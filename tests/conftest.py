import pytest

# A small but structurally real hierarchy: a labelled TextView, two same-text
# buttons (instance indexing), a zero-area node (must be filtered), and an
# icon-only node carrying only a content-desc.
HOME_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.app" bounds="[0,0][720,1600]">
    <node index="0" text="Settings" resource-id="com.app:id/title" class="android.widget.TextView" content-desc="" clickable="false" bounds="[10,20][200,80]"/>
    <node index="1" text="OK" resource-id="com.app:id/submit" class="android.widget.Button" clickable="true" bounds="[100,200][300,280]"/>
    <node index="2" text="OK" resource-id="com.app:id/submit2" class="android.widget.Button" clickable="true" bounds="[100,300][300,380]"/>
    <node index="3" text="Hidden" resource-id="com.app:id/zero" class="android.widget.TextView" bounds="[0,0][0,0]"/>
    <node index="4" text="" resource-id="" class="android.widget.ImageView" content-desc="Profile photo" clickable="true" bounds="[400,20][460,80]"/>
  </node>
</hierarchy>"""


@pytest.fixture
def home_xml():
    return HOME_XML


class FakeDevice:
    """Stand-in for Device in Selector tests: serves a fixed dump, records taps."""

    def __init__(self, xml, screen=(720, 1600)):
        self.xml = xml
        self.screen = screen
        self.taps: list[tuple[int, int]] = []

    def dump_hierarchy_or_none(self):
        return self.xml

    def window_size(self):
        return self.screen

    def click(self, x, y):
        self.taps.append((x, y))


@pytest.fixture
def fake_device(home_xml):
    return FakeDevice(home_xml)
