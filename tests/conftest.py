"""Shared test fixtures.

The mock platform is a genuinely separate FastAPI app, so tests run it on a
real uvicorn server in a background thread on an ephemeral port. That keeps the
adapters' *real* synchronous httpx code path under test - headers, status
codes, Retry-After, client timeouts - rather than a stubbed transport.

The main app is exercised through FastAPI's TestClient. Webhook tests sign
payloads with the production signing helper and POST them at the real endpoint,
which covers the same bytes the mock platform would send.
"""
from __future__ import annotations

import os
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent
TMP = TEST_ROOT / "_tmp"
TMP.mkdir(parents=True, exist_ok=True)

os.environ["ENCRYPTION_KEY"] = "dGVzdC1rZXktdGhpcnR5LXR3by1ieXRlcy0xMjM0NTY="
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["SCHEDULER_DB_URL"] = f"sqlite:///{TMP / 'sched.db'}"
os.environ["ARTIFACTS_DIR"] = str(TMP / "artifacts")
os.environ["PUBLISH_TIMEOUT_SECONDS"] = "1"
os.environ["PUBLISH_MAX_RETRIES"] = "4"
# No outbound webhook from the mock during tests: the main app is a TestClient,
# not a listening socket. Webhook delivery is covered by tests/test_webhooks.py
# and by the live end-to-end run recorded in EVIDENCE.md.
os.environ["MOCK_WEBHOOK_DELAY"] = "0"
os.environ["APP_BASE_URL"] = "http://127.0.0.1:1"  # deliberately unreachable


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def _clean_tmp():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture(scope="session")
def mock_server(_clean_tmp):
    """Run the mock platform on a real port for the whole test session."""
    import uvicorn

    from mock_platform import models as mock_models

    mock_models.set_db_path(TMP / "mock_platform.db")
    mock_models.init_db()

    from mock_platform.main import app as mock_fastapi

    port = _free_port()
    config = uvicorn.Config(
        mock_fastapi, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:  # pragma: no cover
        raise RuntimeError("mock platform server failed to start")

    url = f"http://127.0.0.1:{port}"
    os.environ["MOCK_PLATFORM_URL"] = url
    yield url

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def app_db(mock_server):
    """Fresh main-app database per test."""
    from app import config
    from app.db import database

    db_file = TMP / f"app_{os.urandom(4).hex()}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    config.reset_settings()
    database.reset_engine()
    database.init_db()
    yield database
    database.reset_engine()


@pytest.fixture()
def db_session(app_db):
    session = app_db.get_session_factory()()
    yield session
    session.close()


@pytest.fixture()
def wired(app_db, mock_server):
    """Fresh publisher instances pointed at the running mock platform.

    Also wipes the mock platform's per-platform state so each test starts from
    an empty store with no armed 429 / timeout simulations.
    """
    import httpx

    from app.adapters import factory as publisher_factory

    for platform in ("instagram", "x", "threads"):
        try:
            httpx.post(f"{mock_server}/platform/{platform}/reset", timeout=5)
        except Exception:  # noqa: BLE001 - unknown platforms 404, which is fine
            pass

    publisher_factory.reset()
    yield publisher_factory
    publisher_factory.reset()


@pytest.fixture()
def main_client(app_db, wired):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client
