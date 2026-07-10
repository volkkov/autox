"""The device driver — a uiautomator2-compatible surface with no device-side
server.

Everything runs from the client over adb: the hierarchy comes from the AOSP
``uiautomator dump`` binary (which keeps working on Android 16, unlike u2's
jsonrpc server), selectors resolve in :mod:`autox.selector`, and actions go
through ``input`` / ``cmd`` / ``settings``. There is nothing to install on the
device and nothing to keep alive, so bring-up is instant and there is no
accessibility server to lose mid-session.

The method set mirrors the slice of u2 that macrox calls, so macrox can switch
``import uiautomator2 as u2`` to ``import autox as u2`` unchanged.
"""

import re
import time

import adbutils

from autox.dump import trim_hierarchy_xml
from autox.elements import compact_elements
from autox.exceptions import DeviceError, HierarchyDumpError
from autox.selector import Selector

# Scratch file the shell dump writes to, then we cat back.
_DUMP_PATH = "/sdcard/autox_hierarchy.xml"
# `uiautomator dump` spins up its own instrumentation each call (~2.5 s on
# Android 16); give the shell room but still bound it.
_DUMP_TIMEOUT = 20.0

# u2 press() name -> Android keycode. Covers the names macrox's _safe_press
# forwards plus the common d-pad/volume set.
_KEYCODES = {
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "menu": "KEYCODE_MENU",
    "enter": "KEYCODE_ENTER",
    "delete": "KEYCODE_DEL",
    "del": "KEYCODE_DEL",
    "search": "KEYCODE_SEARCH",
    "power": "KEYCODE_POWER",
    "recent": "KEYCODE_APP_SWITCH",
    "center": "KEYCODE_DPAD_CENTER",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "volume_mute": "KEYCODE_VOLUME_MUTE",
    "camera": "KEYCODE_CAMERA",
}

# set_orientation() name -> user_rotation value.
_ORIENTATIONS = {"natural": 0, "n": 0, "left": 1, "l": 1, "upsidedown": 2, "u": 2, "right": 3, "r": 3}

# swipe_ext finger direction -> (sx, sy, ex, ey) offsets in units of (dx, dy)
# around screen center, where dx = scale·w/2 and dy = scale·h/2. Names the
# FINGER's travel (u2's convention); macrox inverts content→finger before
# calling, and its own shell fallback uses this exact geometry.
_SWIPE_OFFSETS = {
    "up": (0, 1, 0, -1),
    "down": (0, -1, 0, 1),
    "left": (1, 0, -1, 0),
    "right": (-1, 0, 1, 0),
}


class Toast:
    """Toast reader stub — parity with ``u2.toast``.

    Reading toasts needs the accessibility event stream, which requires a
    device-side service autox deliberately does without. ``get_message`` always
    returns the default; macrox already treats a missing toast as "No toast
    message"."""

    def get_message(self, wait_timeout: float = 10.0, cache_timeout: float = 10.0, default=None):
        return default


