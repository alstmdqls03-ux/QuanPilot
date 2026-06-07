import pytest

from quantpilot.risk.sizing import (
    calculate_position_size, SizingResult, InsufficientCapitalError,
)


def test_basic_sizing_respects_5pct_invariant():
    r = calculate_position_size(
        capital=1000.0, risk_pct=0.05, entry=100.0, stop=95.0,
        ct_val=0.01, lot_sz=1.0, leverage=3,
    )
    assert isinstance(r, SizingResult)
    # max_loss + fee ≤ capital × 5% × 1.02
    assert r.max_loss_usd <= 1000.0 * 0.05 * 1.02 + 1e-6
    assert r.contracts > 0


def test_sizing_invariant_fuzz_multi_symbol():
    # ctVal 다른 심볼 + 다양한 stop 거리에서도 invariant 유지
    import random
    rng = random.Random(42)
    for _ in range(1000):
        ct_val = rng.choice([0.01, 0.1, 1.0, 10.0])
        entry = rng.uniform(1.0, 50000.0)
        stop = entry * (1 - rng.uniform(0.005, 0.15))
        cap = rng.uniform(200.0, 5000.0)
        try:
            r = calculate_position_size(cap, 0.05, entry, stop, ct_val, 1.0, leverage=3)
        except InsufficientCapitalError:
            continue
        assert r.max_loss_usd <= cap * 0.05 * 1.02 + 1e-6


def test_insufficient_capital_raises():
    # 자본이 너무 작아 1계약도 못 사면 에러
    with pytest.raises(InsufficientCapitalError):
        calculate_position_size(
            capital=1.0, risk_pct=0.05, entry=50000.0, stop=49000.0,
            ct_val=1.0, lot_sz=1.0, leverage=3,
        )
