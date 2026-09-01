"""429 handling: Retry-After must be honoured, and the publish must eventually succeed."""
from __future__ import annotations

import time

from app.adapters.base import RateLimitedError
from app.models.social_post import PostStatus
from app.services import campaign_service, publish_service
from mock_platform import models as mock_models

RETRY_AFTER = 2


def _campaign(db):
    return campaign_service.create_campaign(
        db,
        title="Backpressure is a feature",
        body="A 429 is the platform telling you the truth about its capacity. " * 4,
        url="https://example.com/blog/rate-limits",
    )


def test_mock_returns_429_with_retry_after_header(db_session, wired):
    campaign = _campaign(db_session)
    post = campaign_service.get_posts(db_session, campaign.id)[0]

    mock_models.set_rate_limit(post.platform, count=1, retry_after=RETRY_AFTER)

    publisher = wired.get(post.platform)
    try:
        publisher._publish_once(post.caption, post.image_path, post.idempotency_key)
    except RateLimitedError as exc:
        assert exc.retry_after == RETRY_AFTER
    else:
        raise AssertionError("expected a RateLimitedError on the armed 429")


def test_retry_after_is_honoured_then_publish_succeeds(db_session, wired):
    campaign = _campaign(db_session)
    post = [
        p
        for p in campaign_service.get_posts(db_session, campaign.id)
        if p.platform == "instagram"
    ][0]

    mock_models.set_rate_limit("instagram", count=1, retry_after=RETRY_AFTER)

    started = time.monotonic()
    result = wired.get("instagram").publish(
        post.caption, post.image_path, post.idempotency_key
    )
    elapsed = time.monotonic() - started

    assert result.external_post_id
    # The client must have actually waited, not hammered the endpoint.
    assert elapsed >= RETRY_AFTER, f"retried after only {elapsed:.2f}s"
    assert len(mock_models.list_posts("instagram")) == 1


def test_publish_service_recovers_from_rate_limit(db_session, wired):
    campaign = _campaign(db_session)
    mock_models.set_rate_limit("x", count=2, retry_after=1)

    posts = publish_service.publish_campaign(db_session, campaign.id)
    x_post = [p for p in posts if p.platform == "x"][0]

    assert x_post.status == PostStatus.PUBLISHING, x_post.failure_reason
    assert x_post.external_post_id


def test_exhausted_retries_marks_failed_not_published(db_session, wired):
    campaign = _campaign(db_session)
    # More 429s than the client has attempts.
    mock_models.set_rate_limit("x", count=99, retry_after=0)

    posts = publish_service.publish_campaign(db_session, campaign.id)
    x_post = [p for p in posts if p.platform == "x"][0]

    assert x_post.status == PostStatus.FAILED
    assert "retries exhausted" in (x_post.failure_reason or "")
    assert len(mock_models.list_posts("x")) == 0
