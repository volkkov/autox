"""Client-side selectors — the piece uiautomator2 loses on Android 16.

u2 resolves ``d(text=…)`` selectors inside its device-side server by walking the
live accessibility tree. That path is dead on Android 16 (the ``getServiceInfo()``
NPE, openatx/uiautomator2#1138), which takes every ``click_by_text/id/description``
down with it. autox resolves the same selectors here, in the client, against the
XML from :meth:`Device.dump_hierarchy` — so selector clicks work again with no
device-side server.

:func:`match_nodes` is pure (XML in, matches out) and carries the semantics;
:class:`Selector` binds it to a device for the dump-and-tap round trip.
"""

import re
import time
import xml.etree.ElementTree as ET

from autox.dump import center_of, is_tappable_area, parse_bounds

# u2 selector kwarg -> (dump XML attribute, match mode). Mirrors the subset of
# uiautomator2's UiSelector that macrox drives, plus the neighbouring string
# variants that share this one dispatch table.
_KWARG_TABLE = {
    "text": ("text", "exact"),
    "textContains": ("text", "contains"),
    "textMatches": ("text", "matches"),
    "textStartsWith": ("text", "startswith"),
    "description": ("content-desc", "exact"),
    "descriptionContains": ("content-desc", "contains"),
    "descriptionMatches": ("content-desc", "matches"),
    "descriptionStartsWith": ("content-desc", "startswith"),
    "resourceId": ("resource-id", "exact"),
    "resourceIdMatches": ("resource-id", "matches"),
    "className": ("class", "exact"),
    "classNameMatches": ("class", "matches"),
}


class MatchedNode:
    """A dump node that satisfied a selector, with its tappable center."""

    __slots__ = ("attrib", "bounds", "center")

    def __init__(self, attrib: dict, bounds: tuple[int, int, int, int]):
        self.attrib = attrib
        self.bounds = bounds
        self.center = center_of(bounds)

    def __repr__(self) -> str:
        label = self.attrib.get("text") or self.attrib.get("content-desc") or self.attrib.get("resource-id") or ""
        return f"MatchedNode({label!r} @ {self.center})"


def _matches(mode: str, actual: str, wanted: str) -> bool:
    if mode == "exact":
        return actual == wanted
    if mode == "contains":
        return wanted in actual
    if mode == "startswith":
        return actual.startswith(wanted)
    if mode == "matches":
        return re.fullmatch(wanted, actual) is not None
    raise ValueError(f"unknown match mode: {mode}")


def _predicates(kwargs: dict):
    """Split selector kwargs into (attribute predicates, instance index).
    Raises ValueError on an unsupported kwarg so a typo or an unimplemented
    selector fails loudly instead of silently matching everything."""
    instance = kwargs.pop("instance", 0)
    preds = []
    for key, value in kwargs.items():
        spec = _KWARG_TABLE.get(key)
        if spec is None:
            raise ValueError(f"unsupported selector kwarg: {key!r} (supported: {', '.join(sorted(_KWARG_TABLE))})")
        attr, mode = spec
        preds.append((attr, mode, str(value)))
    return preds, instance


def match_nodes(xml: str | None, kwargs: dict) -> list[MatchedNode]:
    """Every node in ``xml`` satisfying all of ``kwargs``, in document order.

    Zero-area nodes are dropped: they are invisible and untappable, and a
    selector that resolved to one would tap a garbage coordinate. ``instance``
    is not applied here — the caller indexes the returned list — so a selector's
    full match set stays inspectable.
    """
    if not xml:
        return []
    preds, _ = _predicates(dict(kwargs))
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out: list[MatchedNode] = []
    for node in root.iter("node"):
        if not all(_matches(mode, node.attrib.get(attr, ""), wanted) for attr, mode, wanted in preds):
            continue
        bounds = parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None or not is_tappable_area(bounds):
            continue
        out.append(MatchedNode(dict(node.attrib), bounds))
    return out


class Selector:
    """A bound selector: ``device(text="OK", instance=0)``.

    Kept deliberately small — the operations macrox drives (``click_exists``)
    plus the natural neighbours (``exists``, ``count``, ``click``). Each call
    fetches a fresh hierarchy; there is no cached tree to go stale.
    """

    def __init__(self, device, kwargs: dict):
        self._device = device
        self._kwargs = kwargs
        # Validate + extract instance now so a bad selector raises at
        # construction, not deep inside a click.
        _, self._instance = _predicates(dict(kwargs))

    def _find(self) -> list[MatchedNode]:
        return match_nodes(self._device.dump_hierarchy_or_none(), self._kwargs)

    @property
    def exists(self) -> bool:
        return len(self._find()) > self._instance

    def count(self) -> int:
        return len(self._find())

    def center(self) -> tuple[int, int] | None:
        """Center of the selected instance, or None when it is not present."""
        matches = self._find()
        return matches[self._instance].center if len(matches) > self._instance else None

    def click(self) -> bool:
        """Tap the selected instance. Returns whether an element was tapped."""
        return self.click_exists(timeout=0)

    def click_exists(self, timeout: float = 0.0) -> bool:
        """Wait up to ``timeout`` seconds for the element, tap its center, and
        return True; return False if it never appears.

        Mirrors u2's ``click_exists``: a no-op (returns False) when nothing
        matches, so a caller can tell a real tap from a miss. Each retry redumps
        the hierarchy (~2.5 s on Android 16), so a 5 s timeout is ~2 attempts —
        enough to catch an element that renders a beat late.
        """
        deadline = time.monotonic() + timeout
        while True:
            matches = self._find()
            if len(matches) > self._instance:
                cx, cy = matches[self._instance].center
                self._device.click(cx, cy)
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)
