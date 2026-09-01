"""Pillow-based image variant generation.

Strategy: *contain + pad* on a blurred/solid backdrop rather than a hard crop.
A naive center-crop of a 1600x900 hero into a 1080x1080 square would slice ~44%
off the sides and routinely decapitate the subject. Containing the whole source
inside the target and filling the remaining space with a backdrop derived from
the image keeps the full subject visible at every aspect ratio.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter

from app.config import get_settings


@dataclass(frozen=True)
class PlatformImageSpec:
    name: str
    width: int
    height: int
    fmt: str = "PNG"

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


PLATFORM_IMAGE_SPECS: dict[str, PlatformImageSpec] = {
    "instagram": PlatformImageSpec("instagram", 1080, 1080),
    "x": PlatformImageSpec("x", 1600, 900),
}


def make_placeholder_source(path: Path, size: tuple[int, int] = (1400, 1050)) -> Path:
    """Deterministic gradient placeholder used when no source image is supplied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        for x in range(0, w, 4):
            r = int(30 + 180 * (x / w))
            g = int(40 + 120 * (y / h))
            b = int(120 + 100 * (1 - x / w))
            for dx in range(4):
                if x + dx < w:
                    px[x + dx, y] = (r, g, b)
    img.save(path, "PNG")
    return path


def _backdrop(source: Image.Image, spec: PlatformImageSpec) -> Image.Image:
    """Cover-fill + blur the source to make a non-distracting backdrop."""
    src_ratio = source.width / source.height
    tgt_ratio = spec.width / spec.height
    if src_ratio > tgt_ratio:
        new_h = spec.height
        new_w = max(int(round(new_h * src_ratio)), spec.width)
    else:
        new_w = spec.width
        new_h = max(int(round(new_w / src_ratio)), spec.height)
    cover = source.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - spec.width) // 2
    top = (new_h - spec.height) // 2
    cover = cover.crop((left, top, left + spec.width, top + spec.height))
    return cover.filter(ImageFilter.GaussianBlur(radius=24))


def render_variant(
    source_path: str | Path, platform: str, out_path: str | Path
) -> Path:
    spec = PLATFORM_IMAGE_SPECS.get(platform)
    if spec is None:
        raise ValueError(f"unsupported platform: {platform}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source_path) as raw:
        source = raw.convert("RGB")

        canvas = _backdrop(source, spec)

        # Contain: scale so the ENTIRE source fits inside the target box.
        scale = min(spec.width / source.width, spec.height / source.height)
        fit_w = max(int(round(source.width * scale)), 1)
        fit_h = max(int(round(source.height * scale)), 1)
        fitted = source.resize((fit_w, fit_h), Image.LANCZOS)

        canvas.paste(fitted, ((spec.width - fit_w) // 2, (spec.height - fit_h) // 2))
        canvas.save(out_path, spec.fmt)

    return out_path


def generate_variants(
    campaign_id: str, source_path: str | Path, platforms: list[str] | None = None
) -> dict[str, str]:
    """Render one variant per platform; returns {platform: absolute_path}."""
    settings = get_settings()
    platforms = platforms or sorted(PLATFORM_IMAGE_SPECS)
    out: dict[str, str] = {}
    for platform in platforms:
        target = (
            Path(settings.artifacts_dir) / platform / f"{campaign_id}_{platform}.png"
        )
        out[platform] = str(render_variant(source_path, platform, target).resolve())
    return out
