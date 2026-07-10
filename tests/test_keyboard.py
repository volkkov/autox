import base64

from autox.keyboard import IME, AutoxKeyboard


class FakeAdb:
    """adbutils stand-in tracking the active IME and keyboard-shown state."""

    def __init__(self, installed=True, ime="com.other/.X", shown=False):
        self.installed = installed
        self.ime = ime
        self.shown = shown
        self.log: list[str] = []

    def shell(self, cmd, timeout=None):
        s = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.log.append(s)
        if s.startswith("pm path"):
            return "package:/data/app/base.apk\n" if self.installed else ""
        if s.startswith("settings get secure default_input_method"):
            return self.ime
        if s.startswith("dumpsys input_method"):
            return "mInputShown=true" if self.shown else "mInputShown=false"
        if s.startswith("ime set"):
            self.ime = s.split("ime set", 1)[1].strip()
        if "KEYCODE_BACK" in s:
            self.shown = False  # BACK hid the keyboard
        return ""


def test_prepare_switches_ime():
    fake = FakeAdb(ime="com.other/.X")
    assert AutoxKeyboard(fake).prepare(timeout=1) is True
    assert fake.ime == IME


def test_prepare_hides_shown_keyboard_before_switching():
    fake = FakeAdb(ime="com.other/.X", shown=True)
    assert AutoxKeyboard(fake).prepare(timeout=1) is True
    back = next(i for i, s in enumerate(fake.log) if "KEYCODE_BACK" in s)
    switch = next(i for i, s in enumerate(fake.log) if s.startswith("ime set"))
    assert back < switch  # hidden the keyboard *before* the ime switch
    assert fake.ime == IME


def test_prepare_noop_when_already_active():
    fake = FakeAdb(ime=IME)
    assert AutoxKeyboard(fake).prepare() is True
    assert not any(s.startswith("ime set") for s in fake.log)


def test_prepare_false_when_not_installed():
    assert AutoxKeyboard(FakeAdb(installed=False)).prepare() is False


def test_commit_broadcasts_utf8_base64():
    fake = FakeAdb(ime=IME)
    AutoxKeyboard(fake).commit("hi 日本")
    b64 = base64.b64encode("hi 日本".encode()).decode()
    assert any("ADB_INPUT_B64" in s and b64 in s for s in fake.log)


def test_clear_broadcasts():
    fake = FakeAdb(ime=IME)
    AutoxKeyboard(fake).clear()
    assert any("ADB_CLEAR_TEXT" in s for s in fake.log)
