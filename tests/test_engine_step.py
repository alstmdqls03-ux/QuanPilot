from quantpilot.backtest.engine import check_exits
from quantpilot.backtest.models import Position


def _bar(ts, high, low, close):
    return {"ts": ts, "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


def test_stop_hit_closes_long():
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(110.0, 1.0)], opened_ts=1)
    # 봉 low가 stop 아래로 → 손절 체결
    new_pos, fills = check_exits(pos, _bar(2, high=101, low=94, close=96),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is None
    assert len(fills) == 1 and fills[0].reason == "stop"


def test_stop_first_when_bar_straddles_both():
    # 한 봉이 stop(95)과 target(110)을 동시에 건드림 → 보수적으로 stop 먼저
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(110.0, 1.0)], opened_ts=1)
    new_pos, fills = check_exits(pos, _bar(2, high=111, low=94, close=100),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is None
    assert fills[0].reason == "stop"   # TP가 아니라 stop


def test_partial_tp_reduces_contracts():
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(105.0, 0.5), (110.0, 0.5)], opened_ts=1)
    # 봉 high가 105 닿음(110은 안 닿음), stop 안 닿음 → 50%만 익절
    new_pos, fills = check_exits(pos, _bar(2, high=106, low=99, close=104),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is not None
    assert new_pos.contracts == 5           # 절반 청산
    assert len(new_pos.targets_remaining) == 1
    assert fills[0].reason == "tp1"


def test_no_exit_when_bar_inside_range():
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(110.0, 1.0)], opened_ts=1)
    new_pos, fills = check_exits(pos, _bar(2, high=101, low=99, close=100),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is pos and fills == []


def test_stop_hit_closes_short():
    # 숏 손절: 봉 high가 stop(105) 위로 → 전액 청산
    pos = Position(side="short", entry=100.0, contracts=10, stop=105.0,
                   targets_remaining=[(90.0, 1.0)], opened_ts=1)
    new_pos, fills = check_exits(pos, _bar(2, high=106, low=99, close=104),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is None
    assert len(fills) == 1 and fills[0].reason == "stop"


def test_partial_tp_reduces_contracts_short():
    # 숏 분할익절: 봉 low가 첫 타겟(95) 아래 닿음(90은 미도달), stop 미발동 → 50%만 익절
    pos = Position(side="short", entry=100.0, contracts=10, stop=105.0,
                   targets_remaining=[(95.0, 0.5), (90.0, 0.5)], opened_ts=1)
    new_pos, fills = check_exits(pos, _bar(2, high=101, low=94, close=96),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is not None
    assert new_pos.contracts == 5
    assert len(new_pos.targets_remaining) == 1
    assert fills[0].reason == "tp1"
