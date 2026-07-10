"""Live-device capability check: prove the controls and (when the RPC server is
installed) the UI tree work on the attached phone.

Non-destructive by design — it reads state, locks orientation, taps an inert
status-bar pixel, scrolls and scrolls back, and returns home. Nothing it does
navigates away from or mutates real app content.

Controls run over adb and need nothing on the device, so they always run. The
tree checks (dump / selectors / element list) need the device-side
AccessibilityService RPC server (``server/``); when it isn't installed+enabled
they are reported SKIP with the reason, and the ``tree_source`` check fails so
the overall exit code flags that the tree isn't up yet.

    python -m autox.selfcheck --serial R9RL1063C2T

Exit code 0 iff every check passed (no failures; skips are allowed).
"""

import argparse
import sys
import time
import xml.etree.ElementTree as ET

import autox
from autox.selector import match_nodes


class _Check:
    """Accumulates named PASS/FAIL/SKIP results with timing and detail."""

    def __init__(self):
        self.results: list[tuple[str, str, str, float]] = []

    def run(self, name: str, fn) -> object:
        t0 = time.monotonic()
        try:
            detail = fn()
            self.results.append((name, "PASS", str(detail if detail is not None else "ok"), time.monotonic() - t0))
            return detail
        except Exception as e:  # noqa: BLE001 — a failed check is a recorded result, not a crash
            self.results.append((name, "FAIL", f"{type(e).__name__}: {e}", time.monotonic() - t0))
            return None

    def record(self, name: str, ok: bool, detail: str) -> None:
        self.results.append((name, "PASS" if ok else "FAIL", detail, 0.0))

    def skip(self, name: str, reason: str) -> None:
        self.results.append((name, "SKIP", reason, 0.0))

    @property
    def ok(self) -> bool:
        return all(status != "FAIL" for _, status, _, _ in self.results)


def run(serial: str | None = None) -> _Check:
    """Run the full check suite against ``serial`` and return the results."""
    c = _Check()
    c.run("connect", lambda: (autox.connect(serial), "attached")[1])
    dev = autox.connect(serial)

    ping = getattr(dev.tree_source, "ping", None)
    tree_ready = ping() if callable(ping) else True  # brings the server up (enable + forward)
    c.record("tree_source", tree_ready, "ready" if tree_ready else dev.tree_source_status())

    # ── UI tree (needs the RPC server) ───────────────────────────────────────

    if tree_ready:

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
    else:
        for name in ("dump_hierarchy", "selector_resolution", "dump_elements"):
            c.skip(name, "RPC server not ready — build+install server/autox-server.apk")

    # ── controls (uiautomator-free, always run) ──────────────────────────────

    def check_info():
        info = dev.info
        assert info["sdkInt"] > 0, "sdkInt unreadable"
        assert info["displayWidth"] > 0 and info["displayHeight"] > 0, "bad window size"
        return f"sdk={info['sdkInt']} size={info['displayWidth']}x{info['displayHeight']} rot={info['displayRotation']}"

    c.run("info", check_info)
    c.run("screenshot", lambda: f"{dev.screenshot().size[0]}x{dev.screenshot().size[1]}")

    def check_orientation():
        dev.set_orientation("natural")
        dev.freeze_rotation()
        return f"rotation={dev.info['displayRotation']}"

    c.run("orientation_lock", check_orientation)

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
    for name, status, detail, dt in c.results:
        lines.append(f"  [{status}] {name.ljust(width)}  {dt:5.2f}s  {detail}")
    passed = sum(1 for _, s, _, _ in c.results if s == "PASS")
    skipped = sum(1 for _, s, _, _ in c.results if s == "SKIP")
    verdict = "ALL OK" if c.ok else "FAILURES PRESENT"
    tail = f"  => {verdict} ({passed} passed"
    if skipped:
        tail += f", {skipped} skipped"
    tail += f" of {len(c.results)})"
    return "\n".join(lines) + "\n" + tail


def main() -> int:
    ap = argparse.ArgumentParser(description="autox live-device self-check")
    ap.add_argument("--serial", default=None, help="device serial (default: the only attached device)")
    args = ap.parse_args()
    c = run(args.serial)
    print(_format(c))
    return 0 if c.ok else 1


if __name__ == "__main__":
    sys.exit(main())
