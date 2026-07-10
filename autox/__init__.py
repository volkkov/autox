"""autox — client-side Android UI automation that works on Android 16.

A drop-in for the slice of ``uiautomator2`` that macrox drives, with no
device-side server. Root cause it sidesteps: u2's bundled instrumentation NPEs
in ``UiDevice.setCompressedLayoutHeirarchy`` because ``getServiceInfo()`` returns
null on Android 16 (openatx/uiautomator2#1138), killing ``dump_hierarchy`` and
every selector that depends on it. autox dumps via the AOSP ``uiautomator dump``
binary and resolves selectors in the client instead.

    import autox as u2
    d = u2.connect("SERIAL")
    d.dump_hierarchy()
    d(text="Settings").click_exists(timeout=5)
"""

from autox import exceptions
from autox.device import Device
from autox.elements import compact_elements, compact_elements_json
from autox.selector import Selector

__version__ = "0.1.0"

__all__ = [
    "connect",
    "Device",
    "Selector",
    "compact_elements",
    "compact_elements_json",
    "exceptions",
    "__version__",
]


def connect(serial: str | None = None, host: str = "127.0.0.1", port: int = 5037) -> Device:
    """Attach to a device by serial (or the only attached device when None).

    Fast and side-effect-free: no APK push, no server start — unlike
    ``u2.connect``, which spends ~8 s bringing up an instrumentation server that
    then can't dump on Android 16."""
    return Device(serial=serial, host=host, port=port)
