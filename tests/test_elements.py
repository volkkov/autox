import json

from autox.elements import compact_elements, compact_elements_json

_WRAPPER_XML = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" clickable="true" bounds="[0,0][200,100]">
    <node class="android.widget.TextView" text="Buy now" clickable="false" bounds="[10,10][190,90]"/>
  </node>
</hierarchy>"""

_OFFSCREEN_XML = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node class="android.widget.Button" text="Onscreen" clickable="true" bounds="[10,10][100,60]"/>
  <node class="android.widget.Button" text="Offscreen" clickable="true" bounds="[800,10][900,60]"/>
</hierarchy>"""


def test_actions_and_filtering(home_xml):
    els = compact_elements(home_xml)
    by_id = {e.get("id"): e for e in els}
    # Settings: text but not clickable -> read
    assert by_id["title"]["action"] == "read"
    assert by_id["title"]["text"] == "Settings"
    # OK button -> tap, center of [100,200][300,280]
    assert by_id["submit"]["action"] == "tap"
    assert by_id["submit"]["center"] == [200, 240]
    # zero-area "Hidden" dropped
    assert "zero" not in by_id
    # icon-only node keeps its content-desc as text
    photo = next(e for e in els if e.get("text") == "Profile photo")
    assert photo["action"] == "tap"


def test_wrapper_merge_folds_label_into_clickable():
    els = compact_elements(_WRAPPER_XML)
    assert len(els) == 1
    assert els[0]["type"] == "FrameLayout"
    assert els[0]["action"] == "tap"
    assert els[0]["text"] == "Buy now"  # inherited from the lone contained read


def test_offscreen_culled_with_screen():
    assert len(compact_elements(_OFFSCREEN_XML)) == 2  # no screen -> no cull
    culled = compact_elements(_OFFSCREEN_XML, screen=(720, 1600))
    assert [e["text"] for e in culled] == ["Onscreen"]


def test_empty_and_unparseable():
    assert compact_elements(None) == []
    assert compact_elements("") == []
    assert compact_elements("<broken") == []


def test_json_is_compact_and_roundtrips(home_xml):
    s = compact_elements_json(home_xml)
    assert ", " not in s and ": " not in s  # separators tightened for tokens
    assert json.loads(s) == compact_elements(home_xml)
