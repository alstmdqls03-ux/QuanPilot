from quantpilot.backtest.models import Position, Fill, Trade


def test_position_fields():
    p = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                 targets_remaining=[(105.0, 0.5), (110.0, 0.5)], opened_ts=1)
    assert p.contracts == 10
    assert p.targets_remaining[0] == (105.0, 0.5)


def test_fill_and_trade():
    f = Fill(ts=2, price=105.0, contracts=5, fee=0.26, reason="tp1", pnl_gross=25.0)
    assert f.reason == "tp1"
    t = Trade(side="long", entry=100.0, exit=105.0, contracts=10,
              pnl_gross=50.0, fees=0.5, funding=0.1, pnl_net=49.4,
              opened_ts=1, closed_ts=3, reason="tp")
    assert t.pnl_net == 49.4