class Device:
    """A single Android device, driven entirely over adb."""

    def __init__(self, serial: str | None = None, host: str = "127.0.0.1", port: int = 5037):
        self.serial = serial
        try:
            self._adb = adbutils.AdbClient(host=host, port=port)
            self._d: adbutils.AdbDevice = self._adb.device(serial)
        except Exception as e:  # noqa: BLE001 — surface as our own error type
            raise DeviceError(f"could not attach to device {serial!r}: {e}") from e
        self.toast = Toast()

    # ── raw adb device passthrough ───────────────────────────────────────────

    @property
    def adb_device(self) -> adbutils.AdbDevice:
        """The underlying adbutils device (for callers that already hold their
        own; autox and macrox each keep one — two cheap adb transports)."""
        return self._d

    def shell(self, cmd, timeout: float | None = None) -> str:
        return self._d.shell(cmd, timeout=timeout)

    # ── hierarchy ────────────────────────────────────────────────────────────

    def dump_hierarchy(self, compressed: bool = True, pretty: bool = False, max_depth: int = 50) -> str:
        """UI hierarchy XML via the AOSP ``uiautomator dump`` binary.

        Signature mirrors u2's; the shell binary always returns the full,
        uncompressed tree, so ``compressed``/``pretty``/``max_depth`` are
        accepted for drop-in parity but not applied (macrox filters the tree
        itself). Raises :class:`HierarchyDumpError` on a dead tree — matching
        u2, which raises on dump failure so callers fall through their
        recovery paths."""
        xml = self.dump_hierarchy_or_none()
        if xml is None:
            raise HierarchyDumpError("uiautomator dump produced no hierarchy (secure window or unavailable tree)")
        return xml

    def dump_hierarchy_or_none(self) -> str | None:
        """Like :meth:`dump_hierarchy` but returns None instead of raising —
        the form :class:`Selector` uses so a missing tree is a quiet miss."""
        try:
            status = self._d.shell(["uiautomator", "dump", _DUMP_PATH], timeout=_DUMP_TIMEOUT)
        except Exception:  # noqa: BLE001 — adb/transport hiccup ⇒ treat as no tree
            return None
        # AOSP prints "UI hierchary dumped to: <path>" (sic) on success; anything
        # else ("ERROR: could not get idle state", "null root node…") means the
        # file is absent or stale, so don't trust a cat of it.
        if "dumped" not in status.lower():
            return None
        try:
            raw = self._d.shell(["cat", _DUMP_PATH], timeout=_DUMP_TIMEOUT)
        except Exception:  # noqa: BLE001
            return None
        return trim_hierarchy_xml(raw)

    def dump_elements(self, screen: tuple[int, int] | None = None) -> list[dict]:
        """The current screen as a compact list of actionable/labelled elements
        — the token-cheap, agent-friendly observation. See
        :func:`autox.elements.compact_elements`. ``screen`` defaults to the live
        window size (enables off-screen culling). ``[]`` when the tree is
        unavailable."""
        return compact_elements(self.dump_hierarchy_or_none(), screen or self.window_size())

    def __call__(self, **kwargs) -> Selector:
        """``d(text="OK", instance=0)`` → a client-side :class:`Selector`."""
        return Selector(self, kwargs)

    # ── geometry / info ──────────────────────────────────────────────────────

    def window_size(self) -> tuple[int, int]:
        """(width, height) in the current rotation."""
        size = self._d.window_size()
        return int(size[0]), int(size[1])

    def _abs_xy(self, x, y) -> tuple[int, int]:
        """Absolute pixels. Floats in [0,1] are treated as fractions of the
        window (u2's convention); everything else is already absolute."""
        if isinstance(x, float) and isinstance(y, float) and 0 <= x <= 1 and 0 <= y <= 1:
            w, h = self.window_size()
            return int(x * w), int(y * h)
        return int(x), int(y)

    def _display_rotation(self) -> int:
        """0/1/2/3 for natural/left/upsidedown/right. 0 on any read failure
        (matches the portrait lock autox and macrox enforce)."""
        try:
            out = self._d.shell("dumpsys input")
            m = re.search(r"SurfaceOrientation:\s*(\d)", out)
            if m:
                return int(m.group(1))
        except Exception:  # noqa: BLE001
            pass
        try:
            out = self._d.shell(["settings", "get", "system", "user_rotation"])
            return int(out.strip())
        except Exception:  # noqa: BLE001
            return 0

    @property
    def info(self) -> dict:
        """u2-shaped device info. macrox reads ``displayRotation``; the rest is
        provided for parity and is cheap best-effort."""
        w, h = self.window_size()
        rotation = self._display_rotation()
        try:
            sdk = int(self._d.getprop("ro.build.version.sdk"))
        except Exception:  # noqa: BLE001
            sdk = 0
        try:
            product = self._d.getprop("ro.product.name")
        except Exception:  # noqa: BLE001
            product = ""
        try:
            package = self._d.app_current().package
        except Exception:  # noqa: BLE001
            package = None
        return {
            "currentPackageName": package,
            "displayWidth": w,
            "displayHeight": h,
            "displayRotation": rotation,
            "sdkInt": sdk,
            "productName": product,
            "screenOn": self._screen_on(),
            "naturalOrientation": rotation in (0, 2),
        }

    def _screen_on(self) -> bool:
        try:
            return "mWakefulness=Awake" in self._d.shell("dumpsys power")
        except Exception:  # noqa: BLE001
            return True

    # ── touch / key primitives ───────────────────────────────────────────────

    def click(self, x, y) -> None:
        px, py = self._abs_xy(x, y)
        self._d.shell(["input", "tap", str(px), str(py)])

    def double_click(self, x, y, duration: float = 0.1) -> None:
        px, py = self._abs_xy(x, y)
        self._d.shell(["input", "tap", str(px), str(py)])
        time.sleep(duration)
        self._d.shell(["input", "tap", str(px), str(py)])

    def long_click(self, x, y, duration: float = 0.5) -> None:
        px, py = self._abs_xy(x, y)
        ms = int(duration * 1000)
        # A same-point swipe with a long duration is the standard shell
        # substitute for a long press (`input` has no long-tap).
        self._d.shell(["input", "swipe", str(px), str(py), str(px), str(py), str(ms)])

    def swipe(self, x1, y1, x2, y2, duration: float = 0.5) -> None:
        sx, sy = self._abs_xy(x1, y1)
        ex, ey = self._abs_xy(x2, y2)
        self._d.shell(["input", "swipe", str(sx), str(sy), str(ex), str(ey), str(int(duration * 1000))])

    def drag(self, x1, y1, x2, y2, duration: float = 0.5) -> None:
        sx, sy = self._abs_xy(x1, y1)
        ex, ey = self._abs_xy(x2, y2)
        self._d.shell(["input", "draganddrop", str(sx), str(sy), str(ex), str(ey), str(int(duration * 1000))])

    def swipe_ext(self, direction: str, scale: float = 0.9, duration: float = 0.3) -> None:
        off = _SWIPE_OFFSETS.get(direction)
        if off is None:
            raise ValueError(f"unknown swipe direction: {direction!r}")
        w, h = self.window_size()
        cx, cy, dx, dy = w // 2, h // 2, int(scale * w / 2), int(scale * h / 2)
        sxo, syo, exo, eyo = off
        sx, sy, ex, ey = cx + sxo * dx, cy + syo * dy, cx + exo * dx, cy + eyo * dy
        self._d.shell(["input", "swipe", str(sx), str(sy), str(ex), str(ey), str(int(duration * 1000))])

    def press(self, key) -> None:
        """Press a key by u2 name ('home', 'back', 'enter'…), a raw
        'KEYCODE_*', or an integer keycode."""
        if isinstance(key, int):
            code = str(key)
        else:
            k = str(key).lower()
            code = _KEYCODES.get(k) or (key if str(key).startswith("KEYCODE_") else f"KEYCODE_{str(key).upper()}")
        self._d.shell(["input", "keyevent", code])

    # ── screenshot ───────────────────────────────────────────────────────────

    def screenshot(self):
        """PIL screenshot via adb ``screencap``."""
        return self._d.screenshot()

    # ── app / orientation / server-parity ────────────────────────────────────

    def app_start(self, package: str, use_monkey: bool = True, **kwargs) -> None:
        """Launch an app. Always via monkey's LAUNCHER intent — it needs no
        activity name and no APK stat (a split-APK stat is what crashes u2's
        atx-agent), so it is the robust launcher on modern apps."""
        self._d.shell(["monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])

    def set_orientation(self, orientation: str) -> None:
        value = _ORIENTATIONS.get(str(orientation).lower())
        if value is None:
            raise ValueError(f"unknown orientation: {orientation!r}")
        self._d.shell(["settings", "put", "system", "accelerometer_rotation", "0"])
        self._d.shell(["settings", "put", "system", "user_rotation", str(value)])

    def freeze_rotation(self, freeze: bool = True) -> None:
        """Lock (or release) auto-rotation."""
        self._d.shell(["settings", "put", "system", "accelerometer_rotation", "0" if freeze else "1"])

    def start_uiautomator(self) -> None:
        """No-op — autox runs no device-side server. Present so macrox's
        recovery chain (stop→start) is a harmless no-op instead of an
        AttributeError."""

    def stop_uiautomator(self) -> None:
        """No-op — see :meth:`start_uiautomator`."""

    # ── device control ───────────────────────────────────────────────────────

    def open_notification(self) -> None:
        self._d.shell(["cmd", "statusbar", "expand-notifications"])

    def open_quick_settings(self) -> None:
        self._d.shell(["cmd", "statusbar", "expand-settings"])

    def screen_on(self) -> None:
        self._d.shell(["input", "keyevent", "KEYCODE_WAKEUP"])

    def screen_off(self) -> None:
        self._d.shell(["input", "keyevent", "KEYCODE_SLEEP"])

    def unlock(self) -> None:
        """Wake and dismiss an insecure keyguard."""
        self._d.shell(["input", "keyevent", "KEYCODE_WAKEUP"])
        self._d.shell(["wm", "dismiss-keyguard"])
