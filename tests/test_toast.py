from autox.device import Toast


class FakeSrc:
    """Yields a scripted sequence of (age_ms, text) tuples from get_toast()."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def get_toast(self):
        v = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return v


class FakeDev:
    def __init__(self, src):
        self.tree_source = src


def test_returns_fresh_toast():
    dev = FakeDev(FakeSrc([(200, "Saved")]))
    assert Toast(dev).get_message(wait_timeout=1, cache_timeout=10) == "Saved"


def test_ignores_stale_toast():
    dev = FakeDev(FakeSrc([(999999, "old news")]))
    assert Toast(dev).get_message(wait_timeout=0.4, cache_timeout=5, default=None) is None


def test_waits_then_captures():
    dev = FakeDev(FakeSrc([None, None, (100, "Sent")]))
    assert Toast(dev).get_message(wait_timeout=3, cache_timeout=10) == "Sent"


def test_default_when_no_toast():
    dev = FakeDev(FakeSrc([None]))
    assert Toast(dev).get_message(wait_timeout=0.3, default="none") == "none"
