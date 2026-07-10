"""Text input via autox's own bundled IME (``AutoxIME`` in ``server/``).

adb ``input text`` is ASCII-only and mangles spaces; an IME takes UTF-8, so
Unicode and spaces pass through. autox reimplements ADBKeyboard's broadcast
protocol inside its own server APK — the same APK that hosts the a11y tree server
— so typing needs no external app.

Two Android facts drive the flow (both learned the hard way on Android 16):

* The system **will not switch IMEs while a keyboard is actively shown** —
  ``ime set`` silently no-ops. :meth:`prepare` hides the current keyboard first.
* autox's IME draws no visible view, so ``mInputShown`` never becomes true. It is
  NOT a readiness signal — ``commitText`` works whenever a field is focused. So
  :meth:`prepare` is called *before* focusing; the caller then focuses the field
  (which binds the input connection) and calls :meth:`commit`.
"""

import base64
import logging
import time

from autox.treesource import SERVER_PACKAGE

logger = logging.getLogger(__name__)

# The IME ships in the autox server APK (see server/AutoxIME.java). The id uses
# the relative class form the manifest declares (android:name=".AutoxIME") — the
# `ime` command rejects the fully-qualified form as "Unknown input method".
IME = f"{SERVER_PACKAGE}/.AutoxIME"


class AutoxKeyboard:
    """Drives autox's bundled IME for one device."""

    def __init__(self, adb_device):
        self._d = adb_device

    def is_available(self) -> bool:
        """Whether the autox APK (which carries the IME) is installed."""
        try:
            return bool(self._d.shell(["pm", "path", SERVER_PACKAGE]).strip())
        except Exception:  # noqa: BLE001
            return False

    def current(self) -> str:
        try:
            return (self._d.shell("settings get secure default_input_method") or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def is_active(self) -> bool:
        return self.current() == IME

    def _shown(self) -> bool:
        try:
            return "mInputShown=true" in (self._d.shell("dumpsys input_method") or "")
        except Exception:  # noqa: BLE001
            return False

    def prepare(self, timeout: float = 3.0) -> bool:
        """Make autox's IME the active method. Call BEFORE focusing the target
        field — the system won't switch IMEs while another keyboard is shown, so
        a shown keyboard is dismissed first. Returns whether autox's IME is now
        active."""
        if not self.is_available():
            return False
        if self.is_active():
            return True
        if self._shown():
            # BACK routes to the IME and just hides the keyboard (a field stays
            # focused), clearing the way for the switch.
            self._d.shell(["input", "keyevent", "KEYCODE_BACK"])
            time.sleep(0.4)
        self._d.shell(["ime", "enable", IME])
        self._d.shell(["ime", "set", IME])
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_active():
                return True
            time.sleep(0.2)
        return False

    def commit(self, text: str) -> None:
        """Insert ``text`` (UTF-8, base64) into the focused field."""
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._d.shell(["am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64])

    def clear(self) -> None:
        """Clear the focused field via ADB_CLEAR_TEXT."""
        self._d.shell(["am", "broadcast", "-a", "ADB_CLEAR_TEXT"])

    def input_keycode(self, code: int) -> None:
        self._d.shell(["am", "broadcast", "-a", "ADB_INPUT_CODE", "--ei", "code", str(code)])

    def editor_action(self, code: int) -> None:
        """Perform an IME editor action (search/go/…) via ADB_EDITOR_CODE."""
        self._d.shell(["am", "broadcast", "-a", "ADB_EDITOR_CODE", "--ei", "code", str(code)])
