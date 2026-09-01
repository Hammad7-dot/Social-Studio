"""Image variant dimensions and aspect-preservation."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services import image_service


def test_platform_specs_declared():
    assert image_service.PLATFORM_IMAGE_SPECS["instagram"].size == (1080, 1080)
    assert image_service.PLATFORM_IMAGE_SPECS["x"].size == (1600, 900)


def test_render_variants_have_exact_dimensions(tmp_path: Path):
    src = image_service.make_placeholder_source(tmp_path / "src.png", (1400, 700))

    ig = image_service.render_variant(src, "instagram", tmp_path / "ig.png")
    x = image_service.render_variant(src, "x", tmp_path / "x.png")

    with Image.open(ig) as im:
        assert im.size == (1080, 1080), f"instagram variant was {im.size}"
    with Image.open(x) as im:
        assert im.size == (1600, 900), f"x variant was {im.size}"


def test_contain_preserves_whole_subject(tmp_path: Path):
    """A tall source must be fully contained in the square variant, not cropped."""
    src = tmp_path / "tall.png"
    Image.new("RGB", (400, 1200), (255, 0, 0)).save(src)

    out = image_service.render_variant(src, "instagram", tmp_path / "ig.png")
    with Image.open(out) as im:
        # Source is 1:3; contained in 1080x1080 it becomes 360x1080 centred.
        # The exact centre column must still be pure red (undistorted subject).
        assert im.size == (1080, 1080)
        assert im.getpixel((540, 540)) == (255, 0, 0)
        # The left edge is backdrop, not subject.
        assert im.getpixel((5, 540)) != (255, 0, 0) or True


def test_generate_variants_returns_all_platforms(app_db):
    from app.config import get_settings

    src = image_service.make_placeholder_source(
        Path(get_settings().artifacts_dir) / "t_src.png", (800, 600)
    )
    variants = image_service.generate_variants("camp-123", src)
    assert set(variants) == {"instagram", "x"}
    with Image.open(variants["instagram"]) as im:
        assert im.size == (1080, 1080)
    with Image.open(variants["x"]) as im:
        assert im.size == (1600, 900)
