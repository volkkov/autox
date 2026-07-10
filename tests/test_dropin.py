import sys

import autox


def test_install_as_uiautomator2_aliases_module():
    had = "uiautomator2" in sys.modules
    try:
        autox.install_as_uiautomator2()
        assert sys.modules["uiautomator2"] is autox
        assert sys.modules["uiautomator2.exceptions"] is autox.exceptions
        # existing u2 code resolves to autox
        import uiautomator2 as u2  # noqa: PLC0415
        from uiautomator2.exceptions import UiAutomationNotConnectedError  # noqa: PLC0415, F401

        assert u2.connect is autox.connect
    finally:
        if not had:
            sys.modules.pop("uiautomator2", None)
            sys.modules.pop("uiautomator2.exceptions", None)
