"""meta['risk_mult']로 per-trade 리스크 축소(0.5=2.5%). 기본 1.0 → 기존 불변."""
import pytest

from quantpilot.backtest.engine import open_position

BAR = {"ts": 1_780_000_000_000, "open": 100.0, "high": 101.0,
       "low": 99.0, "close": 100.0}


def test_risk_mult_halves_contracts():
    full, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0)
    half, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                            risk_mult=0.5)
    assert full is not None and half is not None
    assert half.contracts <= full.contracts // 2 + 1
    assert half.contracts < full.contracts


def test_risk_mult_default_is_identity():
    a, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0)
    b, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                         risk_mult=1.0)
    assert a.contracts == b.contracts


def test_risk_mult_above_one_rejected():
    """risk_mult>1은 per-trade 5% 캡을 조용히 뚫으므로 진입 전에 assert로 차단."""
    with pytest.raises(AssertionError):
        open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                      risk_mult=2.0)


def test_risk_mult_zero_rejected():
    """risk_mult≤0은 0계약(베팅 없음) 또는 음수 사이징을 유발하므로 차단."""
    with pytest.raises(AssertionError):
        open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                      risk_mult=0.0)
