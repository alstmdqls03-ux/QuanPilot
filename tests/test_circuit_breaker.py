from quantpilot.risk.circuit_breaker import should_halt, is_new_utc_day

DAY = 86_400_000  # ms


def test_should_halt_below_threshold():
    # 시작자본 1000, 하루 실현 -50(=-5%) → 정지
    assert should_halt(1000.0, -50.0) is True
    # -49.99(=-4.999%)는 아직 아님
    assert should_halt(1000.0, -49.99) is False
    # 이익 구간은 당연히 아님
    assert should_halt(1000.0, 30.0) is False


def test_should_halt_custom_threshold():
    assert should_halt(2000.0, -200.0, threshold=0.10) is True
    assert should_halt(2000.0, -199.0, threshold=0.10) is False


def test_is_new_utc_day():
    base = 1_700_000_000_000
    same_day = base + 3_600_000          # +1h
    next_day = (base // DAY + 1) * DAY    # 다음 UTC 자정
    assert is_new_utc_day(base, same_day) is False
    assert is_new_utc_day(base, next_day) is True
    assert is_new_utc_day(base, next_day + 5 * DAY) is True
