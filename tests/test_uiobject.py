from autox.selector import Selector


def test_reads(fake_device):
    title = Selector(fake_device, {"resourceId": "com.app:id/title"})
    assert title.get_text() == "Settings"
    assert title.bounds() == (10, 20, 200, 80)
    info = title.info
    assert info["className"] == "android.widget.TextView"
    assert info["bounds"] == {"left": 10, "top": 20, "right": 200, "bottom": 80}
    assert info["clickable"] is False


def test_count_len_and_index(fake_device):
    ok = Selector(fake_device, {"text": "OK"})
    assert ok.count() == 2 and len(ok) == 2
    assert ok[1].center() == (200, 340)  # second OK button
    centers = [o.center() for o in ok]
    assert centers == [(200, 240), (200, 340)]


def test_child_descends(fake_device):
    frame = Selector(fake_device, {"className": "android.widget.FrameLayout"})
    assert frame.child(text="OK").center() == (200, 240)
    assert frame.child(text="OK").count() == 2


def test_sibling(fake_device):
    submit = Selector(fake_device, {"resourceId": "com.app:id/submit"})
    assert submit.sibling(resourceId="com.app:id/title").get_text() == "Settings"


def test_parent(fake_device):
    submit = Selector(fake_device, {"resourceId": "com.app:id/submit"})
    assert submit.parent().info["className"] == "android.widget.FrameLayout"


def test_directional(fake_device):
    # submit (center 200,240) and submit2 (center 200,340) share x-extent.
    submit = Selector(fake_device, {"resourceId": "com.app:id/submit"})
    submit2 = Selector(fake_device, {"resourceId": "com.app:id/submit2"})
    assert submit.down(text="OK").center() == (200, 340)
    assert submit2.up(text="OK").center() == (200, 240)


def test_missing_element_raises_on_strict_reads(fake_device):
    import pytest

    from autox.exceptions import UiObjectNotFoundError

    with pytest.raises(UiObjectNotFoundError):
        Selector(fake_device, {"text": "nope"}).get_text()
