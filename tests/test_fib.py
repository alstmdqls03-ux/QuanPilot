from quantpilot.strategy.fib import fib_levels, in_entry_zone, last_wave
from quantpilot.strategy.pivots import Pivot

T0 = 1_780_000_000_000
H = 3_600_000


def test_fib_levels_down_wave():
    # 하락 파동 H(100) → L(50): 되돌림은 위로. 0.5=75, 0.618=80.9
    lv = fib_levels(start=100.0, end=50.0)
    assert lv[0.5] == 75.0
    assert round(lv[0.618], 1) == 80.9
    assert round(lv[0.382], 1) == 69.1


def test_fib_levels_up_wave():
    lv = fib_levels(start=50.0, end=100.0)     # 상승 파동 → 아래로 되돌림
    assert lv[0.5] == 75.0
    assert round(lv[0.618], 1) == 69.1


def test_last_wave_uses_last_two_confirmed():
    piv = [Pivot(T0, 100.0, "H", T0 + 2 * H), Pivot(T0 + 5 * H, 50.0, "L", T0 + 7 * H)]
    w = last_wave(piv, now_ts=T0 + 7 * H)
    assert w == (100.0, 50.0)
    assert last_wave(piv, now_ts=T0 + 6 * H) is None   # L 미확정 시점 → 파동 없음
    assert last_wave([piv[0]], now_ts=T0 + 9 * H) is None


def test_in_entry_zone():
    lv = fib_levels(100.0, 50.0)               # 0.5=75, 0.618=80.9
    assert in_entry_zone(76.0, lv)
    assert in_entry_zone(80.0, lv)
    assert not in_entry_zone(85.0, lv)
    assert not in_entry_zone(70.0, lv)
