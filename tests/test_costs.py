from quantpilot.backtest.costs import apply_slippage, fee_for, funding_between


def test_slippage_worse_direction():
    # 매수 체결가는 위로(불리), 매도 체결가는 아래로(불리)
    assert apply_slippage(100.0, slippage_bps=10, side="buy") > 100.0
    assert apply_slippage(100.0, slippage_bps=10, side="sell") < 100.0


def test_fee_proportional_to_notional():
    # notional 1000, taker 5bps = 0.5
    assert abs(fee_for(notional=1000.0, fee_bps=5) - 0.5) < 1e-9


def test_funding_sums_events_in_window():
    # funding 이벤트 2개가 [open, close) 구간에 들어가면 둘 다 합산
    events = [(1000, 0.0001), (2000, -0.00005), (3000, 0.0002)]
    # 포지션 보유 [1500, 2500): 2000 이벤트만 포함
    paid = funding_between(events, notional=1000.0, side="long",
                           open_ts=1500, close_ts=2500)
    # long은 +funding이면 지불(+), -funding이면 수취(-)
    assert abs(paid - (1000.0 * -0.00005)) < 1e-9
