"""The tree-source seam: where autox gets the UI hierarchy.

autox reads the accessibility tree through one small interface — :class:`TreeSource`,
a single ``dump() -> str | None`` that returns uiautomator-compatible hierarchy
XML (or None for a dead tree). Everything downstream — selectors, the compact
element list, ``dump_hierarchy`` — sits on that one method, so swapping how the
tree is produced never touches them.

Two adapters make the seam real, not hypothetical:

* :class:`RpcTreeSource` — the production path. Talks over ``adb forward`` to the
  device-side AccessibilityService RPC server (``server/``), which walks the live
  a11y tree and returns the XML. No uiautomator, no ``am instrument``, no jsonrpc
  server to NPE on Android 16 (see ADR 0001).
* :class:`StaticTreeSource` — serves a fixed XML string. Lets the whole client
  (selectors, elements) be tested with no device and no server.

The XML the server emits matches uiautomator's schema exactly (``<hierarchy>`` of
``<node>`` with bounds/text/resource-id/class/clickable/…), so the parser in
:mod:`autox.dump` and the selectors in :mod:`autox.selector` are unchanged.
"""

import logging
import time
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

from autox.dump import trim_hierarchy_xml

logger = logging.getLogger(__name__)

# Device-side RPC server coordinates. The AccessibilityService in server/ binds
# this port on the device loopback; `adb forward` bridges the same port on the
# host. Package/service must match server/AndroidManifest.xml and the port must
# match AutoxAccessibilityService.RPC_PORT.
#
# NOT 9008: that is uiautomator2's jsonrpc port, and a leftover u2 server there
# would both block our bind and answer our probes. /ping returns SERVER_IDENT so
# a foreign server on the port is detected instead of mistaken for autox.
DEFAULT_RPC_PORT = 9998
SERVER_PACKAGE = "com.gitshrl.autox"
SERVER_SERVICE = f"{SERVER_PACKAGE}/{SERVER_PACKAGE}.AutoxAccessibilityService"
SERVER_IDENT = "autox-rpc"  # /ping response prefix — proves we reached autox's server


@runtime_checkable
class TreeSource(Protocol):
    """Produces the current UI hierarchy as uiautomator-compatible XML, or None
    for a dead/unavailable tree."""

    def dump(self) -> str | None: ...


class StaticTreeSource:
    """A :class:`TreeSource` that always returns the same XML — for tests and
    for replaying a captured hierarchy."""

    def __init__(self, xml: str | None):
        self._xml = xml

    def dump(self) -> str | None:
        return self._xml


class ServerUnavailableError(RuntimeError):
    """The device-side RPC server could not be reached — not installed, not
    enabled as an accessibility service, or not yet started."""


