"""TP1 체결 후 손절을 본전(entry)으로 이동 — 옵션, 기본 off."""
from quantpilot.backtest.engine import check_exits
from quantpilot.backtest.models import Position


def _pos():
    return Position(side="long", entry=100.0, contracts=10, stop=95.0,
                    targets_remaining=[(105.0, 0.3), (110.0, 0.3), (115.0, 0.4)],
                    opened_ts=0, original_contracts=10)


def test_be_trail_moves_stop_after_tp1():
    pos = _pos()
    bar = {"ts": 1, "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01, be_trail_after_tp1=True)
    assert any(f.reason == "tp1" for f in fills)
    assert pos2 is not None and pos2.stop == 100.0          # 본전 이동


def test_be_trail_default_off_keeps_stop():
    pos = _pos()
    bar = {"ts": 1, "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01)
    assert any(f.reason == "tp1" for f in fills)
    assert pos2.stop == 95.0                                 # 기존 거동(불변)


def test_be_trail_never_lowers_short_stop():
    pos = Position(side="short", entry=100.0, contracts=10, stop=105.0,
                   targets_remaining=[(95.0, 0.3), (90.0, 0.7)],
                   opened_ts=0, original_contracts=10)
    bar = {"ts": 1, "open": 100.0, "high": 101.0, "low": 94.0, "close": 94.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01, be_trail_after_tp1=True)
    assert any(f.reason == "tp1" for f in fills)
    assert pos2.stop == 100.0                                # 숏도 본전으로
