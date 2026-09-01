"""Social Studio API. Runs on port 8000.

    uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters import factory as publisher_factory
from app.api import campaigns, posts, webhooks
from app.config import get_settings
from app.db.database import init_db
from app.scheduler import worker

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("social_studio")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    worker.start()
    logger.info(
        "Social Studio up. platforms=%s mock_platform=%s dev_secrets=%s",
        publisher_factory.platforms(),
        settings.mock_platform_url,
        settings.using_dev_secrets,
    )
    try:
        yield
    finally:
        worker.shutdown()


app = FastAPI(
    title="Social Studio",
    description="Turn a blog post into platform-native social posts.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(campaigns.router)
app.include_router(posts.router)
app.include_router(webhooks.router)


@app.get("/health", tags=["ops"])
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "service": "social-studio",
        "platforms": publisher_factory.platforms(),
        "mock_platform_url": settings.mock_platform_url,
        "using_dev_secrets": settings.using_dev_secrets,
    }


@app.get("/scheduler/jobs", tags=["ops"])
def scheduler_jobs():
    return {"jobs": worker.list_jobs()}