class RpcTreeSource:
    """Reads the a11y tree from the device-side AccessibilityService over HTTP.

    Bring-up (install the APK, enable the service, forward the port) is done once
    lazily on the first :meth:`dump`; enabling and forwarding are idempotent.
    Installing the APK is the user's step — it must be built from ``server/``
    first (the build needs an Android SDK); :meth:`status` reports what is
    missing.
    """

    def __init__(
        self,
        adb_device,
        port: int = DEFAULT_RPC_PORT,
        connect_timeout: float = 5.0,
        ready_timeout: float = 6.0,
    ):
        self._d = adb_device
        self._port = port
        self._timeout = connect_timeout
        # How long to wait for the service's socket after a fresh enable — the
        # AccessibilityService cold-starts and binds its port on connect.
        self._ready_timeout = ready_timeout
        self._ready = False

    # ── bring-up ─────────────────────────────────────────────────────────────

    def _is_installed(self) -> bool:
        try:
            return bool(self._d.shell(f"pm path {SERVER_PACKAGE}").strip())
        except Exception:  # noqa: BLE001
            return False

    def _enabled_services(self) -> str:
        try:
            return self._d.shell("settings get secure enabled_accessibility_services") or ""
        except Exception:  # noqa: BLE001
            return ""

    def ensure_ready(self) -> None:
        """Enable the accessibility service and forward the port (idempotent).
        On a fresh enable, wait for the service to cold-start its socket. Raises
        :class:`ServerUnavailableError` if the APK isn't installed."""
        if not self._is_installed():
            raise ServerUnavailableError(
                f"{SERVER_PACKAGE} is not installed — build server/ (needs an Android SDK; "
                "the repo's CI builds autox-server.apk) and `adb install -r autox-server.apk`"
            )
        enabled = self._enabled_services()
        fresh = SERVER_SERVICE not in enabled
        if fresh:
            merged = SERVER_SERVICE if not enabled.strip() or enabled.strip() == "null" else f"{enabled}:{SERVER_SERVICE}"
            self._d.shell(f"settings put secure enabled_accessibility_services {merged}")
            self._d.shell("settings put secure accessibility_enabled 1")
            # So make_toast isn't suppressed (Android 13+ gates toasts on the
            # app's notifications being enabled). Best-effort.
            try:
                self._d.shell(["pm", "grant", SERVER_PACKAGE, "android.permission.POST_NOTIFICATIONS"])
            except Exception:  # noqa: BLE001
                pass
        # Bridge host:port -> device:port. adbutils forward is idempotent per pair.
        self._d.forward(f"tcp:{self._port}", f"tcp:{self._port}")
        if fresh:
            self._await_server()
        self._ready = True

    def _await_server(self) -> None:
        """Poll /ping until the freshly-enabled service answers as autox."""
        deadline = time.time() + self._ready_timeout
        while time.time() < deadline:
            try:
                if self._is_autox(self._http_get("/ping")):
                    return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.3)

    @staticmethod
    def _is_autox(body: str) -> bool:
        return body.strip().lower().startswith(SERVER_IDENT)

    # ── dump ─────────────────────────────────────────────────────────────────

    def _http_get(self, path: str) -> str:
        url = f"http://127.0.0.1:{self._port}{path}"
        with urllib.request.urlopen(url, timeout=self._timeout) as resp:  # noqa: S310 — fixed localhost URL
            return resp.read().decode("utf-8", errors="replace")

    def dump(self, retries: int = 1, retry_delay: float = 0.4) -> str | None:
        """Fetch the hierarchy XML from the server. None on a dead/empty tree.

        A transient miss (server mid-restart, screen not settled) is retried
        once. Returns None rather than raising so :class:`~autox.selector.Selector`
        treats an unreachable tree as a quiet miss; call :meth:`status` for a
        human-readable reason when bringing the server up."""
        for attempt in range(retries + 1):
            try:
                if not self._ready:
                    self.ensure_ready()
                xml = trim_hierarchy_xml(self._http_get("/dump"))
                if xml is not None:
                    return xml
            except ServerUnavailableError:
                return None  # not installed/enabled — a quiet miss; status() explains why
            except (urllib.error.URLError, OSError) as e:
                logger.debug("RPC dump attempt %d failed: %s", attempt + 1, e)
                self._ready = False  # re-run bring-up next attempt (forward may have dropped)
            if attempt < retries:
                time.sleep(retry_delay)
        return None

    def get_toast(self) -> tuple[int, str] | None:
        """(age_ms, text) of the last toast the a11y server captured, or None.
        age_ms is -1 when no toast has been seen."""
        self.ensure_ready()
        resp = self._http_get("/toast")
        if "\t" not in resp:
            return None
        age, text = resp.split("\t", 1)
        try:
            return (int(age), text)
        except ValueError:
            return None

    def show_toast(self, text: str) -> None:
        import base64

        self.ensure_ready()
        b64 = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
        self._http_get(f"/toastshow?b64={b64}")

    def clipboard_get(self) -> str:
        """Read the device clipboard via the server (the app owns clipboard
        access as the active IME)."""
        self.ensure_ready()
        return self._http_get("/clipboard")

    def clipboard_set(self, text: str) -> None:
        import base64

        self.ensure_ready()
        b64 = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
        self._http_get(f"/clipset?b64={b64}")

    def ping(self) -> bool:
        """True only if autox's own server answers — a foreign server on the
        port (e.g. u2's "pong") fails the identity check."""
        try:
            self.ensure_ready()
            return self._is_autox(self._http_get("/ping"))
        except (ServerUnavailableError, urllib.error.URLError, OSError):
            return False

    def status(self) -> str:
        """One-line diagnostic for selfcheck / bring-up."""
        if not self._is_installed():
            return f"NOT INSTALLED ({SERVER_PACKAGE}) — build+install server/autox-server.apk"
        if SERVER_SERVICE not in self._enabled_services():
            return "installed but accessibility service not enabled (autox enables it on first dump)"
        try:
            self.ensure_ready()
            body = self._http_get("/ping")
        except (ServerUnavailableError, urllib.error.URLError, OSError) as e:
            return f"installed+enabled but not responding on port {self._port} ({type(e).__name__})"
        if self._is_autox(body):
            return "ready"
        return f"port {self._port} answered by a non-autox server ({body.strip()[:24]!r})"
