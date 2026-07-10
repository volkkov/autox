import autox


class _FakeAdb:
    def window_size(self):
        return (720, 1600)


def _device_with_tree(xml):
    # Bypass __init__ (which needs a real adb); wire just what exists() touches.
    d = object.__new__(autox.Device)
    d.tree_source = autox.StaticTreeSource(xml)
    d._d = _FakeAdb()
    return d


def test_device_exists_by_text(home_xml):
    d = _device_with_tree(home_xml)
    assert d.exists(text="OK") is True
    assert d.exists(text="nope") is False


def test_device_exists_by_resource_id(home_xml):
    d = _device_with_tree(home_xml)
    assert d.exists(resourceId="com.app:id/submit") is True
