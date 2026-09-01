from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import SocialPostOut
from app.db.database import get_db
from app.models.social_post import SocialPost

router = APIRouter(prefix="/social-posts", tags=["social-posts"])


@router.get("/{post_id}", response_model=SocialPostOut)
def get_social_post(post_id: str, db: Session = Depends(get_db)):
    post = db.get(SocialPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="social post not found")
    return SocialPostOut.model_validate(post)
