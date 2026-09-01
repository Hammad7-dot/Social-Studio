"""Webhook security and the queued -> publishing -> published status machine."""
from __future__ import annotations

import json

from app.models.social_post import PostStatus, SocialPost
from app.security import webhook as webhook_security
from app.services import campaign_service, publish_service


def _seed(db, client):
    campaign = campaign_service.create_campaign(
        db,
        title="Verify before you trust",
        body="An unsigned webhook is an unauthenticated state transition. " * 4,
        url="https://example.com/blog/webhooks",
    )
    publish_service.publish_campaign(db, campaign.id)
    posts = campaign_service.get_posts(db, campaign.id)
    return campaign, posts


def _payload(post) -> bytes:
    return json.dumps(
        {
            "platform": post.platform,
            "external_post_id": post.external_post_id or "ext-1",
            "idempotency_key": post.idempotency_key,
            "status": "delivered",
        },
        separators=(",", ":"),
    ).encode()


def test_sign_and_verify_roundtrip():
    body = b'{"hello":"world"}'
    sig = webhook_security.sign(body, "s3cret")
    assert sig.startswith("sha256=")
    assert webhook_security.verify(body, sig, "s3cret") is True
    assert webhook_security.verify(body + b" ", sig, "s3cret") is False
    assert webhook_security.verify(body, sig, "other-secret") is False
    assert webhook_security.verify(body, None, "s3cret") is False


def test_forged_signature_rejected_and_status_unchanged(
    main_client, db_session, wired
):
    campaign, posts = _seed(db_session, main_client)
    post = posts[0]
    assert post.status == PostStatus.PUBLISHING

    body = _payload(post)
    resp = main_client.post(
        "/webhook/social-delivery",
        content=body,
        headers={
            "X-Signature": "sha256=" + "0" * 64,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400, resp.text

    db_session.expire_all()
    refreshed = db_session.get(SocialPost, post.id)
    assert refreshed.status == PostStatus.PUBLISHING
    assert refreshed.published_at is None


def test_missing_signature_rejected(main_client, db_session, wired):
    campaign, posts = _seed(db_session, main_client)
    resp = main_client.post(
        "/webhook/social-delivery",
        content=_payload(posts[0]),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_tampered_body_rejected(main_client, db_session, wired):
    campaign, posts = _seed(db_session, main_client)
    post = posts[0]
    body = _payload(post)
    sig = webhook_security.sign(body)

    tampered = body.replace(b'"delivered"', b'"delivered "')
    resp = main_client.post(
        "/webhook/social-delivery",
        content=tampered,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    db_session.expire_all()
    assert db_session.get(SocialPost, post.id).status == PostStatus.PUBLISHING


def test_valid_signature_promotes_to_published(main_client, db_session, wired):
    campaign, posts = _seed(db_session, main_client)
    post = posts[0]
    body = _payload(post)

    resp = main_client.post(
        "/webhook/social-delivery",
        content=body,
        headers={
            "X-Signature": webhook_security.sign(body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] is True

    db_session.expire_all()
    refreshed = db_session.get(SocialPost, post.id)
    assert refreshed.status == PostStatus.PUBLISHED
    assert refreshed.published_at is not None


def test_webhook_redelivery_is_idempotent(main_client, db_session, wired):
    campaign, posts = _seed(db_session, main_client)
    post = posts[0]
    body = _payload(post)
    headers = {
        "X-Signature": webhook_security.sign(body),
        "Content-Type": "application/json",
    }
    first = main_client.post("/webhook/social-delivery", content=body, headers=headers)
    second = main_client.post("/webhook/social-delivery", content=body, headers=headers)
    assert first.status_code == 200 and second.status_code == 200

    db_session.expire_all()
    refreshed = db_session.get(SocialPost, post.id)
    assert refreshed.status == PostStatus.PUBLISHED


def test_publish_alone_never_sets_published(db_session, wired):
    """HTTP 200 from the platform is NOT proof of delivery."""
    campaign = campaign_service.create_campaign(
        db_session,
        title="Accepted is not delivered",
        body="Two different facts. " * 12,
        url="https://example.com/blog/status",
    )
    posts = publish_service.publish_campaign(db_session, campaign.id)
    assert all(p.status == PostStatus.PUBLISHING for p in posts)
    assert all(p.published_at is None for p in posts)
