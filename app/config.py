"""Environment-driven configuration with safe development defaults.

Design rule: the application must NEVER crash because an env var is missing.
Missing security-critical values fall back to well-known dev values and emit a
loud warning so nobody accidentally ships them.
"""
from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("social_studio.config")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Well-known INSECURE dev fallbacks. Used only when env is unset.
_DEV_ENCRYPTION_KEY = base64.b64encode(b"dev-only-insecure-key-32-bytes!!").decode()
_DEV_WEBHOOK_SECRET = "dev-webhook-secret-change-me"


def _decode_key(raw: str) -> bytes:
    """Accept base64 or hex; pad/truncate deterministically to 32 bytes."""
    for decoder in (base64.b64decode, bytes.fromhex):
        try:
            candidate = decoder(raw)
            if len(candidate) == 32:
                return candidate
        except Exception:  # noqa: BLE001 - try the next encoding
            continue
    # Last resort: derive a 32-byte key from the raw string bytes.
    data = raw.encode("utf-8")
    return (data * (32 // max(len(data), 1) + 1))[:32]


@dataclass
class Settings:
    encryption_key: bytes = field(repr=False, default=b"")
    webhook_secret: str = field(repr=False, default="")
    mock_platform_url: str = "http://127.0.0.1:9000"
    app_base_url: str = "http://127.0.0.1:8000"
    database_url: str = ""
    scheduler_db_url: str = ""
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"
    publish_timeout_seconds: float = 5.0
    publish_max_retries: int = 4
    using_dev_secrets: bool = False

    @classmethod
    def load(cls) -> "Settings":
        using_dev = False

        raw_key = os.environ.get("ENCRYPTION_KEY")
        if not raw_key:
            raw_key = _DEV_ENCRYPTION_KEY
            using_dev = True

        secret = os.environ.get("WEBHOOK_SECRET")
        if not secret:
            secret = _DEV_WEBHOOK_SECRET
            using_dev = True

        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        artifacts_dir = Path(
            os.environ.get("ARTIFACTS_DIR", str(PROJECT_ROOT / "artifacts"))
        )
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        settings = cls(
            encryption_key=_decode_key(raw_key),
            webhook_secret=secret,
            mock_platform_url=os.environ.get(
                "MOCK_PLATFORM_URL", "http://127.0.0.1:9000"
            ).rstrip("/"),
            app_base_url=os.environ.get(
                "APP_BASE_URL", "http://127.0.0.1:8000"
            ).rstrip("/"),
            database_url=os.environ.get(
                "DATABASE_URL", f"sqlite:///{data_dir / 'social_studio.db'}"
            ),
            scheduler_db_url=os.environ.get(
                "SCHEDULER_DB_URL", f"sqlite:///{data_dir / 'scheduler.db'}"
            ),
            artifacts_dir=artifacts_dir,
            publish_timeout_seconds=float(
                os.environ.get("PUBLISH_TIMEOUT_SECONDS", "5")
            ),
            publish_max_retries=int(os.environ.get("PUBLISH_MAX_RETRIES", "4")),
            using_dev_secrets=using_dev,
        )

        if using_dev:
            logger.warning(
                "ENCRYPTION_KEY and/or WEBHOOK_SECRET not set - using INSECURE "
                "development defaults. Do NOT use these in production."
            )
        return settings


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def reset_settings() -> None:
    """Used by tests that mutate the environment."""
    global _settings
    _settings = None
