"""open_position의 명시적 타깃 주입 — 기본 경로(주입 없음)는 기존과 동일해야 함."""
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
