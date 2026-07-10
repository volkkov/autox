"""The device driver — a uiautomator2-compatible surface, uiautomator-free.

The UI tree comes through the :class:`~autox.treesource.TreeSource` seam (in
production, the device-side AccessibilityService RPC server — no uiautomator, see
ADR 0001); selectors resolve in :mod:`autox.selector`; actions go through adb
``input`` / ``cmd`` / ``settings``. Controls need nothing on the device; only the
tree needs the RPC server enabled.

The method set mirrors the slice of u2 that macrox calls, so macrox can switch
``import uiautomator2 as u2`` to ``import autox as ax`` and drive it unchanged.
"""

import re
import time

import adbutils

from autox.elements import compact_elements
from autox.exceptions import DeviceError, HierarchyDumpError
from autox.selector import Selector
from autox.treesource import SERVER_PACKAGE, RpcTreeSource, TreeSource

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

# Foreground app from `dumpsys window displays`. On Android 16 the focus line
# moved here from `dumpsys window windows`; adbutils' stock app_current misses it
# and falls back to a ~5s `dumpsys activity top`, so resolve it directly (~45ms).
_FOCUS_RE = re.compile(r"mCurrentFocus=Window\{[^}]*\s(?P<pkg>[^\s/]+)/(?P<act>[^\s}]+)\}")

# send_action() IME action name -> keycode (fallback path).
_IME_ACTIONS = {
    "search": "KEYCODE_SEARCH",
    "go": "KEYCODE_ENTER",
    "send": "KEYCODE_ENTER",
    "next": "KEYCODE_TAB",
    "done": "KEYCODE_ENTER",
    "enter": "KEYCODE_ENTER",
}
# send_action() -> Android EditorInfo IME action codes (ADBKeyboard ADB_EDITOR_CODE).
_IME_EDITOR_CODES = {"go": 2, "search": 3, "send": 4, "next": 5, "done": 6, "previous": 7}


class _Recording:
    """Context manager returned by ``Device.screenrecord`` (u2 parity)."""

    def __init__(self, device, filename):
        self._device = device
        self._filename = filename

    def __enter__(self) -> "_Recording":
        self._device.start_recording(self._filename)
        return self

    def __exit__(self, *exc) -> None:
        self._device.stop_recording()

    def stop(self) -> None:
        self._device.stop_recording()


class Touch:
    """Low-level touch injection — parity with ``u2.touch``. Uses
    ``input motionevent`` (API 24+) to build custom gestures:
    ``d.touch.down(x, y)`` / ``d.touch.move(x, y)`` / ``d.touch.up(x, y)``."""

    def __init__(self, adb_device):
        self._d = adb_device

    def _event(self, action: str, x, y) -> None:
        self._d.shell(["input", "motionevent", action, str(int(x)), str(int(y))])

    def down(self, x, y) -> None:
        self._event("DOWN", x, y)

    def move(self, x, y) -> None:
        self._event("MOVE", x, y)

    def up(self, x, y) -> None:
        self._event("UP", x, y)

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
    """Reads captured toasts — parity with ``u2.toast``.

    The a11y server buffers the last toast text it saw (toasts arrive as
    accessibility events); ``get_message`` polls it. Returns ``default`` when the
    tree source can't report toasts (e.g. a StaticTreeSource)."""

    def __init__(self, device):
        self._device = device

    def get_message(self, wait_timeout: float = 10.0, cache_timeout: float = 10.0, default=None):
        """Wait up to ``wait_timeout`` for a toast captured within the last
        ``cache_timeout`` seconds; return its text or ``default``."""
        src = self._device.tree_source
        if not hasattr(src, "get_toast"):
            return default
        deadline = time.monotonic() + wait_timeout
        while True:
            latest = src.get_toast()
            if latest is not None:
                age_ms, text = latest
                if text and 0 <= age_ms <= cache_timeout * 1000:
                    return text
            if time.monotonic() >= deadline:
                return default
            time.sleep(0.3)

    def reset(self) -> None:
        """u2 parity; the buffer is server-side and self-expiring via age."""


