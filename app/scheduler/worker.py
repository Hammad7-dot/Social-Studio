"""Durable scheduling via APScheduler + SQLAlchemyJobStore.

Jobs are persisted in a SQLite file, so they survive a process restart. The job
target is a module-level function referenced by import path (not a closure), so
APScheduler can serialise and later re-resolve it after a restart.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings

logger = logging.getLogger("social_studio.scheduler")

_scheduler: BackgroundScheduler | None = None


def build_scheduler(jobstore_url: str | None = None) -> BackgroundScheduler:
    """Create a scheduler bound to a persistent SQLAlchemy jobstore."""
    url = jobstore_url or get_settings().scheduler_db_url
    scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=url)},
        job_defaults={
            "coalesce": True,  # collapse missed runs into one
            "misfire_grace_time": 3600,  # still run jobs missed during downtime
            "max_instances": 1,
        },
        timezone="UTC",
    )
    return scheduler


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = build_scheduler()
    return _scheduler


def start() -> BackgroundScheduler:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("scheduler started (jobstore=%s)", get_settings().scheduler_db_url)
    return sched


def shutdown(wait: bool = False) -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=wait)
    _scheduler = None


def run_scheduled_publish(campaign_id: str) -> None:
    """APScheduler job target. Must be importable by path and crash-safe.

    Re-running this after a crash is harmless: already-published posts short
    circuit, and everything else retries with its original idempotency key.
    """
    from app.db.database import get_session_factory, init_db
    from app.services import publish_service

    init_db()
    session = get_session_factory()()
    try:
        posts = publish_service.publish_campaign(session, campaign_id)
        logger.info(
            "scheduled publish for campaign %s touched %d posts",
            campaign_id,
            len(posts),
        )
    finally:
        session.close()


def schedule_campaign(
    campaign_id: str, when: datetime, scheduler: BackgroundScheduler | None = None
) -> str:
    """Add a durable one-shot job. Returns the job id."""
    sched = scheduler or start()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    job_id = f"publish:{campaign_id}"
    sched.add_job(
        # String reference so the job survives serialisation/restart.
        "app.scheduler.worker:run_scheduled_publish",
        trigger="date",
        run_date=when,
        args=[campaign_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info("scheduled campaign %s at %s (job %s)", campaign_id, when, job_id)
    return job_id


def list_jobs(scheduler: BackgroundScheduler | None = None) -> list[dict]:
    sched = scheduler or get_scheduler()
    return [
        {
            "id": job.id,
            "next_run_time": (
                job.next_run_time.isoformat() if job.next_run_time else None
            ),
            "args": list(job.args),
        }
        for job in sched.get_jobs()
    ]
