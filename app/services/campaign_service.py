"""Campaign orchestration: validate -> persist -> images -> captions -> rows."""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters import factory as publisher_factory
from app.config import get_settings
from app.models.campaign import Campaign
from app.models.social_post import PostStatus, SocialPost
from app.services import caption_service, image_service

logger = logging.getLogger("social_studio.campaign")


class ValidationError(ValueError):
    pass


def build_idempotency_key(social_post_id: str, platform: str) -> str:
    """Deterministic key derived from the social_post row's own UUID.

    Stored once at row creation and reused verbatim on every retry, so a
    retried publish always addresses the same platform-side post.
    """
    digest = hashlib.sha256(f"{platform}:{social_post_id}".encode()).hexdigest()
    return f"ss-{platform}-{digest[:32]}"


def _validate(title: str, body: str, url: str) -> None:
    if not title or not title.strip():
        raise ValidationError("title is required")
    if not body or not body.strip():
        raise ValidationError("body is required")
    if not url or not url.strip():
        raise ValidationError("url is required")
    if not url.startswith(("http://", "https://")):
        raise ValidationError("url must start with http:// or https://")


def _resolve_source_image(campaign_id: str, source_image: str | None) -> str:
    if source_image and Path(source_image).exists():
        return source_image
    if source_image:
        logger.warning(
            "source_image %s not found; using generated placeholder", source_image
        )
    placeholder = (
        Path(get_settings().artifacts_dir) / "sources" / f"{campaign_id}_source.png"
    )
    image_service.make_placeholder_source(placeholder)
    return str(placeholder)


def create_campaign(
    db: Session,
    title: str,
    body: str,
    url: str,
    source_image: str | None = None,
    platforms: list[str] | None = None,
) -> Campaign:
    _validate(title, body, url)

    platforms = platforms or publisher_factory.platforms()
    unknown = [p for p in platforms if p not in publisher_factory.platforms()]
    if unknown:
        raise ValidationError(f"unsupported platforms: {unknown}")

    campaign = Campaign(
        id=str(uuid.uuid4()),
        title=title.strip(),
        body=body.strip(),
        url=url.strip(),
        source_image=source_image,
    )
    db.add(campaign)
    db.flush()

    resolved_source = _resolve_source_image(campaign.id, source_image)
    campaign.source_image = resolved_source

    variants = image_service.generate_variants(campaign.id, resolved_source, platforms)

    for platform in platforms:
        post_id = str(uuid.uuid4())
        db.add(
            SocialPost(
                id=post_id,
                campaign_id=campaign.id,
                platform=platform,
                caption=caption_service.build_caption(
                    platform, campaign.title, campaign.body, campaign.url
                ),
                image_path=variants[platform],
                status=PostStatus.QUEUED,
                idempotency_key=build_idempotency_key(post_id, platform),
            )
        )

    db.commit()
    db.refresh(campaign)
    logger.info(
        "campaign %s created with %d queued posts", campaign.id, len(platforms)
    )
    return campaign


def get_campaign(db: Session, campaign_id: str) -> Campaign | None:
    return db.get(Campaign, campaign_id)


def get_posts(db: Session, campaign_id: str) -> list[SocialPost]:
    return (
        db.query(SocialPost)
        .filter(SocialPost.campaign_id == campaign_id)
        .order_by(SocialPost.platform)
        .all()
    )
