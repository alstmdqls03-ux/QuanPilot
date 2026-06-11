"""open_position의 명시적 타깃 주입 — 기본 경로(주입 없음)는 기존과 동일해야 함."""
import pytest

from quantpilot.backtest.engine import open_position
from quantpilot.risk.take_profit import build_targets

BAR = {"ts": 1_780_000_000_000, "open": 100.0, "high": 101.0,
       "low": 99.0, "close": 100.0}


def test_default_targets_unchanged():           # 회귀: rsi-mr 경로
    pos, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0)
    assert pos is not None
    assert pos.targets_remaining == build_targets(pos.entry, 95.0, "long")


def test_explicit_targets_used():
    custom = [(103.0, 0.5), (108.0, 0.4)]       # 50/40, 잔여 10%는 러너
    pos, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                           targets=custom)
    assert pos.targets_remaining == custom


def test_injected_list_targets_normalized_to_tuples():
    """JSON 역직렬화 경로: list로 주입된 타깃이 tuple로 정규화되는지 확인.

    WHY: check_exits의 remaining.remove((price,frac))는 tuple만 매치 —
    list로 들어오면 첫 TP 체결에서 ValueError → 페이퍼 루프 livelock.
    """
    pos, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                           targets=[[103.0, 0.5], [108.0, 0.4]])   # list로 주입
    assert pos is not None
    assert pos.targets_remaining == [(103.0, 0.5), (108.0, 0.4)]   # tuple로 정규화


def test_injected_wrong_direction_target_rejected():
    """롱인데 entry(~100)보다 낮은 타깃은 이익 방향이 아니므로 진입 전 거부."""
    with pytest.raises(AssertionError):
        open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                      targets=[(97.0, 0.5)])                        # 롱인데 entry 아래


def test_injected_frac_sum_above_one_rejected():
    """타깃 비중 합이 1 초과 — 총 청산 수량이 원 계약을 넘어 과청산 위험."""
    with pytest.raises(AssertionError):
        open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                      targets=[(103.0, 0.6), (108.0, 0.6)])         # 합 1.2


def test_injected_frac_zero_rejected():
    """frac≤0인 타깃은 아무것도 청산 안 하고 remaining만 잠식."""
    with pytest.raises(AssertionError):
        open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                      targets=[(103.0, 0.0)])
