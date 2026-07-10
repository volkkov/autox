"""Text input via autox's own bundled IME (``AutoxIME`` in ``server/``).

adb ``input text`` is ASCII-only and mangles spaces; an IME takes UTF-8, so
Unicode, emoji, and spaces all pass through. autox reimplements ADBKeyboard's
broadcast protocol inside its own server APK — the same APK that hosts the a11y
tree server — so typing needs no external app. All typing routes here, falling
back to adbutils ``send_keys`` only when the IME can't be brought up.

The IME's broadcast receiver commits to the focused field only while the IME is
the active method AND bound to that field, so :meth:`ensure_active` selects the
IME and polls ``dumpsys input_method`` until it is current and shown — broadcasting
before that races the cold start and the text is silently dropped.
"""

import base64
import logging
import time

from autox.treesource import SERVER_PACKAGE

logger = logging.getLogger(__name__)

# The IME ships in the autox server APK (see server/AutoxIME.java) — nothing to
# install separately.
IME = f"{SERVER_PACKAGE}/{SERVER_PACKAGE}.AutoxIME"


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

    def _state(self) -> tuple[str | None, bool]:
        try:
            ime = (self._d.shell("settings get secure default_input_method") or "").strip()
            dump = self._d.shell("dumpsys input_method") or ""
        except Exception:  # noqa: BLE001
            return (None, False)
        return (ime or None, "mInputShown=true" in dump)

    def ensure_active(self, timeout: float = 5.0) -> bool:
        """Make autox's IME the current method and wait until it is shown.
        Returns False if the autox APK isn't installed or it never becomes ready."""
        if not self.is_available():
            return False
        method, shown = self._state()
        if method != IME:
            # Only switch when needed — re-setting the active IME tears down a
            # working input connection.
            self._d.shell(["ime", "enable", IME])
            self._d.shell(["ime", "set", IME])
        deadline = time.time() + timeout
        while time.time() < deadline:
            method, shown = self._state()
            if method == IME and shown:
                return True
            time.sleep(0.3)
        return False

    def type(self, text: str) -> bool:
        """Type ``text`` (UTF-8, base64 over the broadcast). Returns success."""
        if not self.ensure_active():
            return False
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._d.shell(["am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64])
        return True

    def clear(self) -> bool:
        """Clear the focused field via ADB_CLEAR_TEXT. Returns success."""
        if not self.ensure_active():
            return False
        self._d.shell(["am", "broadcast", "-a", "ADB_CLEAR_TEXT"])
        return True

    def input_keycode(self, code: int) -> bool:
        if not self.ensure_active():
            return False
        self._d.shell(["am", "broadcast", "-a", "ADB_INPUT_CODE", "--ei", "code", str(code)])
        return True

    def editor_action(self, code: int) -> bool:
        """Perform an IME editor action (search/go/…) via ADB_EDITOR_CODE."""
        if not self.ensure_active():
            return False
        self._d.shell(["am", "broadcast", "-a", "ADB_EDITOR_CODE", "--ei", "code", str(code)])
        return True
