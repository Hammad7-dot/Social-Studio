"""Durability of the APScheduler SQLAlchemy jobstore across process-like restarts."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.scheduler import worker


def _jobstore_url(tmp_path: Path) -> tuple[str, Path]:
    db = tmp_path / "jobs.db"
    return f"sqlite:///{db}", db


def test_job_survives_scheduler_teardown_and_reload(tmp_path: Path):
    url, db_file = _jobstore_url(tmp_path)
    when = datetime.now(timezone.utc) + timedelta(hours=2)

    # --- "process 1" -------------------------------------------------
    sched_a = worker.build_scheduler(url)
    sched_a.start(paused=True)
    job_id = worker.schedule_campaign("camp-abc", when, scheduler=sched_a)
    assert job_id in [j["id"] for j in worker.list_jobs(sched_a)]
    sched_a.shutdown(wait=False)

    assert db_file.exists(), "jobstore sqlite file was not created"

    # --- "process 2": brand new scheduler, same jobstore file ---------
    sched_b = worker.build_scheduler(url)
    sched_b.start(paused=True)
    jobs = worker.list_jobs(sched_b)
    sched_b.shutdown(wait=False)

    ids = [j["id"] for j in jobs]
    assert job_id in ids, f"job lost across restart; found {ids}"
    reloaded = [j for j in jobs if j["id"] == job_id][0]
    assert reloaded["args"] == ["camp-abc"]
    assert reloaded["next_run_time"] is not None


def test_job_row_is_actually_persisted_in_sqlite(tmp_path: Path):
    url, db_file = _jobstore_url(tmp_path)
    sched = worker.build_scheduler(url)
    sched.start(paused=True)
    worker.schedule_campaign(
        "camp-persist", datetime.now(timezone.utc) + timedelta(days=1), scheduler=sched
    )
    sched.shutdown(wait=False)

    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT id FROM apscheduler_jobs").fetchall()
    assert [r[0] for r in rows] == ["publish:camp-persist"]


def test_rescheduling_replaces_rather_than_duplicates(tmp_path: Path):
    url, _ = _jobstore_url(tmp_path)
    sched = worker.build_scheduler(url)
    sched.start(paused=True)
    now = datetime.now(timezone.utc)
    worker.schedule_campaign("camp-1", now + timedelta(hours=1), scheduler=sched)
    worker.schedule_campaign("camp-1", now + timedelta(hours=5), scheduler=sched)
    jobs = worker.list_jobs(sched)
    sched.shutdown(wait=False)
    assert len(jobs) == 1


def test_scheduled_job_target_is_importable_by_path():
    """APScheduler stores a string reference; it must resolve after a restart."""
    import importlib

    mod = importlib.import_module("app.scheduler.worker")
    assert callable(getattr(mod, "run_scheduled_publish"))


def test_scheduled_run_is_crash_safe_and_idempotent(db_session, wired, monkeypatch):
    """Re-running a scheduled publish must not create duplicate platform posts."""
    from app.services import campaign_service
    from mock_platform import models as mock_models

    campaign = campaign_service.create_campaign(
        db_session,
        title="Crash safety",
        body="A worker that dies mid-publish must be safe to restart. " * 4,
        url="https://example.com/blog/crash",
    )

    import app.db.database as database

    monkeypatch.setattr(
        database, "get_session_factory", lambda: (lambda: db_session)
    )

    worker.run_scheduled_publish(campaign.id)
    worker.run_scheduled_publish(campaign.id)  # simulated restart / re-run

    assert len(mock_models.list_posts("instagram")) == 1
    assert len(mock_models.list_posts("x")) == 1
