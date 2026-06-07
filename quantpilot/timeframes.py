"""Timeframe 문자열 ↔ 밀리초 변환.

WHY 별도 모듈: collector·status·테스트 여러 곳에서 쓰는 순수 로직.
한 곳에 모아 두면 봉 길이 계산 버그를 한 군데서만 잡으면 됨.
"""

# Week 1이 지원하는 timeframe만. YAGNI — 5m/1m은 계획 없으니 제외.
_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
}
SUPPORTED_TIMEFRAMES = frozenset(_MS.keys())


def timeframe_to_ms(timeframe: str) -> int:
    """'1h' → 3_600_000. 지원 안 하는 값이면 ValueError(사람 실수, 즉시 중단)."""
    try:
        return _MS[timeframe]
    except KeyError:
        raise ValueError(
            f"지원하지 않는 timeframe '{timeframe}'. "
            f"사용 가능: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}"
        )
