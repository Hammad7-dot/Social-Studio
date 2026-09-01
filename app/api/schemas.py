from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    source_image: str | None = None
    platforms: list[str] | None = None


class SocialPostOut(BaseModel):
    id: str
    campaign_id: str
    platform: str
    caption: str
    image_path: str
    status: str
    idempotency_key: str
    external_post_id: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    failure_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CampaignOut(BaseModel):
    id: str
    title: str
    body: str
    url: str
    source_image: str | None = None
    created_at: datetime
    social_posts: list[SocialPostOut] = []

    model_config = ConfigDict(from_attributes=True)


class ScheduleRequest(BaseModel):
    run_at: datetime | None = None
    delay_seconds: float | None = None
