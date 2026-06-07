from quantpilot.risk.take_profit import build_targets


def test_long_targets_above_entry():
    # entry 100, stop 95 → R=5. 1R/2R/3R = 105/110/115
    targets = build_targets(entry=100.0, stop=95.0, side="long",
                            r_multiples=[1, 2, 3], fractions=[0.33, 0.33, 0.34])
    prices = [p for p, _ in targets]
    assert prices == [105.0, 110.0, 115.0]
    assert abs(sum(f for _, f in targets) - 1.0) < 1e-9


def test_short_targets_below_entry():
    targets = build_targets(entry=100.0, stop=105.0, side="short",
                            r_multiples=[1, 2, 3], fractions=[0.33, 0.33, 0.34])
    prices = [p for p, _ in targets]
    assert prices == [95.0, 90.0, 85.0]
