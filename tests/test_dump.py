from autox.dump import center_of, is_tappable_area, parse_bounds, trim_hierarchy_xml


def test_trim_strips_trailing_status_line():
    raw = "<?xml version='1.0'?><hierarchy></hierarchy>UI hierchary dumped to: /dev/tty"
    assert trim_hierarchy_xml(raw) == "<?xml version='1.0'?><hierarchy></hierarchy>"


def test_trim_handles_leading_and_trailing_junk():
    raw = "garbage\n<?xml ?><hierarchy rotation='0'></hierarchy>\n\n"
    assert trim_hierarchy_xml(raw) == "<?xml ?><hierarchy rotation='0'></hierarchy>"


def test_trim_without_xml_decl_uses_hierarchy_tag():
    raw = "<hierarchy></hierarchy>trailer"
    assert trim_hierarchy_xml(raw) == "<hierarchy></hierarchy>"


def test_trim_returns_none_on_failed_dump():
    assert trim_hierarchy_xml("ERROR: could not get idle state.") is None
    assert trim_hierarchy_xml("") is None
    assert trim_hierarchy_xml(None) is None  # type: ignore[arg-type]


def test_parse_bounds():
    assert parse_bounds("[0,0][720,1600]") == (0, 0, 720, 1600)
    assert parse_bounds("[-5,10][15,20]") == (-5, 10, 15, 20)
    assert parse_bounds("nonsense") is None
    assert parse_bounds("") is None


def test_center_and_area():
    assert center_of((100, 200, 300, 280)) == (200, 240)
    assert is_tappable_area((100, 200, 300, 280)) is True
    assert is_tappable_area((0, 0, 0, 0)) is False
    assert is_tappable_area((5, 5, 5, 20)) is False  # zero width
