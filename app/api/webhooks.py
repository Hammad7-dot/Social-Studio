"""Signed delivery webhook endpoint.

Security posture:
  * signature computed over the RAW body bytes (never a re-serialised dict)
  * constant-time comparison
  * an invalid signature returns 400 and mutates NOTHING
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security import webhook as webhook_security
from app.services import publish_service

logger = logging.getLogger("social_studio.webhooks")
router = APIRouter(tags=["webhooks"])


@router.post("/webhook/social-delivery")
async def social_delivery(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None, alias="X-Signature"),
):
    raw = await request.body()

    if not webhook_security.verify(raw, x_signature):
        logger.warning("rejected delivery webhook: invalid signature")
        raise HTTPException(status_code=400, detail="invalid signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="malformed json") from exc

    platform = payload.get("platform")
    idem = payload.get("idempotency_key")
    external_id = payload.get("external_post_id")
    if not platform or not idem:
        raise HTTPException(
            status_code=400, detail="platform and idempotency_key are required"
        )

    post = publish_service.mark_published(db, platform, idem, external_id)
    if post is None:
        # Verified, but we have no matching row. Ack so the sender stops
        # retrying, and report that nothing was updated.
        return {"ok": True, "updated": False, "reason": "no matching social post"}

    return {
        "ok": True,
        "updated": True,
        "social_post_id": post.id,
        "status": post.status,
    }
