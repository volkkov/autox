"""Exception hierarchy, name-compatible with ``uiautomator2.exceptions``.

macrox imports ``BaseException`` and ``UiAutomationNotConnectedError`` from
uiautomator2's exceptions module and branches on them (see its
``_is_u2_dead`` / ``_try_u2_action``). Mirroring the names lets macrox switch
its import to ``autox`` without touching that recovery logic.
"""


class BaseException(Exception):  # noqa: A001 — deliberately mirrors uiautomator2.exceptions.BaseException
    """Root of every autox device error."""


class DeviceError(BaseException):
    """A device/adb-level failure (serial not attached, adb transport gone)."""


class HierarchyDumpError(BaseException):
    """The UI hierarchy could not be dumped — a dead tree (e.g. a secure
    window that blocks accessibility), distinct from a valid empty screen."""


class UiAutomationNotConnectedError(BaseException):
    """Kept for API parity with uiautomator2. autox never raises it — it runs
    no device-side UiAutomation server, so there is no connection to lose — but
    macrox's recovery chain catches this type, so the name must resolve."""
