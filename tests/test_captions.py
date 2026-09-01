"""Caption composition: shared voice + per-platform rules, deterministic."""
from __future__ import annotations

from app.services import caption_service

TITLE = "How we cut publish latency by 60%"
BODY = (
    "We replaced a synchronous fan-out with a queue and a durable scheduler. "
    "The result was fewer timeouts and far fewer duplicate posts. "
) * 10
URL = "https://example.com/blog/latency"


def test_x_caption_respects_280_char_limit():
    caption = caption_service.build_caption("x", TITLE, BODY, URL)
    assert len(caption) <= 280, f"caption was {len(caption)} chars"
    assert URL in caption, "X captions must carry the link"


def test_instagram_caption_omits_url_and_carries_more_tags():
    caption = caption_service.build_caption("instagram", TITLE, BODY, URL)
    assert len(caption) <= 2200
    assert URL not in caption, "IG captions must not include a non-clickable URL"
    assert caption.count("#") > 2


def test_captions_are_deterministic():
    a = caption_service.build_caption("x", TITLE, BODY, URL)
    b = caption_service.build_caption("x", TITLE, BODY, URL)
    assert a == b


def test_shared_brand_voice_present_on_every_platform():
    for platform in caption_service.supported_platforms():
        caption = caption_service.build_caption(platform, TITLE, BODY, URL)
        assert TITLE in caption
        assert "#buildinpublic" in caption


def test_optional_ai_hook_is_pluggable():
    caption_service.set_ai_rewriter(lambda platform, text: f"[{platform}] {text}")
    try:
        caption = caption_service.build_caption("x", TITLE, BODY, URL)
        assert caption.startswith("[x] ")
    finally:
        caption_service.set_ai_rewriter(None)


def test_unknown_platform_rejected():
    import pytest

    with pytest.raises(ValueError):
        caption_service.build_caption("myspace", TITLE, BODY, URL)
