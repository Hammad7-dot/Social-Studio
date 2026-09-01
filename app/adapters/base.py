"""The SocialPublisher abstraction.

Business logic (campaign_service, publish_service, the scheduler worker) talks
ONLY to this interface, obtained from `publisher_factory.get(platform)`. There
is no `if platform == "instagram"` anywhere in the service layer - adding a
third platform means adding one adapter class and one registry entry.
"""
from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import get_settings

logger = logging.getLogger("social_studio.adapters")


class PublishError(Exception):
    """Permanent failure - do not retry."""


class TransientPublishError(Exception):
    """Temporary failure - the caller may retry with the SAME idempotency key."""


class RateLimitedError(TransientPublishError):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


@dataclass
class PublishResult:
    external_post_id: str
    platform: str
    idempotency_key: str
    replayed: bool = False
    raw: dict = field(default_factory=dict)


class SocialPublisher(abc.ABC):
    """Every platform integration implements exactly this contract."""

    platform: str = ""
    image_spec: tuple[int, int] = (0, 0)

    @abc.abstractmethod
    def authenticate(self) -> str:
        """Obtain (and cache) an access token. Returns the token."""

    @abc.abstractmethod
    def publish(
        self, caption: str, image_path: str, idempotency_key: str
    ) -> PublishResult:
        """Publish once. MUST be safe to call repeatedly with the same key."""

    @abc.abstractmethod
    def get_status(self, external_id: str) -> dict:
        """Fetch the platform-side status of a previously published post."""


class HttpMockPublisher(SocialPublisher):
    """Shared HTTP implementation against the mock platform server.

    Concrete platforms subclass this and set `platform` / `image_spec` only.
    All retry, rate-limit and idempotency behaviour lives here, once.
    """

    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.mock_platform_url).rstrip("/")
        self.timeout = settings.publish_timeout_seconds
        self.max_retries = settings.publish_max_retries
        self._client = client
        self._token: str | None = None

    # -- plumbing ---------------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- SocialPublisher --------------------------------------------------
    def authenticate(self) -> str:
        if self._token:
            return self._token
        resp = self._http().post(
            "/oauth/token",
            json={
                "platform": self.platform,
                "client_id": f"social-studio-{self.platform}",
                "client_secret": self._client_secret(),
            },
        )
        if resp.status_code != 200:
            raise PublishError(
                f"{self.platform}: authentication failed ({resp.status_code})"
            )
        self._token = resp.json()["access_token"]
        # NOTE: the token value is deliberately never logged.
        logger.info("%s: authenticated (token redacted)", self.platform)
        return self._token

    def _client_secret(self) -> str:
        import os

        return os.environ.get("MOCK_CLIENT_SECRET", "mock-client-secret")

    def _publish_once(
        self, caption: str, image_path: str, idempotency_key: str
    ) -> PublishResult:
        token = self.authenticate()
        try:
            resp = self._http().post(
                f"/platform/{self.platform}/publish",
                json={
                    "caption": caption,
                    "image_name": image_path.rsplit("/", 1)[-1],
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": idempotency_key,
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # The platform may well have created the post. Retrying with the
            # same idempotency key is the ONLY safe recovery.
            raise TransientPublishError(f"transport failure: {exc}") from exc

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "2"))
            raise RateLimitedError(retry_after)
        if resp.status_code == 401:
            self._token = None
            raise TransientPublishError("token rejected; will re-authenticate")
        if resp.status_code >= 500:
            raise TransientPublishError(f"server error {resp.status_code}")
        if resp.status_code >= 400:
            raise PublishError(f"{self.platform}: {resp.status_code} {resp.text}")

        data = resp.json()
        return PublishResult(
            external_post_id=data["id"],
            platform=self.platform,
            idempotency_key=idempotency_key,
            replayed=not data.get("created", True),
            raw=data,
        )

    def publish(
        self, caption: str, image_path: str, idempotency_key: str
    ) -> PublishResult:
        """Publish with bounded retries.

        The idempotency key is supplied by the caller and NEVER regenerated
        here, so every retry addresses the same platform-side post.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._publish_once(caption, image_path, idempotency_key)
            except RateLimitedError as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                # Honour the server's Retry-After exactly; do not hammer.
                logger.info(
                    "%s: 429 on attempt %d, sleeping %.1fs (Retry-After)",
                    self.platform,
                    attempt,
                    exc.retry_after,
                )
                time.sleep(exc.retry_after)
            except TransientPublishError as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                backoff = min(2 ** (attempt - 1) * 0.5, 4.0)
                logger.info(
                    "%s: transient failure on attempt %d (%s), backing off %.1fs",
                    self.platform,
                    attempt,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
        raise TransientPublishError(
            f"{self.platform}: exhausted {self.max_retries} attempts: {last_exc}"
        )

    def get_status(self, external_id: str) -> dict:
        resp = self._http().get(f"/platform/{self.platform}/posts/{external_id}")
        if resp.status_code == 404:
            raise PublishError(f"{self.platform}: no such post {external_id}")
        resp.raise_for_status()
        return resp.json()
