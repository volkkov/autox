from autox.xpath import XPathSelector, normalize_xpath


def test_normalize_shorthands():
    assert normalize_xpath("@com.app:id/x") == '//node[@resource-id="com.app:id/x"]'
    assert normalize_xpath("com.app:id/x") == '//node[@resource-id="com.app:id/x"]'
    assert normalize_xpath("Hello") == '//*[@text="Hello"]'
    assert normalize_xpath('//node[@text="Y"]') == '//node[@text="Y"]'


def test_query_by_text(fake_device):
    assert XPathSelector(fake_device, '//node[@text="Settings"]').get_text() == "Settings"


def test_query_by_resource_id_shorthand(fake_device):
    assert XPathSelector(fake_device, "@com.app:id/submit").exists
    assert XPathSelector(fake_device, "com.app:id/submit").center() == (200, 240)


def test_query_bare_text_shorthand(fake_device):
    assert XPathSelector(fake_device, "Settings").exists


def test_query_by_class_all(fake_device):
    buttons = XPathSelector(fake_device, '//node[@class="android.widget.Button"]').all()
    assert [n.center for n in buttons] == [(200, 240), (200, 340)]


def test_missing_xpath_not_exists(fake_device):
    assert XPathSelector(fake_device, '//node[@text="ghost"]').exists is False
