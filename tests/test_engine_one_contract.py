"""1계약 포지션에서도 TP 사다리가 동작(마지막 타깃 잔량 흡수) — TODOS Codex #7."""
from quantpilot.backtest.engine import check_exits
from quantpilot.backtest.models import Position


def test_one_contract_fills_at_last_target():
    """1계약에서 0.5/0.4 round → 0이라 TP가 침묵하던 버그 수정 확인.

    WHY: 마지막 타깃이 잔량 전부를 흡수해야 소액 계좌에서도 사다리가 동작.
    """
    pos = Position(side="long", entry=100.0, contracts=1, stop=95.0,
                   targets_remaining=[(103.0, 0.5), (108.0, 0.4)],
                   opened_ts=0, original_contracts=1)
    bar = {"ts": 1, "open": 100.0, "high": 109.0, "low": 99.0, "close": 108.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01)
    assert fills and sum(f.contracts for f in fills) == 1   # 사다리 어딘가에서 전량 체결
    assert pos2 is None                                      # 포지션 종료


def test_one_contract_103_skipped_108_absorbs_all():
    """1계약: 103 히트봉에서 round(1×0.5)=0(banker rounding) → 103 스킵, 108이 remaining[-1]로
    잔량 흡수 → 108 히트봉에서 전량 체결.

    WHY: Python banker's rounding에서 round(0.5)=0이라 첫 타깃이 qty=0이 됨.
    remaining.remove 후 108이 remaining[-1]이 되고, 108 봉에서 contracts_left=1 전부 흡수.
    """
    pos = Position(side="long", entry=100.0, contracts=1, stop=95.0,
                   targets_remaining=[(103.0, 0.5), (108.0, 0.4)],
                   opened_ts=0, original_contracts=1)
    # 봉1: 103 닿음, 108 미달 → qty=round(1*0.5)=0 → 체결 없음, 103만 remaining에서 제거
    bar1 = {"ts": 1, "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.5}
    pos2, fills1 = check_exits(pos, bar1, 5.0, 0.0, 0.01)
    assert not fills1                               # 봉1: 체결 없음(qty=0 스킵)
    assert pos2 is not None                         # 포지션 유지
    assert pos2.targets_remaining == [(103.0, 0.5), (108.0, 0.4)]  # remaining 그대로(qty=0이면 remove 안 됨)

    # 봉2: 108 닿음 → 108이 remaining[-1], qty=contracts_left=1 흡수 → 전량 체결
    bar2 = {"ts": 2, "open": 104.0, "high": 109.0, "low": 103.0, "close": 108.5}
    pos3, fills2 = check_exits(pos2, bar2, 5.0, 0.0, 0.01)
    assert fills2
    assert sum(f.contracts for f in fills2) == 1
    assert pos3 is None                             # 포지션 종료


def test_two_contract_ladder_intact():
    """2계약에선 기존 동작 유지 — 마지막 타깃 흡수가 일반 케이스를 깨지 않는지 회귀."""
    pos = Position(side="long", entry=100.0, contracts=2, stop=95.0,
                   targets_remaining=[(103.0, 0.5), (108.0, 0.5)],
                   opened_ts=0, original_contracts=2)
    bar = {"ts": 1, "open": 100.0, "high": 109.0, "low": 99.0, "close": 108.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01)
    assert pos2 is None
    assert sum(f.contracts for f in fills) == 2