class Device:
    """A single Android device, driven entirely over adb."""

    def __init__(
        self,
        serial: str | None = None,
        host: str = "127.0.0.1",
        port: int = 5037,
        tree_source: TreeSource | None = None,
    ):
        self.serial = serial
        try:
            self._adb = adbutils.AdbClient(host=host, port=port)
            self._d: adbutils.AdbDevice = self._adb.device(serial)
        except Exception as e:  # noqa: BLE001 — surface as our own error type
            raise DeviceError(f"could not attach to device {serial!r}: {e}") from e
        # The UI tree comes through this seam. Default: the device-side
        # AccessibilityService RPC server. Inject a StaticTreeSource for tests.
        self.tree_source: TreeSource = tree_source or RpcTreeSource(self._d)
        self.toast = Toast(self)
        # Immutable device props, read once on first info access (keeps connect
        # side-effect-free while sparing the getprop round-trips on every later
        # info read — macrox reads .info ~twice per agent step).
        self._sdk_int: int | None = None
        self._product_name: str | None = None

    # ── raw adb device passthrough ───────────────────────────────────────────

    @property
    def adb_device(self) -> adbutils.AdbDevice:
        """The underlying adbutils device (for callers that already hold their
        own; autox and macrox each keep one — two cheap adb transports)."""
        return self._d

    def shell(self, cmd, timeout: float | None = None) -> str:
        return self._d.shell(cmd, timeout=timeout)

    def _is_installed(self, package: str) -> bool:
        """Whether ``package`` has an installed APK path."""
        try:
            return bool(self._d.shell(["pm", "path", package]).strip())
        except Exception:  # noqa: BLE001
            return False

    # ── hierarchy ────────────────────────────────────────────────────────────

    def dump_hierarchy(self, compressed: bool = True, pretty: bool = False, max_depth: int = 50) -> str:
        """UI hierarchy XML from the :class:`~autox.treesource.TreeSource`.

        Signature mirrors u2's; the RPC server returns the full tree, so
        ``compressed``/``pretty``/``max_depth`` are accepted for drop-in parity
        but not applied (macrox filters the tree itself). Raises
        :class:`HierarchyDumpError` on a dead tree — matching u2, which raises on
        dump failure so callers fall through their recovery paths."""
        xml = self.dump_hierarchy_or_none()
        if xml is None:
            raise HierarchyDumpError(
                "no hierarchy — the accessibility RPC server is not reachable "
                f"({self.tree_source_status()}) or the tree is empty"
            )
        return xml

    def dump_hierarchy_or_none(self) -> str | None:
        """Like :meth:`dump_hierarchy` but returns None instead of raising — the
        form :class:`Selector` uses so a missing tree is a quiet miss. Transient
        retries live in the tree source, not here."""
        return self.tree_source.dump()

    def tree_source_status(self) -> str:
        """Human-readable state of the tree source (for bring-up / selfcheck)."""
        status = getattr(self.tree_source, "status", None)
        return status() if callable(status) else type(self.tree_source).__name__

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

    def exists(self, **kwargs) -> bool:
        """Whether a selector matches on the current screen — u2's ``d.exists``."""
        return self(**kwargs).exists

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
            return int(self._d.rotation()) % 4
        except Exception:  # noqa: BLE001
            pass
        try:
            return int(self._d.shell(["settings", "get", "system", "user_rotation"]).strip())
        except Exception:  # noqa: BLE001
            return 0

    def _cached_sdk_int(self) -> int:
        if self._sdk_int is None:
            try:
                self._sdk_int = int(self._d.getprop("ro.build.version.sdk"))
            except Exception:  # noqa: BLE001
                self._sdk_int = 0
        return self._sdk_int

    def _cached_product_name(self) -> str:
        if self._product_name is None:
            try:
                self._product_name = self._d.getprop("ro.product.name") or ""
            except Exception:  # noqa: BLE001
                self._product_name = ""
        return self._product_name

    def _foreground_package(self) -> str | None:
        try:
            m = _FOCUS_RE.search(self._d.shell(["dumpsys", "window", "displays"]))
            if m:
                return m.group("pkg")
        except Exception:  # noqa: BLE001
            pass
        try:
            return self._d.app_current().package
        except Exception:  # noqa: BLE001
            return None

    @property
    def info(self) -> dict:
        """u2-shaped device info. macrox reads ``displayRotation``; the rest is
        provided for parity. The immutable props (sdkInt, productName) are cached
        after first read so repeated ``.info`` access — macrox reads it ~twice
        per step — doesn't re-run getprop."""
        w, h = self.window_size()
        rotation = self._display_rotation()
        package = self._foreground_package()
        return {
            "currentPackageName": package,
            "displayWidth": w,
            "displayHeight": h,
            "displayRotation": rotation,
            "sdkInt": self._cached_sdk_int(),
            "productName": self._cached_product_name(),
            "screenOn": self._screen_on(),
            "naturalOrientation": rotation in (0, 2),
        }

    def _screen_on(self) -> bool:
        try:
            return bool(self._d.is_screen_on())
        except Exception:  # noqa: BLE001
            return True

    # ── touch / key primitives (adbutils where it has a robust one) ───────────

    def click(self, x, y) -> None:
        self._d.click(*self._abs_xy(x, y))

    def double_click(self, x, y, duration: float = 0.1) -> None:
        px, py = self._abs_xy(x, y)
        self._d.click(px, py)
        time.sleep(duration)
        self._d.click(px, py)

    def long_click(self, x, y, duration: float = 0.5) -> None:
        # A same-point swipe with a long duration is the standard substitute for
        # a long press (there is no long-tap primitive).
        px, py = self._abs_xy(x, y)
        self._d.swipe(px, py, px, py, duration)

    def swipe(self, x1, y1, x2, y2, duration: float = 0.5) -> None:
        sx, sy = self._abs_xy(x1, y1)
        ex, ey = self._abs_xy(x2, y2)
        self._d.swipe(sx, sy, ex, ey, duration)

    def drag(self, x1, y1, x2, y2, duration: float = 0.5) -> None:
        sx, sy = self._abs_xy(x1, y1)
        ex, ey = self._abs_xy(x2, y2)
        self._d.drag(sx, sy, ex, ey, duration)

    def swipe_ext(self, direction: str, scale: float = 0.9, duration: float = 0.3) -> None:
        off = _SWIPE_OFFSETS.get(direction)
        if off is None:
            raise ValueError(f"unknown swipe direction: {direction!r}")
        w, h = self.window_size()
        cx, cy, dx, dy = w // 2, h // 2, int(scale * w / 2), int(scale * h / 2)
        sxo, syo, exo, eyo = off
        self._d.swipe(cx + sxo * dx, cy + syo * dy, cx + exo * dx, cy + eyo * dy, duration)

    def press(self, key) -> None:
        """Press a key by u2 name ('home', 'back', 'enter'…), a raw
        'KEYCODE_*', or an integer keycode."""
        if isinstance(key, int):
            code = key
        else:
            k = str(key).lower()
            code = _KEYCODES.get(k) or (key if str(key).startswith("KEYCODE_") else f"KEYCODE_{str(key).upper()}")
        self._d.keyevent(code)

    # ── screenshot ───────────────────────────────────────────────────────────

    def screenshot(self):
        """PIL screenshot via adb ``screencap``."""
        return self._d.screenshot()

    def start_recording(self, filename: str) -> None:
        """Begin screen recording to a local ``filename`` (adbutils/scrcpy)."""
        self._d.start_recording(filename)

    def stop_recording(self) -> None:
        self._d.stop_recording()

    def is_recording(self) -> bool:
        return bool(self._d.is_recording())

    def screenrecord(self, filename: str) -> "_Recording":
        """u2-named context manager: ``with d.screenrecord('out.mp4'): …``."""
        return _Recording(self, filename)

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
        """Bring the tree source up (enable the a11y RPC server + forward).
        Named for u2 parity; best-effort — a StaticTreeSource has nothing to do."""
        ensure = getattr(self.tree_source, "ensure_ready", None)
        if callable(ensure):
            try:
                ensure()
            except Exception:  # noqa: BLE001 — bring-up is best-effort
                pass

    def stop_uiautomator(self) -> None:
        """No-op — the a11y server stays enabled for the session; see
        :meth:`start_uiautomator`."""

    def reset_uiautomator(self, reason: str = "") -> None:
        """u2 parity: re-run tree-source bring-up. autox has no server to crash,
        so this just re-ensures the a11y service is enabled and forwarded."""
        self.start_uiautomator()

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

    def make_toast(self, text: str, duration: float = 1.0) -> None:
        """Show a toast on the device via autox's server (u2 parity; also the
        way to exercise toast capture)."""
        src = self.tree_source
        if not hasattr(src, "show_toast"):
            raise DeviceError("make_toast needs the RPC tree source (install autox-server.apk)")
        src.show_toast(text)

    @property
    def last_toast(self) -> str | None:
        """The last captured toast text (within the cache window), or None."""
        return self.toast.get_message(wait_timeout=0)

    def clear_toast(self) -> None:
        """u2 parity; the toast buffer is server-side and self-expires by age."""
        self.toast.reset()

    def keyevent(self, key) -> None:
        """Alias for :meth:`press` — u2 name."""
        self.press(key)

    def long_press(self, x, y, duration: float = 1.0) -> None:
        self.long_click(x, y, duration=duration)

    def open_url(self, url: str) -> None:
        self._d.shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def pos_rel2abs(self, x, y) -> tuple[int, int]:
        """Fractional (0-1) coordinates → absolute pixels."""
        return self._abs_xy(x, y)

    @property
    def touch(self) -> Touch:
        return Touch(self._d)

    def gesture(self, strokes, duration: float = 0.3) -> None:
        """Dispatch a multi-touch gesture through the a11y server (real touch, via
        ``dispatchGesture``). Each stroke is ``(x1, y1, x2, y2)``; all strokes run
        simultaneously — two strokes make a pinch."""
        src = self.tree_source
        if not hasattr(src, "gesture"):
            raise DeviceError("gesture needs the RPC tree source (install autox-server.apk)")
        src.gesture([tuple(int(v) for v in s) for s in strokes], int(duration * 1000))

    def swipe_points(self, points, duration: float = 0.5) -> None:
        """Swipe through a path of (x, y) points as one continuous gesture."""
        pts = [self._abs_xy(px, py) for px, py in points]
        if len(pts) < 2:
            raise ValueError("swipe_points needs at least 2 points")
        step = max(duration / (len(pts) - 1), 0.01)
        self.touch.down(*pts[0])
        for px, py in pts[1:]:
            time.sleep(step)
            self.touch.move(px, py)
        self.touch.up(*pts[-1])

    # ── app management ───────────────────────────────────────────────────────

    def app_current(self) -> dict:
        """{"package", "activity"} of the foreground app."""
        try:
            m = _FOCUS_RE.search(self._d.shell(["dumpsys", "window", "displays"]))
            if m:
                return {"package": m.group("pkg"), "activity": m.group("act")}
        except Exception:  # noqa: BLE001
            pass
        info = self._d.app_current()
        return {"package": info.package, "activity": info.activity}

    def app_stop(self, package: str) -> None:
        self._d.app_stop(package)

    def app_clear(self, package: str) -> None:
        self._d.app_clear(package)

    def app_install(self, path_or_url: str) -> None:
        """Install an APK from a local path or an http(s) URL (adbutils handles
        the download)."""
        self._d.install(path_or_url, nolaunch=True)

    def app_uninstall(self, package: str) -> bool:
        """Uninstall a package. Returns whether it was installed beforehand."""
        if not self._is_installed(package):
            return False
        self._d.uninstall(package)
        return True

    def app_list(self, filter_third_party: bool = False) -> list[str]:
        """Installed package names. ``filter_third_party`` limits to user apps."""
        if filter_third_party:
            out = self._d.shell(["pm", "list", "packages", "-3"])
            return sorted(line[8:].strip() for line in out.splitlines() if line.startswith("package:"))
        return sorted(self._d.list_packages())

    def app_list_running(self) -> list[str]:
        """Installed packages that currently have a running process."""
        installed = set(self.app_list())
        try:
            procs = self._d.shell(["ps", "-A", "-o", "NAME"])
        except Exception:  # noqa: BLE001
            procs = self._d.shell(["ps"])
        running = {ln.strip().split(":", 1)[0] for ln in procs.splitlines()}
        return sorted(installed & running)

    def app_stop_all(self, excludes=()) -> list[str]:
        """Force-stop every running third-party app except ``excludes``."""
        excl = set(excludes)
        stopped = []
        for pkg in self.app_list_running():
            if pkg in excl or pkg == SERVER_PACKAGE:
                continue
            self.app_stop(pkg)
            stopped.append(pkg)
        return stopped

    def app_info(self, package: str) -> dict:
        """Version/metadata via adbutils ``package_info``."""
        pi = self._d.package_info(package)
        if pi is None:
            raise DeviceError(f"app not installed: {package}")
        return {
            "packageName": package,
            "versionName": pi.get("version_name"),
            "versionCode": pi.get("version_code"),
            **pi,
        }

    def app_wait(self, package: str, timeout: float = 20.0, front: bool = False) -> bool:
        """Wait until ``package`` is running (or foreground when ``front``)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if (self.app_current()["package"] == package) if front else (package in self.app_list_running()):
                return True
            time.sleep(0.5)
        return False

    def wait_activity(self, activity: str, timeout: float = 10.0) -> bool:
        """Wait until the foreground activity contains ``activity``."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if activity in self.app_current()["activity"]:
                return True
            time.sleep(0.5)
        return False

    # ── files ────────────────────────────────────────────────────────────────

    def push(self, src: str, dst: str) -> None:
        self._d.sync.push(src, dst)

    def pull(self, src: str, dst: str) -> None:
        self._d.sync.pull(src, dst)

    # ── device info ──────────────────────────────────────────────────────────

    @property
    def device_info(self) -> dict:
        props = {
            "serial": self.serial or self._d.serial,
            "sdk": self._cached_sdk_int(),
            "brand": self._getprop("ro.product.brand"),
            "model": self._getprop("ro.product.model"),
            "arch": self._getprop("ro.product.cpu.abi"),
            "version": self._getprop("ro.build.version.release"),
        }
        return props

    def _getprop(self, name: str) -> str:
        try:
            return self._d.getprop(name) or ""
        except Exception:  # noqa: BLE001
            return ""

    @property
    def wlan_ip(self) -> str | None:
        try:
            return self._d.wlan_ip() or None
        except Exception:  # noqa: BLE001
            return self._getprop("dhcp.wlan0.ipaddress") or None

    @property
    def orientation(self) -> str:
        """Current rotation name: natural/left/upsidedown/right."""
        return ("natural", "left", "upsidedown", "right")[self._display_rotation() % 4]

    # ── text input / IME ─────────────────────────────────────────────────────

    @property
    def image(self):
        """Template matching over screenshots (u2's ``d.image``; needs
        ``autox[image]``)."""
        if getattr(self, "_image", None) is None:
            from autox.image import ImageX

            self._image = ImageX(self)
        return self._image

    @property
    def keyboard(self):
        """autox's bundled IME driver (lazy)."""
        if getattr(self, "_keyboard", None) is None:
            from autox.keyboard import AutoxKeyboard

            self._keyboard = AutoxKeyboard(self._d)
        return self._keyboard

    def _type_text(self, text: str) -> None:
        # If autox's IME is already active, commit UTF-8 through it; otherwise adb
        # `input text` (ASCII) injects into the focused field without an IME
        # switch. Robust UTF-8 typing is the selector path (UiObject.set_text),
        # which re-focuses after switching the IME.
        if self.keyboard.is_active():
            self.keyboard.commit(text)
        else:
            self._d.send_keys(text)

    def send_keys(self, text: str, clear: bool = False) -> None:
        """Type into the focused field; ``clear`` wipes it first."""
        if clear:
            self.clear_text()
        self._type_text(text)

    def clear_text(self, count: int = 120) -> None:
        """Clear the focused field: via autox's IME if active, else cursor-to-end
        then a burst of deletes."""
        if self.keyboard.is_active():
            self.keyboard.clear()
            return
        self._d.shell(["input", "keyevent", "KEYCODE_MOVE_END"])
        self._d.shell("input keyevent " + ("67 " * count).strip())  # 67 = KEYCODE_DEL

    def send_action(self, action: str = "search") -> None:
        """Trigger an IME action (search/go/next/done/send) — via autox's IME
        editor action when active, else a keyevent."""
        code = _IME_EDITOR_CODES.get(action.lower())
        if code is not None and self.keyboard.is_active():
            self.keyboard.editor_action(code)
            return
        self._d.shell(["input", "keyevent", _IME_ACTIONS.get(action.lower(), "KEYCODE_ENTER")])

    def hide_keyboard(self) -> None:
        """Dismiss the soft keyboard if one is shown (BACK routes to the IME)."""
        try:
            shown = "mInputShown=true" in (self._d.shell("dumpsys input_method") or "")
        except Exception:  # noqa: BLE001
            shown = False
        if shown:
            self.press("back")

    def current_ime(self) -> str:
        return (self._d.shell("settings get secure default_input_method") or "").strip()

    def set_input_ime(self, ime: str) -> None:
        self._d.shell(["ime", "enable", ime])
        self._d.shell(["ime", "set", ime])

    def is_input_ime_installed(self, ime: str) -> bool:
        try:
            return ime in (self._d.shell(["ime", "list", "-a", "-s"]) or "")
        except Exception:  # noqa: BLE001
            return False

    # ── clipboard (via autox's own server) ───────────────────────────────────
    #
    # Android 10+ restricts clipboard access to the foreground app or the active
    # IME. autox's APK is both an a11y service and an IME, so it can read/write
    # the clipboard when its IME is active — no external clipper app (which is
    # dead on Android 16 anyway; its APK targets SDK 0).

    def _clipboard_rpc(self):
        src = self.tree_source
        if not hasattr(src, "clipboard_get"):
            raise DeviceError("clipboard needs the RPC tree source (install autox-server.apk)")
        self.keyboard.prepare()  # app must be the active IME for clipboard access
        return src

    @property
    def clipboard(self) -> str | None:
        """Read the clipboard text."""
        return self._clipboard_rpc().clipboard_get() or None

    def set_clipboard(self, text: str, label: str | None = None) -> None:
        """Set the clipboard text."""
        self._clipboard_rpc().clipboard_set(text)

    # ── settings / waits / query factories ───────────────────────────────────

    @property
    def settings(self) -> dict:
        if getattr(self, "_settings", None) is None:
            self._settings = {"wait_timeout": 20.0, "xpath_timeout": 10.0, "operation_delay": (0, 0)}
        return self._settings

    def implicitly_wait(self, seconds: float | None = None) -> float:
        """Get or set the default element wait timeout (u2 parity)."""
        if seconds is not None:
            self.settings["wait_timeout"] = seconds
        return self.settings["wait_timeout"]

    @property
    def wait_timeout(self) -> float:
        return self.settings["wait_timeout"]

    def xpath(self, xpath: str):
        """``d.xpath('//node[@text="OK"]')`` → an :class:`~autox.xpath.XPathSelector`."""
        from autox.xpath import XPathSelector

        return XPathSelector(self, xpath)

    @property
    def watcher(self):
        from autox.watcher import Watcher

        if getattr(self, "_watcher", None) is None:
            self._watcher = Watcher(self)
        return self._watcher

    def watch_context(self, builtin: bool = False):
        from autox.watcher import WatchContext

        return WatchContext(self, builtin=builtin)
