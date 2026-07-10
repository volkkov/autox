"""Template matching over screenshots — u2's ``d.image``, gated behind opencv.

Optional: ``pip install 'autox[image]'``. The pure :func:`locate` is the whole
algorithm (PIL in, match out); :class:`ImageX` binds it to a device screenshot.
Kept out of the base install so autox stays light for callers that ground on the
tree (the usual path) rather than pixels.
"""


def _require_cv2():
    try:
        import cv2
        import numpy as np
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise RuntimeError("image matching needs opencv — pip install 'autox[image]'") from e
    return cv2, np


def locate(haystack, needle, threshold: float = 0.8):
    """Find ``needle`` (PIL) inside ``haystack`` (PIL) by grayscale template
    match. Returns ``(cx, cy, confidence)`` of the best match at or above
    ``threshold``, else ``None``."""
    cv2, np = _require_cv2()
    hay = cv2.cvtColor(np.array(haystack.convert("RGB")), cv2.COLOR_RGB2GRAY)
    ndl = cv2.cvtColor(np.array(needle.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if ndl.shape[0] > hay.shape[0] or ndl.shape[1] > hay.shape[1]:
        return None
    result = cv2.matchTemplate(hay, ndl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    h, w = ndl.shape
    return (max_loc[0] + w // 2, max_loc[1] + h // 2, float(max_val))


class ImageX:
    """u2-parity ``d.image``: locate/tap a template on the current screen."""

    def __init__(self, device):
        self._device = device

    def _load(self, template):
        if isinstance(template, str):
            from PIL import Image

            return Image.open(template)
        return template  # already a PIL Image

    def match(self, template, threshold: float = 0.8):
        """``(cx, cy, confidence)`` of ``template`` on screen, or ``None``.
        ``template`` is an image path or a PIL Image."""
        return locate(self._device.screenshot(), self._load(template), threshold)

    def exists(self, template, threshold: float = 0.8) -> bool:
        return self.match(template, threshold) is not None

    def click(self, template, threshold: float = 0.8) -> bool:
        """Tap the center of ``template`` if found. Returns whether it was found."""
        found = self.match(template, threshold)
        if found is None:
            return False
        self._device.click(found[0], found[1])
        return True

    def wait(self, template, timeout: float = 10.0, threshold: float = 0.8):
        """Poll up to ``timeout`` for ``template`` to appear; return the match
        or ``None``."""
        import time

        deadline = time.monotonic() + timeout
        while True:
            found = self.match(template, threshold)
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)
