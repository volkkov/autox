import pytest

from autox.selector import Selector, match_nodes


def test_text_exact_matches_both_buttons(home_xml):
    m = match_nodes(home_xml, {"text": "OK"})
    assert [n.center for n in m] == [(200, 240), (200, 340)]


def test_text_contains(home_xml):
    m = match_nodes(home_xml, {"textContains": "etting"})
    assert len(m) == 1 and m[0].center == (105, 50)


def test_resource_id_exact(home_xml):
    m = match_nodes(home_xml, {"resourceId": "com.app:id/submit"})
    assert len(m) == 1 and m[0].center == (200, 240)


def test_resource_id_matches_anchors_suffix(home_xml):
    # macrox's _resource_selector builds '.*/submit$' — must hit submit, not submit2.
    m = match_nodes(home_xml, {"resourceIdMatches": r".*/submit$"})
    assert len(m) == 1 and m[0].attrib["resource-id"] == "com.app:id/submit"


def test_description_exact(home_xml):
    m = match_nodes(home_xml, {"description": "Profile photo"})
    assert len(m) == 1 and m[0].center == (430, 50)


def test_zero_area_node_is_filtered(home_xml):
    assert match_nodes(home_xml, {"text": "Hidden"}) == []


_OFFSCREEN_DUP = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node text="Go" class="android.widget.Button" bounds="[800,10][900,60]"/>
  <node text="Go" class="android.widget.Button" bounds="[100,200][300,280]"/>
</hierarchy>"""


def test_offscreen_node_culled_only_when_screen_known():
    # Without screen: both match (instance 0 is the off-screen one).
    both = match_nodes(_OFFSCREEN_DUP, {"text": "Go"})
    assert [n.center for n in both] == [(850, 35), (200, 240)]
    # With screen: the off-screen namesake is dropped, so instance 0 is visible.
    visible = match_nodes(_OFFSCREEN_DUP, {"text": "Go"}, screen=(720, 1600))
    assert [n.center for n in visible] == [(200, 240)]


def test_unsupported_kwarg_raises(home_xml):
    with pytest.raises(ValueError):
        match_nodes(home_xml, {"bogusAttr": "x"})


def test_empty_or_missing_xml():
    assert match_nodes(None, {"text": "OK"}) == []
    assert match_nodes("", {"text": "OK"}) == []
    assert match_nodes("<not-xml", {"text": "OK"}) == []


def test_selector_click_exists_taps_center(fake_device):
    assert Selector(fake_device, {"text": "OK"}).click_exists(timeout=0) is True
    assert fake_device.taps == [(200, 240)]


def test_selector_instance_selects_second(fake_device):
    assert Selector(fake_device, {"text": "OK", "instance": 1}).click_exists(timeout=0) is True
    assert fake_device.taps == [(200, 340)]


def test_selector_absent_returns_false_without_tap(fake_device):
    assert Selector(fake_device, {"text": "Nope"}).click_exists(timeout=0) is False
    assert fake_device.taps == []


def test_selector_exists_count_center(fake_device):
    sel = Selector(fake_device, {"text": "OK"})
    assert sel.exists is True
    assert sel.count() == 2
    assert sel.center() == (200, 240)
