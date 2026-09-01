"""Deterministic caption generation.

A single shared brand voice is composed with per-platform rules. The renderer
is deterministic (no AI call, no network), which makes captions testable and
reproducible. An optional AI hook can be injected later via `set_ai_rewriter`
without touching business logic - see docs/design.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

BRAND_VOICE = {
    "tone": "practical, confident, no hype",
    "cta": "Read the full breakdown",
    "signature_tags": ["#buildinpublic", "#engineering"],
}


@dataclass(frozen=True)
class PlatformCaptionRules:
    name: str
    max_chars: int
    max_hashtags: int
    include_url: bool
    extra_tags: tuple[str, ...]
    emoji_prefix: str


PLATFORM_RULES: dict[str, PlatformCaptionRules] = {
    "instagram": PlatformCaptionRules(
        name="instagram",
        max_chars=2200,
        max_hashtags=8,
        include_url=False,  # IG captions do not render clickable links
        extra_tags=("#devlife", "#tech", "#startup"),
        emoji_prefix="",
    ),
    "x": PlatformCaptionRules(
        name="x",
        max_chars=280,
        max_hashtags=2,
        include_url=True,
        extra_tags=("#dev",),
        emoji_prefix="",
    ),
}

# Optional pluggable rewriter: fn(platform, draft_text) -> str
_ai_rewriter: Callable[[str, str], str] | None = None


def set_ai_rewriter(fn: Callable[[str, str], str] | None) -> None:
    """Install an optional AI post-processor. Default is None (pure templates)."""
    global _ai_rewriter
    _ai_rewriter = fn


def supported_platforms() -> list[str]:
    return sorted(PLATFORM_RULES)


def _first_sentences(body: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", body or "").strip()
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    # Prefer a sentence boundary, then a word boundary.
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > limit * 0.4:
            return cut[: idx + 1].strip()
    idx = cut.rfind(" ")
    return (cut[:idx] if idx > 0 else cut).rstrip() + "..."


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def build_caption(platform: str, title: str, body: str, url: str) -> str:
    rules = PLATFORM_RULES.get(platform)
    if rules is None:
        raise ValueError(f"unsupported platform: {platform}")

    tags = (BRAND_VOICE["signature_tags"] + list(rules.extra_tags))[
        : rules.max_hashtags
    ]
    tag_line = " ".join(tags)

    # Budget the body summary so the assembled caption fits the platform limit.
    fixed = len(title) + len(tag_line) + 8
    if rules.include_url:
        fixed += len(url) + 2
    budget = max(rules.max_chars - fixed, 40)

    summary = _first_sentences(body, budget)

    parts = [f"{rules.emoji_prefix}{title}".strip(), summary]
    if rules.include_url:
        parts.append(f"{BRAND_VOICE['cta']}: {url}")
    else:
        parts.append(f"{BRAND_VOICE['cta']} — link in bio.")
    parts.append(tag_line)

    caption = "\n\n".join(p for p in parts if p)

    if _ai_rewriter is not None:
        caption = _ai_rewriter(platform, caption)

    return _truncate(caption, rules.max_chars)
