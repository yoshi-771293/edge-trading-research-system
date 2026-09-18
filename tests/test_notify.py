from live import notify


def test_header_values_are_ascii_safe():
    assert notify.ascii_header("✅ Edge Tournament live") == "Edge Tournament live"
    assert notify.ascii_header("Drawdown -25% — halted") == "Drawdown -25% - halted"
    assert notify.ascii_header("plain").isascii()
