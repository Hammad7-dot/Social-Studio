"""Publisher registry.

The ONLY place in the codebase that maps a platform string to a class. Business
logic calls `publisher_factory.get(platform)` and receives a SocialPublisher.
"""
from __future__ import annotations

from typing import Type

from app.adapters.base import SocialPublisher
from app.adapters.fake_instagram import FakeInstagramPublisher
from app.adapters.fake_x import FakeXPublisher

_REGISTRY: dict[str, Type[SocialPublisher]] = {
    FakeInstagramPublisher.platform: FakeInstagramPublisher,
    FakeXPublisher.platform: FakeXPublisher,
}

# Cached instances so OAuth tokens are reused across publishes.
_INSTANCES: dict[str, SocialPublisher] = {}


class UnknownPlatformError(KeyError):
    pass


def register(cls: Type[SocialPublisher]) -> None:
    _REGISTRY[cls.platform] = cls
    _INSTANCES.pop(cls.platform, None)


def platforms() -> list[str]:
    return sorted(_REGISTRY)


def get(platform: str) -> SocialPublisher:
    if platform not in _REGISTRY:
        raise UnknownPlatformError(
            f"no publisher registered for platform '{platform}'"
        )
    if platform not in _INSTANCES:
        _INSTANCES[platform] = _REGISTRY[platform]()
    return _INSTANCES[platform]


def reset() -> None:
    """Test hook - drop cached instances (and their tokens/clients)."""
    for inst in _INSTANCES.values():
        close = getattr(inst, "close", None)
        if callable(close):
            close()
    _INSTANCES.clear()
