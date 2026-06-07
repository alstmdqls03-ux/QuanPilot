import pytest

from quantpilot.risk.liquidation import (
    liquidation_price, assert_stop_within_liquidation, StopBeyondLiquidationError,
)


def test_liq_long_below_entry():
    liq = liquidation_price(entry=100.0, leverage=5, side="long", mmr=0.005)
    assert liq < 100.0
    assert abs(liq - 100.0 * (1 - 1/5 + 0.005)) < 1e-9


def test_liq_short_above_entry():
    liq = liquidation_price(entry=100.0, leverage=5, side="short", mmr=0.005)
    assert liq > 100.0


def test_stop_within_liq_ok():
    # 5x long: liq ≈ 80.5, 안전구역 70% = entry-13.7 ≈ 86.3. stop=95는 OK.
    assert_stop_within_liquidation(entry=100.0, stop=95.0, leverage=5, side="long")


def test_stop_beyond_liq_raises():
    # stop을 청산보다 멀게(75) 두면 거부
    with pytest.raises(StopBeyondLiquidationError):
        assert_stop_within_liquidation(entry=100.0, stop=75.0, leverage=5, side="long")


def test_stop_within_liq_ok_short():
    # 5x short: liq ≈ 119.5, 안전구역 안. stop=105는 OK.
    assert_stop_within_liquidation(entry=100.0, stop=105.0, leverage=5, side="short")


def test_stop_beyond_liq_raises_short():
    # 숏 stop을 청산보다 멀게(125) 두면 거부
    with pytest.raises(StopBeyondLiquidationError):
        assert_stop_within_liquidation(entry=100.0, stop=125.0, leverage=5, side="short")
