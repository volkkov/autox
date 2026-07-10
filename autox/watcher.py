"""Watchers — background rules that fire when a pop-up appears.

u2 parity: register condition→action rules, then either poll them with
:meth:`Watcher.run` or run a background thread with :meth:`Watcher.start`. A rule
fires when every one of its conditions is present in one hierarchy snapshot; the
default action taps the last condition's element.

Client-side and stateless per check — each :meth:`run` fetches one fresh
hierarchy and evaluates all rules against it.
"""

import threading
import time

from autox.selector import match_nodes


class _Rule:
    """Builder for one watcher rule: ``.when(...).when(...).click()``."""

    def __init__(self, watcher: "Watcher", conditions: list[dict]):
        self._watcher = watcher
        self._conditions = conditions

    def when(self, **kwargs) -> "_Rule":
        self._conditions.append(kwargs)
        return self

    def click(self) -> None:
        """Tap the element matched by the last condition when all conditions hold."""
        self._watcher._register(self._conditions, lambda d, matched: d.click(*matched[-1].center))

    def press(self, key: str) -> None:
        self._watcher._register(self._conditions, lambda d, matched: d.press(key))

    def call(self, func) -> None:
        """Call ``func(device)`` when all conditions hold."""
        self._watcher._register(self._conditions, lambda d, matched: func(d))


class Watcher:
    """A set of condition→action rules over the hierarchy."""

    def __init__(self, device):
        self._device = device
        self._rules: list[tuple[list[dict], object]] = []
        self._thread: threading.Thread | None = None
        self._running = False

    def when(self, **kwargs) -> _Rule:
        return _Rule(self, [kwargs])

    def _register(self, conditions: list[dict], action) -> None:
        self._rules.append((conditions, action))

    def run(self) -> bool:
        """Evaluate every rule against one fresh hierarchy. Returns whether any fired."""
        xml = self._device.dump_hierarchy_or_none()
        if not xml:
            return False
        try:
            screen = self._device.window_size()
        except Exception:  # noqa: BLE001
            screen = None
        fired = False
        for conditions, action in self._rules:
            matched = []
            for cond in conditions:
                nodes = match_nodes(xml, cond, screen)
                if not nodes:
                    break
                matched.append(nodes[0])
            else:
                action(self._device, matched)
                fired = True
        return fired

    def start(self, interval: float = 2.0) -> None:
        """Poll the rules on a background daemon thread."""
        if self._running:
            return
        self._running = True

        def loop():
            while self._running:
                try:
                    self.run()
                except Exception:  # noqa: BLE001 — a watcher must never crash the app
                    pass
                time.sleep(interval)

        self._thread = threading.Thread(target=loop, name="autox-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def reset(self) -> None:
        self._rules = []

    @property
    def running(self) -> bool:
        return self._running


class WatchContext:
    """``with d.watch_context() as ctx: ctx.when(text="Allow").click()`` — a
    scoped watcher that polls while inside the block."""

    def __init__(self, device, builtin: bool = False):
        self._watcher = Watcher(device)
        if builtin:
            # Common permission/interstitial dismissals.
            self._watcher.when(text="Allow").click()
            self._watcher.when(text="OK").click()

    def when(self, **kwargs) -> _Rule:
        return self._watcher.when(**kwargs)

    def wait_stable(self, timeout: float = 5.0, settle: float = 1.0) -> bool:
        """Run rules until nothing fires for ``settle`` seconds. Returns whether
        it settled within ``timeout``."""
        deadline = time.monotonic() + timeout
        last_fire = time.monotonic()
        while time.monotonic() < deadline:
            if self._watcher.run():
                last_fire = time.monotonic()
            elif time.monotonic() - last_fire >= settle:
                return True
            time.sleep(0.5)
        return False

    def __enter__(self) -> "WatchContext":
        self._watcher.start()
        return self

    def __exit__(self, *exc) -> None:
        self._watcher.stop()
