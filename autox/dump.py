"""Pure helpers for the UI hierarchy XML — no device, no I/O, unit-testable.

The device-side dump lives in :mod:`autox.device`; everything here operates on
the raw string it returns.
"""

import re

_HIERARCHY_CLOSE = "</hierarchy>"
# Bounds look like "[x1,y1][x2,y2]"; capture the four signed integers.
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def trim_hierarchy_xml(raw: str) -> str | None:
    """Return just the ``<?xml…</hierarchy>`` document from a raw dump.

    The AOSP ``uiautomator dump`` binary appends a human-readable status line
    ("UI hierarchy dumped to: …") when it writes to stdout/``/dev/tty``, and a
    ``cat`` of the scratch file can carry a trailing newline. Slice the well-
    formed document out so :func:`xml.etree.ElementTree.fromstring` never chokes
    on trailing junk. ``None`` when no hierarchy is present (a failed dump)."""
    if not raw:
        return None
    start = raw.find("<?xml")
    if start < 0:
        start = raw.find("<hierarchy")
    end = raw.rfind(_HIERARCHY_CLOSE)
    if start < 0 or end < 0:
        return None
    return raw[start : end + len(_HIERARCHY_CLOSE)]


def parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    """``"[x1,y1][x2,y2]"`` → ``(x1, y1, x2, y2)``; ``None`` if unparseable."""
    m = _BOUNDS_RE.search(bounds or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def center_of(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    """Center pixel of a ``(x1, y1, x2, y2)`` box."""
    x1, y1, x2, y2 = bounds
    return (x1 + x2) // 2, (y1 + y2) // 2


def is_tappable_area(bounds: tuple[int, int, int, int]) -> bool:
    """Whether a box has positive area — zero-area nodes are invisible and
    untappable, so they are excluded from selector candidates."""
    x1, y1, x2, y2 = bounds
    return x2 > x1 and y2 > y1
