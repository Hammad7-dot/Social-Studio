"""Mock platform persistence.

Idempotency is enforced by a REAL SQLite UNIQUE(platform, idempotency_key)
constraint, not by an in-process check. Concurrent duplicate requests therefore
race at the database, and the loser catches IntegrityError and reads back the
row the winner inserted - so both callers receive the SAME post id.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path

_LOCK = threading.Lock()
_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_platform.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_posts (
    id              TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    caption         TEXT NOT NULL,
    image_name      TEXT,
    created_at      REAL NOT NULL,
    UNIQUE (platform, idempotency_key)
);
CREATE TABLE IF NOT EXISTS platform_state (
    platform            TEXT PRIMARY KEY,
    rate_limit_remaining INTEGER NOT NULL DEFAULT 0,
    retry_after          INTEGER NOT NULL DEFAULT 2,
    timeout_remaining    INTEGER NOT NULL DEFAULT 0,
    timeout_delay        REAL NOT NULL DEFAULT 10.0,
    -- Seconds to wait before firing the delivery webhook. -1 means "use the
    -- server-wide default". Raising it lets a demo inspect the 'publishing'
    -- state before delivery lands.
    webhook_delay        REAL NOT NULL DEFAULT -1.0
);
"""


def db_path() -> Path:
    return _DB_PATH


def set_db_path(path: str | Path) -> None:
    """Test hook - point the mock store at an isolated file."""
    global _DB_PATH
    _DB_PATH = Path(path)


def connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _ensure_state(conn: sqlite3.Connection, platform: str) -> sqlite3.Row:
    conn.execute(
        "INSERT OR IGNORE INTO platform_state (platform) VALUES (?)", (platform,)
    )
    return conn.execute(
        "SELECT * FROM platform_state WHERE platform = ?", (platform,)
    ).fetchone()


def get_state(platform: str) -> dict:
    with _LOCK, connect() as conn:
        row = _ensure_state(conn, platform)
        return dict(row)


def set_rate_limit(platform: str, count: int, retry_after: int) -> dict:
    with _LOCK, connect() as conn:
        _ensure_state(conn, platform)
        conn.execute(
            "UPDATE platform_state SET rate_limit_remaining = ?, retry_after = ? "
            "WHERE platform = ?",
            (count, retry_after, platform),
        )
        return dict(_ensure_state(conn, platform))


def set_timeout(platform: str, count: int, delay: float) -> dict:
    with _LOCK, connect() as conn:
        _ensure_state(conn, platform)
        conn.execute(
            "UPDATE platform_state SET timeout_remaining = ?, timeout_delay = ? "
            "WHERE platform = ?",
            (count, delay, platform),
        )
        return dict(_ensure_state(conn, platform))


def consume_rate_limit(platform: str) -> int | None:
    """If a 429 is armed, decrement and return the Retry-After seconds."""
    with _LOCK, connect() as conn:
        row = _ensure_state(conn, platform)
        if row["rate_limit_remaining"] > 0:
            conn.execute(
                "UPDATE platform_state SET rate_limit_remaining = "
                "rate_limit_remaining - 1 WHERE platform = ?",
                (platform,),
            )
            return int(row["retry_after"])
        return None


def consume_timeout(platform: str) -> float | None:
    """If a dropped-response simulation is armed, decrement and return the delay."""
    with _LOCK, connect() as conn:
        row = _ensure_state(conn, platform)
        if row["timeout_remaining"] > 0:
            conn.execute(
                "UPDATE platform_state SET timeout_remaining = "
                "timeout_remaining - 1 WHERE platform = ?",
                (platform,),
            )
            return float(row["timeout_delay"])
        return None


def upsert_post(
    platform: str, idempotency_key: str, caption: str, image_name: str | None
) -> tuple[dict, bool]:
    """Insert, or return the pre-existing post for this idempotency key.

    Returns (post, created). `created` is False when the UNIQUE constraint
    already held a row for (platform, idempotency_key).
    """
    post_id = f"{platform}_{uuid.uuid4().hex[:12]}"
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO platform_posts "
                "(id, platform, idempotency_key, caption, image_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (post_id, platform, idempotency_key, caption, image_name, time.time()),
            )
            conn.commit()
            created = True
        except sqlite3.IntegrityError:
            created = False
        row = conn.execute(
            "SELECT * FROM platform_posts WHERE platform = ? AND idempotency_key = ?",
            (platform, idempotency_key),
        ).fetchone()
    return dict(row), created


def list_posts(platform: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM platform_posts WHERE platform = ? ORDER BY created_at",
            (platform,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_post(platform: str, post_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM platform_posts WHERE platform = ? AND id = ?",
            (platform, post_id),
        ).fetchone()
    return dict(row) if row else None


def reset(platform: str) -> None:
    with _LOCK, connect() as conn:
        conn.execute("DELETE FROM platform_posts WHERE platform = ?", (platform,))
        conn.execute("DELETE FROM platform_state WHERE platform = ?", (platform,))
        conn.commit()


def set_webhook_delay(platform: str, delay: float) -> dict:
    with _LOCK, connect() as conn:
        _ensure_state(conn, platform)
        conn.execute(
            "UPDATE platform_state SET webhook_delay = ? WHERE platform = ?",
            (float(delay), platform),
        )
        return dict(_ensure_state(conn, platform))


def get_webhook_delay(platform: str) -> float | None:
    """Returns the per-platform override, or None to use the global default."""
    with _LOCK, connect() as conn:
        row = _ensure_state(conn, platform)
        value = float(row["webhook_delay"])
    return None if value < 0 else value
