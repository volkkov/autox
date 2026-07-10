import pytest

from autox.treesource import (
    SERVER_SERVICE,
    RpcTreeSource,
    ServerUnavailableError,
    StaticTreeSource,
)


class FakeAdb:
    """Minimal adbutils stand-in: answers pm/settings, records forwards."""

    def __init__(self, installed=True, enabled=""):
        self.installed = installed
        self.enabled = enabled
        self.shell_log: list[str] = []
        self.forwards: list[tuple[str, str]] = []

    def shell(self, cmd, timeout=None):
        s = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.shell_log.append(s)
        if s.startswith("pm path"):
            return "package:/data/app/base.apk\n" if self.installed else ""
        if s.startswith("settings get secure enabled_accessibility_services"):
            return self.enabled
        if s.startswith("settings put secure enabled_accessibility_services"):
            self.enabled = s.split("enabled_accessibility_services", 1)[1].strip()
        return ""

    def forward(self, local, remote):
        self.forwards.append((local, remote))


def test_static_source():
    assert StaticTreeSource("<hierarchy/>").dump() == "<hierarchy/>"
    assert StaticTreeSource(None).dump() is None


def test_status_not_installed():
    src = RpcTreeSource(FakeAdb(installed=False))
    assert src.status().startswith("NOT INSTALLED")


def test_ensure_ready_raises_when_not_installed():
    with pytest.raises(ServerUnavailableError):
        RpcTreeSource(FakeAdb(installed=False)).ensure_ready()


def test_dump_returns_none_when_not_installed():
    # Selector relies on a quiet None (not an exception) for a missing server.
    assert RpcTreeSource(FakeAdb(installed=False)).dump() is None


def test_ensure_ready_enables_service_and_forwards():
    fake = FakeAdb(installed=True, enabled="null")
    RpcTreeSource(fake, port=9008).ensure_ready()
    assert SERVER_SERVICE in fake.enabled
    assert ("tcp:9008", "tcp:9008") in fake.forwards
    assert any("accessibility_enabled 1" in s for s in fake.shell_log)


def test_ensure_ready_appends_to_existing_services():
    fake = FakeAdb(installed=True, enabled="com.other/.Svc")
    RpcTreeSource(fake).ensure_ready()
    assert "com.other/.Svc" in fake.enabled  # existing service preserved
    assert SERVER_SERVICE in fake.enabled


def test_ensure_ready_idempotent_when_already_enabled():
    fake = FakeAdb(installed=True, enabled=SERVER_SERVICE)
    RpcTreeSource(fake).ensure_ready()
    # already enabled -> no settings put for enabled_accessibility_services
    assert not any(s.startswith("settings put secure enabled_accessibility_services") for s in fake.shell_log)
