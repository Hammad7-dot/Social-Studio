"""Idempotency: duplicate publishes must never create duplicate platform posts."""
from __future__ import annotations

import concurrent.futures

from mock_platform import models as mock_models
from app.models.social_post import PostStatus
from app.services import campaign_service, publish_service


def _make_campaign(db):
    return campaign_service.create_campaign(
        db,
        title="Shipping a durable publisher",
        body="Retries are only safe when they are idempotent. " * 6,
        url="https://example.com/blog/idempotency",
    )


def test_idempotency_key_is_deterministic_and_stored_once(db_session, wired):
    campaign = _make_campaign(db_session)
    posts = campaign_service.get_posts(db_session, campaign.id)
    for post in posts:
        expected = campaign_service.build_idempotency_key(post.id, post.platform)
        assert post.idempotency_key == expected
        # Recomputing must give the identical value - keys are never random.
        assert expected == campaign_service.build_idempotency_key(
            post.id, post.platform
        )


def test_double_publish_creates_exactly_one_platform_post(db_session, wired):
    campaign = _make_campaign(db_session)

    first = publish_service.publish_campaign(db_session, campaign.id)
    second = publish_service.publish_campaign(db_session, campaign.id)

    for platform in ("instagram", "x"):
        posts = mock_models.list_posts(platform)
        assert len(posts) == 1, f"{platform} had {len(posts)} posts, expected 1"

    ids_first = {p.platform: p.external_post_id for p in first}
    ids_second = {p.platform: p.external_post_id for p in second}
    assert ids_first == ids_second
    assert all(p.status == PostStatus.PUBLISHING for p in second)


def test_concurrent_duplicate_publishes_collapse_to_one(db_session, wired):
    """The UNIQUE(platform, idempotency_key) constraint arbitrates the race."""
    campaign = _make_campaign(db_session)
    post = [
        p
        for p in campaign_service.get_posts(db_session, campaign.id)
        if p.platform == "instagram"
    ][0]

    publisher = wired.get("instagram")
    publisher.authenticate()

    def attempt():
        return publisher.publish(post.caption, post.image_path, post.idempotency_key)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = [f.result() for f in [pool.submit(attempt) for _ in range(6)]]

    external_ids = {r.external_post_id for r in results}
    assert len(external_ids) == 1, f"got divergent post ids: {external_ids}"
    assert len(mock_models.list_posts("instagram")) == 1


def test_timeout_recovery_does_not_duplicate(db_session, wired):
    """Post is created server-side, response is dropped, client retries.

    The retry uses the SAME idempotency key, so the end state is one post.
    """
    campaign = _make_campaign(db_session)
    post = [
        p
        for p in campaign_service.get_posts(db_session, campaign.id)
        if p.platform == "x"
    ][0]

    # Arm one dropped response, delayed well past the 1s client timeout.
    mock_models.set_timeout("x", count=1, delay=3.0)

    result = wired.get("x").publish(
        post.caption, post.image_path, post.idempotency_key
    )

    posts = mock_models.list_posts("x")
    assert len(posts) == 1, f"timeout retry duplicated the post: {posts}"
    assert result.external_post_id == posts[0]["id"]
    # The second attempt saw the row already there -> it was an idempotent replay.
    assert result.replayed is True
