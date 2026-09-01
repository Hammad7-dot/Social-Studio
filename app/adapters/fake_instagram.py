"""Instagram adapter (talks to the mock platform)."""
from __future__ import annotations

from app.adapters.base import HttpMockPublisher


class FakeInstagramPublisher(HttpMockPublisher):
    platform = "instagram"
    image_spec = (1080, 1080)
