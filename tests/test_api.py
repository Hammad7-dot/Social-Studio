"""End-to-end API surface through FastAPI TestClient."""
from __future__ import annotations

from PIL import Image

PAYLOAD = {
    "title": "Designing for platforms that lie to you",
    "body": "Real APIs time out, rate limit, and duplicate. " * 8,
    "url": "https://example.com/blog/platforms",
}


def test_health(main_client):
    resp = main_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["platforms"]) == {"instagram", "x"}


def test_create_get_and_publish_campaign(main_client):
    created = main_client.post("/campaigns", json=PAYLOAD)
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert len(campaign["social_posts"]) == 2

    by_platform = {p["platform"]: p for p in campaign["social_posts"]}
    with Image.open(by_platform["instagram"]["image_path"]) as im:
        assert im.size == (1080, 1080)
    with Image.open(by_platform["x"]["image_path"]) as im:
        assert im.size == (1600, 900)
    assert all(p["status"] == "queued" for p in campaign["social_posts"])

    fetched = main_client.get(f"/campaigns/{campaign['id']}")
    assert fetched.status_code == 200

    published = main_client.post(f"/campaigns/{campaign['id']}/publish")
    assert published.status_code == 200, published.text
    posts = published.json()
    assert all(p["status"] == "publishing" for p in posts), posts
    assert all(p["external_post_id"] for p in posts)

    single = main_client.get(f"/social-posts/{posts[0]['id']}")
    assert single.status_code == 200
    assert single.json()["id"] == posts[0]["id"]


def test_validation_errors(main_client):
    bad = main_client.post("/campaigns", json={**PAYLOAD, "url": "not-a-url"})
    assert bad.status_code == 422

    missing = main_client.post("/campaigns", json={"title": "x"})
    assert missing.status_code == 422

    unknown = main_client.post("/campaigns", json={**PAYLOAD, "platforms": ["myspace"]})
    assert unknown.status_code == 422


def test_404s(main_client):
    assert main_client.get("/campaigns/does-not-exist").status_code == 404
    assert main_client.get("/social-posts/does-not-exist").status_code == 404
    assert main_client.post("/campaigns/nope/publish").status_code == 404


def test_schedule_endpoint_registers_durable_job(main_client):
    campaign = main_client.post("/campaigns", json=PAYLOAD).json()
    resp = main_client.post(
        f"/campaigns/{campaign['id']}/schedule", json={"delay_seconds": 3600}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == f"publish:{campaign['id']}"
    assert body["job_id"] in [j["id"] for j in body["jobs"]]

    jobs = main_client.get("/scheduler/jobs").json()["jobs"]
    assert body["job_id"] in [j["id"] for j in jobs]
