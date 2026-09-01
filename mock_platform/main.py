"""Standalone mock social platform. Runs on port 9000.

    uvicorn mock_platform.main:app --port 9000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mock_platform import models
from mock_platform.routes import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.init_db()
    yield


app = FastAPI(
    title="Mock Social Platform",
    description="Simulates Instagram / X publishing with realistic failure modes.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": "mock_platform",
        "platforms": ["instagram", "x"],
        "docs": "/docs",
    }
