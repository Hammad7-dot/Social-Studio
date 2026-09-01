from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.campaign import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class PostStatus:
    """Explicit status machine.

    queued      -> created by campaign_service, nothing sent yet
    publishing  -> accepted by the platform (HTTP 2xx from publish call)
    published   -> ONLY set by an HMAC-verified delivery webhook
    failed      -> permanent failure (auth error, retries exhausted)
    """

    QUEUED = "queued"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"

    ALL = (QUEUED, PUBLISHING, PUBLISHED, FAILED)


class SocialPost(Base):
    __tablename__ = "social_posts"
    __table_args__ = (
        UniqueConstraint(
            "platform", "idempotency_key", name="uq_social_post_platform_idem"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PostStatus.QUEUED
    )
    # Deterministic, assigned exactly once at row creation, reused on every retry.
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    external_post_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    campaign = relationship("Campaign", back_populates="social_posts")
