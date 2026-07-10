"""Client-side selectors — the piece uiautomator2 loses on Android 16.

u2 resolves ``d(text=…)`` selectors inside its device-side server against the live
accessibility tree — the path that dies on Android 16 (openatx/uiautomator2#1138),
taking every ``click_by_text/id/description`` with it. autox resolves the same
selectors here, in the client, against the hierarchy XML the RPC tree source
returns.

:func:`match_nodes` is pure (XML in, matches out) and carries the matching
semantics. :class:`UiObject` is the u2-parity element handle — reads, actions,
waits, scrolling, and relative navigation — over whatever ``_find()`` resolves.
:class:`Selector` is the concrete ``d(**kwargs)`` handle.
"""

import re
import time
import xml.etree.ElementTree as ET

from autox.dump import center_of, is_tappable_area, parse_bounds
from autox.exceptions import UiObjectNotFoundError

# u2 selector kwarg -> (dump XML attribute, match mode).
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
    "packageName": ("package", "exact"),
}
# Boolean state predicates -> dump attribute.
_BOOL_TABLE = {
    "clickable": "clickable",
    "checkable": "checkable",
    "checked": "checked",
    "enabled": "enabled",
    "focusable": "focusable",
    "focused": "focused",
    "scrollable": "scrollable",
    "selected": "selected",
    "longClickable": "long-clickable",
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
    Raises ValueError on an unsupported kwarg so a typo fails loudly."""
    instance = kwargs.pop("instance", 0)
    preds = []
    for key, value in kwargs.items():
        if key in _KWARG_TABLE:
            attr, mode = _KWARG_TABLE[key]
            preds.append((attr, mode, str(value)))
        elif key in _BOOL_TABLE:
            preds.append((_BOOL_TABLE[key], "exact", "true" if value else "false"))
        else:
            supported = ", ".join(sorted(list(_KWARG_TABLE) + list(_BOOL_TABLE)))
            raise ValueError(f"unsupported selector kwarg: {key!r} (supported: {supported})")
    return preds, instance


def _node_matches(node, preds) -> bool:
    return all(_matches(mode, node.attrib.get(attr, ""), wanted) for attr, mode, wanted in preds)


def _visible(bounds, screen) -> bool:
    if bounds is None or not is_tappable_area(bounds):
        return False
    sw, sh = screen if screen else (None, None)
    if sw and sh:
        x1, y1, x2, y2 = bounds
        if x2 <= 0 or y2 <= 0 or x1 >= sw or y1 >= sh:
            return False
    return True


def match_nodes(xml: str | None, kwargs: dict, screen: tuple[int, int] | None = None) -> list[MatchedNode]:
    """Every node in ``xml`` satisfying all of ``kwargs``, in document order.

    Zero-area nodes are dropped (untappable). With ``screen`` = (w, h), fully
    off-screen nodes are dropped too, so a selector resolves to the same visible
    elements the agent saw. ``instance`` is not applied here — the caller indexes
    the returned list.
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
        if not _node_matches(node, preds):
            continue
        bounds = parse_bounds(node.attrib.get("bounds", ""))
        if _visible(bounds, screen):
            out.append(MatchedNode(dict(node.attrib), bounds))
    return out


def _parents_map(root):
    """child element -> parent element (ElementTree has no parent pointers)."""
    return {child: parent for parent in root.iter() for child in parent}


def _elem_by_identity(root, node: MatchedNode):
    """The ET element matching a resolved :class:`MatchedNode`, keyed on bounds
    plus the identifying attributes — so relative navigation can re-find the base
    element in a fresh tree regardless of how the base was resolved."""
    for el in root.iter("node"):
        if (
            parse_bounds(el.attrib.get("bounds", "")) == node.bounds
            and el.attrib.get("resource-id", "") == node.attrib.get("resource-id", "")
            and el.attrib.get("text", "") == node.attrib.get("text", "")
            and el.attrib.get("content-desc", "") == node.attrib.get("content-desc", "")
        ):
            return el
    return None


class UiObject:
    """u2-parity element handle. Subclasses supply :meth:`_find`; everything
    else — reads, actions, waits, scroll, relative navigation — is shared."""

    def __init__(self, device, instance: int = 0):
        self._device = device
        self._instance = instance
        self._screen: tuple[int, int] | None = None

    # ── resolution (subclass hook) ───────────────────────────────────────────

    def _find(self) -> list[MatchedNode]:
        raise NotImplementedError

    def _screen_size(self) -> tuple[int, int] | None:
        if self._screen is None:
            try:
                self._screen = self._device.window_size()
            except Exception:  # noqa: BLE001
                self._screen = (0, 0)
        return self._screen

    def _nth(self) -> MatchedNode | None:
        matches = self._find()
        return matches[self._instance] if len(matches) > self._instance else None

    def _require(self) -> MatchedNode:
        node = self._nth()
        if node is None:
            raise UiObjectNotFoundError(f"no element for {self!r}")
        return node

    # ── presence / enumeration ───────────────────────────────────────────────

    @property
    def exists(self) -> bool:
        return self._nth() is not None

    def count(self) -> int:
        return len(self._find())

    def __len__(self) -> int:
        return self.count()

    # ── reads ────────────────────────────────────────────────────────────────

    def center(self) -> tuple[int, int] | None:
        node = self._nth()
        return node.center if node else None

    def bounds(self) -> tuple[int, int, int, int] | None:
        node = self._nth()
        return node.bounds if node else None

    def get_text(self) -> str:
        node = self._require()
        return node.attrib.get("text", "") or node.attrib.get("content-desc", "")

    @property
    def info(self) -> dict:
        node = self._require()
        a = node.attrib
        x1, y1, x2, y2 = node.bounds
        return {
            "text": a.get("text", ""),
            "resourceName": a.get("resource-id") or None,
            "className": a.get("class") or None,
            "packageName": a.get("package") or None,
            "contentDescription": a.get("content-desc") or None,
            "bounds": {"left": x1, "top": y1, "right": x2, "bottom": y2},
            "visibleBounds": {"left": x1, "top": y1, "right": x2, "bottom": y2},
            "clickable": a.get("clickable") == "true",
            "checkable": a.get("checkable") == "true",
            "checked": a.get("checked") == "true",
            "enabled": a.get("enabled") == "true",
            "focusable": a.get("focusable") == "true",
            "focused": a.get("focused") == "true",
            "scrollable": a.get("scrollable") == "true",
            "selected": a.get("selected") == "true",
            "longClickable": a.get("long-clickable") == "true",
        }

    # ── actions ──────────────────────────────────────────────────────────────

    def click(self, timeout: float = 0.0) -> None:
        """Tap the element, waiting up to ``timeout`` for it. Raises
        :class:`UiObjectNotFoundError` if it never appears (u2 semantics)."""
        if not self.click_exists(timeout=timeout):
            raise UiObjectNotFoundError(f"no element to click for {self!r}")

    def click_exists(self, timeout: float = 0.0) -> bool:
        """Wait up to ``timeout`` for the element, tap its center, return True;
        return False (a no-op) if it never appears."""
        deadline = time.monotonic() + timeout
        while True:
            node = self._nth()
            if node is not None:
                self._device.click(*node.center)
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def click_gone(self, timeout: float = 10.0) -> bool:
        """Click repeatedly until the element is gone. Returns whether it went."""
        deadline = time.monotonic() + timeout
        while True:
            if not self.click_exists(timeout=0):
                return True
            if time.monotonic() >= deadline:
                return not self.exists
            time.sleep(0.5)

    def long_click(self, duration: float = 0.5) -> None:
        node = self._require()
        self._device.long_click(*node.center, duration=duration)

    def drag_to(self, x, y, duration: float = 0.5) -> None:
        node = self._require()
        self._device.drag(*node.center, x, y, duration=duration)

    def swipe(self, direction: str, scale: float = 0.6, duration: float = 0.2) -> None:
        """Swipe within the element's bounds in ``direction`` (up/down/left/right)."""
        x1, y1, x2, y2 = self._require().bounds
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        dx, dy = int((x2 - x1) * scale / 2), int((y2 - y1) * scale / 2)
        vec = {"up": (0, dy, 0, -dy), "down": (0, -dy, 0, dy), "left": (dx, 0, -dx, 0), "right": (-dx, 0, dx, 0)}
        if direction not in vec:
            raise ValueError(f"unknown direction: {direction!r}")
        sxo, syo, exo, eyo = vec[direction]
        self._device.swipe(cx + sxo, cy + syo, cx + exo, cy + eyo, duration=duration)

    def scroll(self, direction: str = "down", steps: int = 10) -> None:
        """Scroll the element in ``direction`` (slower, drag-like)."""
        self.swipe(direction, scale=0.8, duration=max(steps * 0.03, 0.2))

    def fling(self, direction: str = "down") -> None:
        """Fling the element in ``direction`` (fast)."""
        self.swipe(direction, scale=0.9, duration=0.05)

    def set_text(self, text: str) -> None:
        """Focus the field, clear it, then type ``text`` (ASCII; Unicode needs an
        IME — see the coverage matrix)."""
        node = self._require()
        self._device.click(*node.center)
        self._device.clear_text(count=max(len(node.attrib.get("text", "")) + 2, 4))
        self._device._type_text(text)

    def clear_text(self) -> None:
        node = self._require()
        self._device.click(*node.center)
        self._device.clear_text(count=max(len(node.attrib.get("text", "")) + 2, 4))

    def send_keys(self, text: str, clear: bool = False) -> None:
        node = self._require()
        self._device.click(*node.center)
        if clear:
            self._device.clear_text(count=max(len(node.attrib.get("text", "")) + 2, 4))
        self._device._type_text(text)

    def screenshot(self):
        """PIL screenshot cropped to the element's bounds."""
        x1, y1, x2, y2 = self._require().bounds
        return self._device.screenshot().crop((x1, y1, x2, y2))

    # ── waits ────────────────────────────────────────────────────────────────

    def wait(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self.exists:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def wait_gone(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if not self.exists:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def must_wait(self, timeout: float = 10.0) -> None:
        if not self.wait(timeout=timeout):
            raise UiObjectNotFoundError(f"element never appeared: {self!r}")

    # ── relative navigation ──────────────────────────────────────────────────

    def child(self, **kwargs):
        return _RelativeUiObject(self, "child", kwargs)

    def child_by_text(self, text: str, **kwargs):
        return _RelativeUiObject(self, "child", {"text": text, **kwargs})

    def child_by_description(self, description: str, **kwargs):
        return _RelativeUiObject(self, "child", {"description": description, **kwargs})

    def sibling(self, **kwargs):
        return _RelativeUiObject(self, "sibling", kwargs)

    def parent(self, **kwargs):
        return _RelativeUiObject(self, "parent", kwargs)

    def child_by_instance(self, index: int):
        return _RelativeUiObject(self, "child", {"instance": index})

    def left(self, **kwargs):
        return _RelativeUiObject(self, "left", kwargs)

    def right(self, **kwargs):
        return _RelativeUiObject(self, "right", kwargs)

    def up(self, **kwargs):
        return _RelativeUiObject(self, "up", kwargs)

    def down(self, **kwargs):
        return _RelativeUiObject(self, "down", kwargs)


class Selector(UiObject):
    """A bound ``d(text="OK", instance=0)`` selector."""

    def __init__(self, device, kwargs: dict):
        _, instance = _predicates(dict(kwargs))  # validate + extract instance
        super().__init__(device, instance)
        self._kwargs = kwargs

    def __repr__(self) -> str:
        return f"Selector({self._kwargs})"

    def _find(self) -> list[MatchedNode]:
        return match_nodes(self._device.dump_hierarchy_or_none(), self._kwargs, self._screen_size())

    def __getitem__(self, index: int) -> "Selector":
        return Selector(self._device, {**{k: v for k, v in self._kwargs.items() if k != "instance"}, "instance": index})

    def __iter__(self):
        for i in range(self.count()):
            yield self[i]


class _RelativeUiObject(UiObject):
    """An element resolved relative to a base — child/sibling/directional."""

    def __init__(self, base: UiObject, relation: str, kwargs: dict):
        _, instance = _predicates(dict(kwargs))
        super().__init__(base._device, instance)
        self._base = base
        self._relation = relation
        self._kwargs = kwargs

    def __repr__(self) -> str:
        return f"{self._base!r}.{self._relation}({self._kwargs})"

    def _find(self) -> list[MatchedNode]:
        # Resolve the base to a node first (works for any base — Selector,
        # xpath, or another relative), then locate it in the tree by identity.
        base_node = self._base._nth()
        if base_node is None:
            return []
        xml = self._device.dump_hierarchy_or_none()
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []
        screen = self._screen_size()
        base_elem = _elem_by_identity(root, base_node)
        if base_elem is None:
            return []

        preds, _ = _predicates(dict(self._kwargs))
        candidates = self._related(base_elem, root, preds, screen)
        out = []
        for el in candidates:
            b = parse_bounds(el.attrib.get("bounds", ""))
            if _visible(b, screen):
                out.append(MatchedNode(dict(el.attrib), b))
        return out

    def _related(self, base_elem, root, preds, screen):
        if self._relation == "child":
            return [el for el in base_elem.iter("node") if el is not base_elem and _node_matches(el, preds)]
        if self._relation == "sibling":
            parent = _parents_map(root).get(base_elem)
            kids = list(parent) if parent is not None else []
            return [el for el in kids if el is not base_elem and _node_matches(el, preds)]
        if self._relation == "parent":
            parent = _parents_map(root).get(base_elem)
            if parent is None or parent.tag != "node" or not _node_matches(parent, preds):
                return []
            return [parent]
        # directional: nearest matching node in that direction, with perpendicular overlap
        bx = parse_bounds(base_elem.attrib.get("bounds", ""))
        if bx is None:
            return []
        return self._directional(base_elem, root, preds, bx)

    def _directional(self, base_elem, root, preds, bx):
        bx1, by1, bx2, by2 = bx
        bcx, bcy = (bx1 + bx2) // 2, (by1 + by2) // 2
        scored = []
        for el in root.iter("node"):
            if el is base_elem or not _node_matches(el, preds):
                continue
            b = parse_bounds(el.attrib.get("bounds", ""))
            if b is None or not is_tappable_area(b):
                continue
            x1, y1, x2, y2 = b
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            v_overlap = min(by2, y2) > max(by1, y1)
            h_overlap = min(bx2, x2) > max(bx1, x1)
            if self._relation == "left" and cx < bcx and v_overlap:
                scored.append((bcx - cx, el))
            elif self._relation == "right" and cx > bcx and v_overlap:
                scored.append((cx - bcx, el))
            elif self._relation == "up" and cy < bcy and h_overlap:
                scored.append((bcy - cy, el))
            elif self._relation == "down" and cy > bcy and h_overlap:
                scored.append((cy - bcy, el))
        return [el for _, el in sorted(scored, key=lambda t: t[0])]
