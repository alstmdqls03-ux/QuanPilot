# tests/test_engine_reuse.py
from quantpilot.backtest.models import Fill, Position


def test_open_position_is_public():
    from quantpilot.backtest.engine import open_position
    bar = {"close": 100.0, "ts": 1_700_000_000_000}
    pos, fee = open_position("long", bar, 95.0, 1000.0, 0.01, 1.0, 3, 5.0, 2.0)
    assert pos is not None
    assert pos.side == "long" and pos.contracts > 0 and fee > 0
    # 진입가 = 종가에 매수 슬리피지(2bps) 반영: 100 × (1 + 2/10000) = 100.02
    assert abs(pos.entry - 100.02) < 1e-9


def test_close_fill_is_public():
    from quantpilot.backtest.engine import close_fill
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[], opened_ts=1, original_contracts=10)
    f = close_fill(pos, 105.0, 10, 2, "exit_signal", 5.0, 0.0, 0.01)
    assert f.reason == "exit_signal" and f.contracts == 10
    # 슬리피지 0 → pnl_gross = (105-100)×10×0.01 = 0.5, fee = 10×105×0.01 × 5bps = 0.00525
    assert abs(f.pnl_gross - 0.5) < 1e-9 and abs(f.fee - 0.00525) < 1e-9


def test_build_trade_is_public_and_aggregates():
    from quantpilot.backtest.engine import build_trade
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[], opened_ts=1, original_contracts=10)
    fills = [Fill(ts=2, price=105.0, contracts=10, fee=1.0, reason="tp1", pnl_gross=50.0)]
    t = build_trade(pos, fills, 2, funding=0.0, open_fee=0.5)
    assert t.exit == 105.0 and t.contracts == 10 and t.pnl_gross == 50.0
    assert abs(t.fees - 1.5) < 1e-9 and abs(t.pnl_net - 48.5) < 1e-9
