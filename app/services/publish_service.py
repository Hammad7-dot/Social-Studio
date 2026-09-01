"""Publishing orchestration.

Status machine enforced here:

    queued ──publish() HTTP 2xx──> publishing ──verified webhook──> published
       │                               │
       └──permanent error──> failed <──┘ (retries exhausted)

`published` is NEVER set by this module. Only an HMAC-verified delivery webhook
promotes a post to `published` (see app/api/webhooks.py).

No platform-specific branching appears anywhere below: the publisher comes from
`publisher_factory.get(post.platform)`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.adapters import factory as publisher_factory
from app.adapters.base import PublishError, TransientPublishError
from app.models.social_post import PostStatus, SocialPost

logger = logging.getLogger("social_studio.publish")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def publish_post(db: Session, post: SocialPost) -> SocialPost:
    """Publish one social post. Idempotent and safe to re-run after a crash."""
    if post.status == PostStatus.PUBLISHED:
        logger.info("post %s already published; nothing to do", post.id)
        return post

    publisher = publisher_factory.get(post.platform)

    try:
        result = publisher.publish(
            caption=post.caption,
            image_path=post.image_path,
            # Reused verbatim on every attempt - never regenerated.
            idempotency_key=post.idempotency_key,
        )
    except PublishError as exc:
        post.status = PostStatus.FAILED
        post.failure_reason = str(exc)
        db.commit()
        logger.error("post %s permanently failed: %s", post.id, exc)
        return post
    except TransientPublishError as exc:
        post.status = PostStatus.FAILED
        post.failure_reason = f"retries exhausted: {exc}"
        db.commit()
        logger.error("post %s failed after retries: %s", post.id, exc)
        return post

    # The delivery webhook can legitimately arrive BEFORE this publish call
    # returns (the platform creates the post, then fires the callback, then
    # answers us). Re-read the row so a fast webhook is never downgraded from
    # 'published' back to 'publishing'. The status machine only moves forward.
    db.refresh(post)

    post.external_post_id = result.external_post_id
    if post.status != PostStatus.PUBLISHED:
        # Deliberately NOT 'published' - the platform has only accepted the post.
        post.status = PostStatus.PUBLISHING
    post.failure_reason = None
    db.commit()
    db.refresh(post)
    logger.info(
        "post %s accepted by %s as %s (replayed=%s)",
        post.id,
        post.platform,
        result.external_post_id,
        result.replayed,
    )
    return post


def publish_campaign(db: Session, campaign_id: str) -> list[SocialPost]:
    posts = (
        db.query(SocialPost)
        .filter(SocialPost.campaign_id == campaign_id)
        .order_by(SocialPost.platform)
        .all()
    )
    return [publish_post(db, post) for post in posts]


def mark_published(
    db: Session, platform: str, idempotency_key: str, external_post_id: str
) -> SocialPost | None:
    """Called ONLY from the verified-webhook path."""
    post = (
        db.query(SocialPost)
        .filter(
            SocialPost.platform == platform,
            SocialPost.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if post is None:
        logger.warning(
            "delivery webhook for unknown post platform=%s key=%s",
            platform,
            idempotency_key,
        )
        return None
    if post.status == PostStatus.PUBLISHED:
        return post  # idempotent redelivery
    post.status = PostStatus.PUBLISHED
    post.external_post_id = external_post_id or post.external_post_id
    post.published_at = _utcnow()
    post.failure_reason = None
    db.commit()
    db.refresh(post)
    logger.info("post %s marked published via verified webhook", post.id)
    return post
