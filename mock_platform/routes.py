"""Mock social platform HTTP surface.

Simulates the unreliability of a real social API:
  * OAuth bearer tokens
  * Idempotency-Key enforcement backed by a UNIQUE DB constraint
  * 429 + Retry-After rate limiting (armable)
  * dropped/delayed responses AFTER the post was created server-side
  * asynchronous, HMAC-signed delivery webhooks back to the main app
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from mock_platform import models

logger = logging.getLogger("mock_platform")
router = APIRouter()

SUPPORTED_PLATFORMS = {"instagram", "x"}
CLIENT_SECRET = os.environ.get("MOCK_CLIENT_SECRET", "mock-client-secret")

# token -> platform. Issued by /oauth/token.
_ISSUED_TOKENS: dict[str, str] = {}

# Delay before the delivery webhook fires (seconds). Short for testability.
WEBHOOK_DELAY_SECONDS = float(os.environ.get("MOCK_WEBHOOK_DELAY", "0.5"))


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _webhook_secret() -> str:
    return os.environ.get("WEBHOOK_SECRET", "dev-webhook-secret-change-me")


def _check_platform(platform: str) -> None:
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=404, detail=f"unknown platform '{platform}'")


def _require_bearer(platform: str, authorization: str | None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if _ISSUED_TOKENS.get(token) != platform:
        raise HTTPException(status_code=401, detail="invalid or expired token")


@router.post("/oauth/token")
async def oauth_token(payload: dict):
    platform = payload.get("platform", "")
    _check_platform(platform)
    if payload.get("client_secret") != CLIENT_SECRET:
        raise HTTPException(status_code=401, detail="bad client_secret")
    token = secrets.token_urlsafe(32)
    _ISSUED_TOKENS[token] = platform
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}


async def _deliver_webhook(platform: str, post_id: str, idempotency_key: str) -> None:
    """Fire the signed delivery callback after a short delay."""
    override = models.get_webhook_delay(platform)
    await asyncio.sleep(
        override if override is not None else WEBHOOK_DELAY_SECONDS
    )
    body = json.dumps(
        {
            "platform": platform,
            "external_post_id": post_id,
            "idempotency_key": idempotency_key,
            "status": "delivered",
            "delivered_at": time.time(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    signature = "sha256=" + hmac.new(
        _webhook_secret().encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    url = f"{_app_base_url()}/webhook/social-delivery"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                },
            )
        logger.info("webhook -> %s status=%s", url, resp.status_code)
    except Exception as exc:  # noqa: BLE001 - webhook delivery is best-effort
        logger.warning("webhook delivery to %s failed: %s", url, exc)


@router.post("/platform/{platform}/publish")
async def publish(
    platform: str,
    payload: dict,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _check_platform(platform)
    _require_bearer(platform, authorization)

    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header required")

    # Rate limiting is checked BEFORE any post is created.
    retry_after = models.consume_rate_limit(platform)
    if retry_after is not None:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    caption = payload.get("caption", "")
    image_name = payload.get("image_name")

    # The post is created FIRST, then the response may be dropped. This is the
    # realistic failure mode idempotency exists to survive.
    post, created = models.upsert_post(platform, idempotency_key, caption, image_name)

    if created:
        asyncio.create_task(
            _deliver_webhook(platform, post["id"], idempotency_key)
        )

    delay = models.consume_timeout(platform)
    if delay is not None:
        logger.info(
            "simulate-timeout: post %s created, holding response %.1fs", post["id"], delay
        )
        await asyncio.sleep(delay)

    return JSONResponse(
        status_code=201 if created else 200,
        content={
            "id": post["id"],
            "platform": platform,
            "idempotency_key": idempotency_key,
            "caption": post["caption"],
            "created": created,
            "status": "accepted",
        },
        headers={"Idempotent-Replay": "false" if created else "true"},
    )


@router.get("/platform/{platform}/posts")
async def list_posts(platform: str):
    _check_platform(platform)
    posts = models.list_posts(platform)
    return {"platform": platform, "count": len(posts), "posts": posts}


@router.get("/platform/{platform}/posts/{post_id}")
async def get_post(platform: str, post_id: str):
    _check_platform(platform)
    post = models.get_post(platform, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found")
    return {**post, "status": "delivered"}


@router.post("/platform/{platform}/reset")
async def reset(platform: str):
    _check_platform(platform)
    models.reset(platform)
    return {"platform": platform, "reset": True}


@router.post("/platform/{platform}/rate-limit")
async def arm_rate_limit(platform: str, payload: dict | None = None):
    _check_platform(platform)
    payload = payload or {}
    state = models.set_rate_limit(
        platform, int(payload.get("count", 1)), int(payload.get("retry_after", 2))
    )
    return {"platform": platform, "state": state}


@router.post("/platform/{platform}/simulate-timeout")
async def arm_timeout(platform: str, payload: dict | None = None):
    _check_platform(platform)
    payload = payload or {}
    state = models.set_timeout(
        platform, int(payload.get("count", 1)), float(payload.get("delay", 10.0))
    )
    return {"platform": platform, "state": state}


@router.post("/platform/{platform}/webhook-delay")
async def set_webhook_delay(platform: str, payload: dict | None = None):
    """Control how long delivery callbacks are held back, for demo determinism."""
    _check_platform(platform)
    payload = payload or {}
    state = models.set_webhook_delay(platform, float(payload.get("delay", -1)))
    return {"platform": platform, "state": state}


@router.get("/platform/{platform}/state")
async def platform_state(platform: str):
    _check_platform(platform)
    return models.get_state(platform)


@router.get("/health")
async def health():
    return {"status": "ok", "service": "mock_platform"}
