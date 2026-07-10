import pytest

pytest.importorskip("cv2")
pytest.importorskip("numpy")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from autox.image import ImageX, locate  # noqa: E402


def _needle():
    # Structured (two-tone) so template matching has variance to lock onto.
    a = np.zeros((30, 30, 3), np.uint8)
    a[:15] = (255, 0, 0)
    a[15:] = (0, 0, 255)
    return Image.fromarray(a)


def test_locate_finds_embedded_needle():
    needle = _needle()
    hay = Image.new("RGB", (200, 200), (0, 0, 0))
    hay.paste(needle, (70, 50))
    m = locate(hay, needle, threshold=0.9)
    assert m is not None
    cx, cy, conf = m
    assert abs(cx - 85) <= 2 and abs(cy - 65) <= 2  # center of the 30x30 at (70,50)
    assert conf > 0.9


def test_locate_absent_returns_none():
    hay = Image.new("RGB", (100, 100), (0, 0, 0))
    assert locate(hay, _needle(), threshold=0.9) is None


def test_locate_needle_larger_than_haystack():
    assert locate(Image.new("RGB", (10, 10)), _needle()) is None


class _FakeDevice:
    def __init__(self, screen):
        self._screen = screen
        self.taps = []

    def screenshot(self):
        return self._screen

    def click(self, x, y):
        self.taps.append((x, y))


def test_imagex_click_taps_match_center():
    needle = _needle()
    hay = Image.new("RGB", (200, 200), (0, 0, 0))
    hay.paste(needle, (70, 50))
    dev = _FakeDevice(hay)
    assert ImageX(dev).click(needle, threshold=0.9) is True
    assert dev.taps == [(85, 65)]


def test_imagex_click_absent_returns_false():
    dev = _FakeDevice(Image.new("RGB", (200, 200), (0, 0, 0)))
    assert ImageX(dev).click(_needle(), threshold=0.9) is False
    assert dev.taps == []
