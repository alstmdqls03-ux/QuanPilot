import pytest

from quantpilot.timeframes import timeframe_to_ms, SUPPORTED_TIMEFRAMES


def test_known_timeframes():
    assert timeframe_to_ms("1h") == 3_600_000
    assert timeframe_to_ms("15m") == 900_000


def test_supported_set():
    assert "1h" in SUPPORTED_TIMEFRAMES
    assert "15m" in SUPPORTED_TIMEFRAMES


def test_unknown_timeframe_raises():
    with pytest.raises(ValueError) as e:
        timeframe_to_ms("7m")
    assert "7m" in str(e.value)
