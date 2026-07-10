"""XPath selectors over the hierarchy XML — ``d.xpath('//node[@text="OK"]')``.

Uses lxml (full XPath 1.0) when it is installed, else falls back to
ElementTree's XPath subset (attribute-predicate paths — the common case:
``//node[@resource-id="…"]``, ``//*[@text="…"]``, ``//android.widget.Button``).
Advanced XPath (``contains()``, functions, ``and``/``or``) needs lxml — install
``autox[xpath]``.

An :class:`XPathSelector` is a :class:`~autox.selector.UiObject`, so it inherits
click / get_text / set_text / wait / … unchanged; only resolution differs.
"""

import xml.etree.ElementTree as ET

from autox.dump import parse_bounds
from autox.exceptions import XPathElementNotFoundError
from autox.selector import MatchedNode, UiObject

try:
    from lxml import etree as _LET

    _HAVE_LXML = True
except ImportError:  # pragma: no cover - depends on optional dep
    _HAVE_LXML = False


def normalize_xpath(xpath: str) -> str:
    """Apply u2's shorthands: ``@id`` and bare ``pkg:id/name`` → resource-id;
    a bare word → text match; otherwise pass the XPath through."""
    x = xpath.strip()
    if x.startswith(("//", "/", "(", ".")):
        return x
    if x.startswith("@"):
        return f'//node[@resource-id="{x[1:]}"]'
    if ":id/" in x:
        return f'//node[@resource-id="{x}"]'
    return f'//*[@text="{x}"]'


def query(xml: str, xpath: str) -> list:
    """Return the elements matching ``xpath`` (lxml or ElementTree elements)."""
    expr = normalize_xpath(xpath)
    if _HAVE_LXML:
        root = _LET.fromstring(xml.encode("utf-8"))
        return list(root.xpath(expr))
    # ElementTree needs a relative path; //foo -> .//foo
    et_expr = "." + expr if expr.startswith("/") else expr
    try:
        root = ET.fromstring(xml)
        return list(root.findall(et_expr))
    except (ET.ParseError, SyntaxError):
        return []


class XPathSelector(UiObject):
    """A bound XPath query. Resolves against the live hierarchy on each call."""

    def __init__(self, device, xpath: str, instance: int = 0):
        super().__init__(device, instance)
        self._xpath = xpath

    def __repr__(self) -> str:
        return f"XPathSelector({self._xpath!r})"

    def _find(self) -> list[MatchedNode]:
        xml = self._device.dump_hierarchy_or_none()
        if not xml:
            return []
        out = []
        for el in query(xml, self._xpath):
            bounds = parse_bounds(el.get("bounds", ""))
            if bounds is not None:
                out.append(MatchedNode(dict(el.attrib), bounds))
        return out

    def all(self) -> list[MatchedNode]:
        """Every matching node (u2 parity)."""
        return self._find()

    def get(self, timeout: float = 10.0) -> "XPathSelector":
        """Wait for the element and return self, or raise (u2 parity)."""
        if not self.wait(timeout=timeout):
            raise XPathElementNotFoundError(f"no node for xpath {self._xpath!r}")
        return self
