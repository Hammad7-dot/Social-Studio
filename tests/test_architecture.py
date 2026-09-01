"""Architecture guardrails - the abstraction must not be bypassed."""
from __future__ import annotations

import re
from pathlib import Path

SERVICE_FILES = [
    Path("app/services/publish_service.py"),
    Path("app/services/campaign_service.py"),
    Path("app/scheduler/worker.py"),
    Path("app/api/campaigns.py"),
    Path("app/api/webhooks.py"),
]

BRANCH_PATTERN = re.compile(
    r"""(if|elif)\s+[^\n]*platform[^\n]*==\s*["'](instagram|x|twitter)["']""",
    re.IGNORECASE,
)


def test_no_platform_branching_in_business_logic():
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for rel in SERVICE_FILES:
        text = (root / rel).read_text()
        for match in BRANCH_PATTERN.finditer(text):
            offenders.append(f"{rel}: {match.group(0)}")
    assert not offenders, "platform-specific branching leaked into business logic:\n" + "\n".join(offenders)


def test_all_publishers_implement_the_interface():
    from app.adapters import factory
    from app.adapters.base import SocialPublisher

    for platform in factory.platforms():
        pub = factory.get(platform)
        assert isinstance(pub, SocialPublisher)
        assert pub.platform == platform
        for method in ("authenticate", "publish", "get_status"):
            assert callable(getattr(pub, method))


def test_factory_rejects_unknown_platform():
    import pytest

    from app.adapters import factory

    with pytest.raises(factory.UnknownPlatformError):
        factory.get("myspace")


def test_adding_a_platform_needs_only_an_adapter():
    from app.adapters import factory
    from app.adapters.base import HttpMockPublisher

    class FakeThreadsPublisher(HttpMockPublisher):
        platform = "threads"
        image_spec = (1080, 1350)

    try:
        factory.register(FakeThreadsPublisher)
        assert "threads" in factory.platforms()
        assert isinstance(factory.get("threads"), FakeThreadsPublisher)
    finally:
        factory._REGISTRY.pop("threads", None)
        factory._INSTANCES.pop("threads", None)
