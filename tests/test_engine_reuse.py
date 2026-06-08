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


def test_build_trade_weighted_average_exit():
    """복수 fill의 가중평균 exit 가격 계산 검증.

    WHY 이 테스트: build_trade가 avg_exit = Σ(price×contracts)/Σcontracts 공식을
    올바르게 적용하는지 확인. 분할 익절 시나리오에서 fill 가격이 다르면
    단순 평균(모든 fill price 합/개수)을 쓰면 오답이 됨.

    fill1: price=105, contracts=4 → 가중치 420
    fill2: price=95,  contracts=6 → 가중치 570
    avg_exit = (420+570)/(4+6) = 990/10 = 99.0  (단순평균 100이 아님)
    """
    from quantpilot.backtest.engine import build_trade
    pos = Position(side="long", entry=100.0, contracts=10, stop=90.0,
                   targets_remaining=[], opened_ts=1, original_contracts=10)
    fill1 = Fill(ts=2, price=105.0, contracts=4, fee=0.5, reason="tp1", pnl_gross=20.0)
    fill2 = Fill(ts=3, price=95.0, contracts=6, fee=0.7, reason="stop", pnl_gross=-30.0)
    t = build_trade(pos, [fill1, fill2], 3, funding=0.0, open_fee=0.3)
    # 가중평균: (105×4 + 95×6) / (4+6) = (420+570)/10 = 99.0
    expected_avg_exit = (105.0 * 4 + 95.0 * 6) / (4 + 6)
    assert abs(t.exit - expected_avg_exit) < 1e-9, (
        f"avg_exit {t.exit} != {expected_avg_exit} (가중평균 공식 오류)")
    # gross/fees/pnl_net 집계도 올바른지
    assert abs(t.pnl_gross - (20.0 - 30.0)) < 1e-9
    assert abs(t.fees - (0.3 + 0.5 + 0.7)) < 1e-9
    assert abs(t.pnl_net - (t.pnl_gross - t.fees - 0.0)) < 1e-9
