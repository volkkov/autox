"""Live-device capability check: prove the hierarchy dump and every control
work on the attached phone.

Non-destructive by design — it reads state, locks orientation, taps an inert
status-bar pixel, scrolls and scrolls back, and returns home. Nothing it does
navigates away from or mutates real app content. Run it standalone or on a
schedule:

    python -m autox.selfcheck --serial R9RL1063C2T

Exit code 0 iff every check passed.
"""

import argparse
import sys
import time
import xml.etree.ElementTree as ET

import autox
from autox.selector import match_nodes


class _Check:
    """Accumulates named pass/fail results with timing and detail."""

    def __init__(self):
        self.results: list[tuple[str, bool, str, float]] = []

    def run(self, name: str, fn) -> object:
        t0 = time.monotonic()
        try:
            detail = fn()
            self.results.append((name, True, str(detail if detail is not None else "ok"), time.monotonic() - t0))
            return detail
        except Exception as e:  # noqa: BLE001 — a failed check is a recorded result, not a crash
            self.results.append((name, False, f"{type(e).__name__}: {e}", time.monotonic() - t0))
            return None

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _, _ in self.results)


def run(serial: str | None = None) -> _Check:
    """Run the full check suite against ``serial`` and return the results."""
    c = _Check()
    c.run("connect", lambda: (autox.connect(serial), "attached")[1])
    dev = autox.connect(serial)  # a fresh handle for the rest (connect is cheap)

    def check_info():
        info = dev.info
        assert info["sdkInt"] > 0, "sdkInt unreadable"
        assert info["displayWidth"] > 0 and info["displayHeight"] > 0, "bad window size"
        return f"sdk={info['sdkInt']} size={info['displayWidth']}x{info['displayHeight']} rot={info['displayRotation']}"

    c.run("info", check_info)

    def check_dump():
        t0 = time.monotonic()
        xml = dev.dump_hierarchy()
        dt = time.monotonic() - t0
        assert xml.lstrip().startswith(("<?xml", "<hierarchy")), "not an XML hierarchy"
        n = len(list(ET.fromstring(xml).iter("node")))
        assert n > 0, "empty hierarchy"
        return f"{n} nodes in {dt:.2f}s"

    c.run("dump_hierarchy", check_dump)

    def check_selectors():
        # Resolve a selector against the live screen with no tap: pick a text
        # actually present, then prove d(text=…) finds it and yields a center.
        xml = dev.dump_hierarchy()
        labelled = [
            n.attrib["text"]
            for n in ET.fromstring(xml).iter("node")
            if n.attrib.get("text") and n.attrib.get("bounds", "").startswith("[")
        ]
        if not labelled:
            return "no labelled elements on screen (skipped)"
        text = labelled[0]
        assert match_nodes(xml, {"text": text}), "match_nodes found nothing"
        sel = dev(text=text)
        assert sel.exists, "selector.exists False for present text"
        assert sel.center() is not None, "selector.center() None for present text"
        return f"resolved {text!r} @ {sel.center()}"

    c.run("selector_resolution", check_selectors)

    def check_elements():
        els = dev.dump_elements()
        assert isinstance(els, list), "dump_elements did not return a list"
        actionable = sum(1 for e in els if e.get("action") in ("tap", "type"))
        return f"{len(els)} elements ({actionable} actionable)"

    c.run("dump_elements", check_elements)

    def check_screenshot():
        img = dev.screenshot()
        assert img.size[0] > 0 and img.size[1] > 0, "empty screenshot"
        return f"{img.size[0]}x{img.size[1]} {img.mode}"

    c.run("screenshot", check_screenshot)

    def check_orientation():
        dev.set_orientation("natural")
        dev.freeze_rotation()
        return f"rotation={dev.info['displayRotation']}"

    c.run("orientation_lock", check_orientation)

    # ── controls (benign, reversible) ────────────────────────────────────────

    def check_key():
        dev.press("home")
        time.sleep(0.5)
        return f"foreground={dev.info['currentPackageName']}"

    c.run("key_press_home", check_key)

    def check_tap():
        # Inert: a single tap on the status-bar top pixel opens nothing (the
        # shade needs a swipe), so this exercises `input tap` without effect.
        w, _ = dev.window_size()
        dev.click(w // 2, 1)
        return f"tapped ({w // 2}, 1)"

    c.run("tap", check_tap)

    def check_swipe():
        dev.swipe_ext("down")
        time.sleep(0.4)
        dev.swipe_ext("up")  # scroll back to where we started
        return "scrolled down+up"

    c.run("swipe", check_swipe)

    def check_notification():
        dev.open_notification()
        time.sleep(0.6)
        dev.press("home")  # closes the shade
        return "opened + dismissed shade"

    c.run("open_notification", check_notification)

    c.run("screen_on", lambda: (dev.screen_on(), "awake")[1])

    return c


def _format(c: _Check) -> str:
    width = max(len(name) for name, *_ in c.results)
    lines = []
    for name, passed, detail, dt in c.results:
        mark = "PASS" if passed else "FAIL"
        lines.append(f"  [{mark}] {name.ljust(width)}  {dt:5.2f}s  {detail}")
    verdict = "ALL CONTROLS OK" if c.ok else "FAILURES PRESENT"
    return "\n".join(lines) + f"\n  => {verdict} ({sum(p for _, p, _, _ in c.results)}/{len(c.results)} passed)"


def main() -> int:
    ap = argparse.ArgumentParser(description="autox live-device self-check")
    ap.add_argument("--serial", default=None, help="device serial (default: the only attached device)")
    args = ap.parse_args()
    c = run(args.serial)
    print(_format(c))
    return 0 if c.ok else 1


if __name__ == "__main__":
    sys.exit(main())
