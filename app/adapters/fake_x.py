"""X / Twitter adapter (talks to the mock platform)."""
from __future__ import annotations

from app.adapters.base import HttpMockPublisher


class FakeXPublisher(HttpMockPublisher):
    platform = "x"
    image_spec = (1600, 900)
