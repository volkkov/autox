"""autox — client-side Android UI automation that works on Android 16.

A drop-in for the slice of ``uiautomator2`` that macrox drives, with no
uiautomator anywhere. Root cause it sidesteps: u2's bundled instrumentation NPEs
in ``UiDevice.setCompressedLayoutHeirarchy`` because ``getServiceInfo()`` returns
null on Android 16 (openatx/uiautomator2#1138), killing ``dump_hierarchy`` and
every selector that depends on it.

autox splits the problem cleanly (ADR 0001):

* **Controls** (tap/swipe/key/screenshot/app-launch/orientation) run over adb
  ``input`` / ``cmd`` / ``settings`` — nothing on the device.
* **Observation** (the UI tree) comes through the :class:`~autox.treesource.TreeSource`
  seam. In production that's the device-side AccessibilityService RPC server in
  ``server/`` — no uiautomator, no ``am instrument``. Selectors and the compact
  element list resolve client-side against its XML.

    import autox as ax
    d = ax.connect("SERIAL")
    d.dump_hierarchy()
    d(text="Settings").click_exists(timeout=5)
"""

from autox import exceptions
from autox.device import Device
from autox.elements import compact_elements, compact_elements_json
from autox.selector import Selector, UiObject
from autox.treesource import RpcTreeSource, StaticTreeSource, TreeSource
from autox.xpath import XPathSelector

__version__ = "0.1.0"

__all__ = [
    "connect",
    "install_as_uiautomator2",
    "Device",
    "Selector",
    "UiObject",
    "XPathSelector",
    "TreeSource",
    "RpcTreeSource",
    "StaticTreeSource",
    "compact_elements",
    "compact_elements_json",
    "exceptions",
    "__version__",
]


def connect(serial: str | None = None, host: str = "127.0.0.1", port: int = 5037) -> Device:
    """Attach to a device by serial (or the only attached device when None).

    Fast and side-effect-free: no APK push, no server start at connect time —
    the tree source brings the RPC server up lazily on first dump."""
    return Device(serial=serial, host=host, port=port)


def install_as_uiautomator2() -> None:
    """Alias autox as the ``uiautomator2`` module so existing u2 code runs on
    autox unchanged — a zero-edit drop-in. Call it before importing code that
    does ``import uiautomator2``:

        import autox
        autox.install_as_uiautomator2()
        # code that `import uiautomator2 as u2` now gets autox

    Verified: macrox's Environment drives autox this way with selectors live on
    Android 16.
    """
    import sys

    sys.modules["uiautomator2"] = sys.modules[__name__]
    sys.modules["uiautomator2.exceptions"] = exceptions
