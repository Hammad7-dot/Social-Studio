from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    CampaignCreate,
    CampaignOut,
    ScheduleRequest,
    SocialPostOut,
)
from app.db.database import get_db
from app.scheduler import worker
from app.services import campaign_service, publish_service

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    try:
        campaign = campaign_service.create_campaign(
            db,
            title=payload.title,
            body=payload.body,
            url=payload.url,
            source_image=payload.source_image,
            platforms=payload.platforms,
        )
    except campaign_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(db, campaign)


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = campaign_service.get_campaign(db, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return _serialize(db, campaign)


@router.post("/{campaign_id}/publish", response_model=list[SocialPostOut])
def publish_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = campaign_service.get_campaign(db, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    posts = publish_service.publish_campaign(db, campaign_id)
    return [SocialPostOut.model_validate(p) for p in posts]


@router.post("/{campaign_id}/schedule")
def schedule_campaign(
    campaign_id: str, payload: ScheduleRequest, db: Session = Depends(get_db)
):
    campaign = campaign_service.get_campaign(db, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")

    if payload.run_at is not None:
        when = payload.run_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    else:
        when = datetime.now(timezone.utc) + timedelta(
            seconds=payload.delay_seconds or 60
        )

    job_id = worker.schedule_campaign(campaign_id, when)

    for post in campaign_service.get_posts(db, campaign_id):
        post.scheduled_at = when.replace(tzinfo=None)
    db.commit()

    return {
        "campaign_id": campaign_id,
        "job_id": job_id,
        "scheduled_at": when.isoformat(),
        "jobs": worker.list_jobs(),
    }


def _serialize(db: Session, campaign):
    posts = campaign_service.get_posts(db, campaign.id)
    return CampaignOut(
        id=campaign.id,
        title=campaign.title,
        body=campaign.body,
        url=campaign.url,
        source_image=campaign.source_image,
        created_at=campaign.created_at,
        social_posts=[SocialPostOut.model_validate(p) for p in posts],
    )
