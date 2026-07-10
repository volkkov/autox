"""Compact, token-cheap element extraction — the agent-friendly observation.

A raw ``dump_hierarchy`` is tens of KB of XML; most of it is layout scaffolding
an agent never acts on. :func:`compact_elements` slims it to just the
interactive and labelled nodes as small dicts, so an LLM agent spends its tokens
on what it can tap or read, not on ``FrameLayout`` nesting.

Slimming rules (all token-motivated):
  * keep only clickable / editable / labelled nodes,
  * drop the ``<package>:id/`` prefix from ids (dead weight on every row),
  * fold clickable/editable/read into one ``action``,
  * omit empty ``id``/``text``,
  * drop zero-area, off-screen, and exact-duplicate nodes,
  * fold a clickable wrapper around a single text label into one element.

Pure and unit-testable; :meth:`autox.device.Device.dump_elements` binds it to a
live dump.
"""

import json
import xml.etree.ElementTree as ET

from autox.dump import center_of, parse_bounds

_EDITABLE_CLASS_HINTS = ("EditText", "AutoCompleteTextView")


def compact_elements(xml: str | None, screen: tuple[int, int] | None = None) -> list[dict]:
    """Slim ``xml`` to a list of actionable/labelled element dicts.

    ``screen`` = (width, height) enables off-screen culling. Each element is
    ``{id?, text?, type, action, center:[x,y]}`` — ``action`` is ``tap`` /
    ``type`` / ``read``. Returns ``[]`` when the XML is missing or unparseable.
    """
    if not xml:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    sw, sh = screen if screen else (None, None)
    elements: list[dict] = []
    seen: set = set()
    for node in root.iter("node"):
        attr = node.attrib
        class_name = attr.get("class", "")
        clickable = attr.get("clickable") == "true"
        editable = any(h in class_name for h in _EDITABLE_CLASS_HINTS) or attr.get("editable") == "true"
        label = attr.get("text", "") or attr.get("content-desc", "")
        if not clickable and not editable and not label:
            continue

        bounds = parse_bounds(attr.get("bounds", ""))
        if bounds is None:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:  # zero-area — invisible, untappable
            continue
        if sw and sh and (x2 <= 0 or y2 <= 0 or x1 >= sw or y1 >= sh):  # off-screen
            continue
        cx, cy = center_of(bounds)

        action = "type" if editable else ("tap" if clickable else "read")
        res_id = attr.get("resource-id", "")
        short_id = res_id.split("/", 1)[-1] if res_id else ""

        key = (short_id, label, action, cx, cy)
        if key in seen:
            continue
        seen.add(key)

        el: dict = {}
        if short_id:
            el["id"] = short_id
        if label:
            el["text"] = label
        el["type"] = class_name.rsplit(".", 1)[-1]
        el["action"] = action
        el["center"] = [cx, cy]
        el["_bounds"] = bounds  # dropped after the merge below
        elements.append(el)

    # Fold the Android clickable-wrapper-around-a-TextView pattern: a labelless
    # tap/type element that spatially contains exactly one read inherits that
    # read's text and the read is dropped. Ambiguous wrappers (zero or ≥2
    # contained reads) merge nothing; a tap/type element is never dropped.
    reads = [e for e in elements if e["action"] == "read"]
    dropped: set = set()
    for el in elements:
        if el["action"] not in ("tap", "type") or el.get("text"):
            continue
        ax1, ay1, ax2, ay2 = el["_bounds"]
        inside = [
            r
            for r in reads
            if ax1 <= r["_bounds"][0] and ay1 <= r["_bounds"][1] and r["_bounds"][2] <= ax2 and r["_bounds"][3] <= ay2
        ]
        if len(inside) == 1:
            el["text"] = inside[0]["text"]
            dropped.add(id(inside[0]))

    out = []
    for el in elements:
        if id(el) in dropped:
            continue
        del el["_bounds"]
        out.append(el)
    return out


def compact_elements_json(xml: str | None, screen: tuple[int, int] | None = None) -> str:
    """:func:`compact_elements` as a compact JSON string (UTF-8 preserved)."""
    return json.dumps(compact_elements(xml, screen), ensure_ascii=False, separators=(",", ":"))
