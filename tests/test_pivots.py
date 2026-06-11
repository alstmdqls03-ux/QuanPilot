"""ZigZag 확정 피벗 — 룩어헤드-프리가 핵심 검증."""
import pandas as pd
import pytest

from quantpilot.strategy.pivots import Pivot, confirmed_pivots

HOUR = 3_600_000
T0 = 1_780_000_000_000


def make_df(closes, spread=1.0):
    """종가 시퀀스로 결정적 OHLC 생성. high=close+spread, low=close-spread."""
    idx = [T0 + i * HOUR for i in range(len(closes))]
    return pd.DataFrame({
        "open": closes, "high": [c + spread for c in closes],
        "low": [c - spread for c in closes], "close": closes,
        "volume": [1.0] * len(closes)}, index=idx)


def wave_df():
    # 횡보(ATR 안정화) → 상승 100→130 → 하락 130→95 → 반등 95→115
    closes = ([100.0] * 20
              + [100 + 2 * i for i in range(1, 16)]      # ~130
              + [130 - 2.5 * i for i in range(1, 15)]    # ~95
              + [95 + 2 * i for i in range(1, 11)])      # ~115
    return make_df(closes)


def test_pivots_alternate_and_match_extremes():
    df = wave_df()
    pivots = confirmed_pivots(df, atr_k=3.0)
    assert len(pivots) >= 2
    kinds = [p.kind for p in pivots]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))   # H/L 교대
    first_h = next(p for p in pivots if p.kind == "H")
    assert first_h.price == pytest.approx(131.0, abs=1.5)   # 상승 최고 high 근처
    assert all(p.confirmed_ts > p.ts for p in pivots)       # 확정은 극점 이후


def test_pivots_lookahead_free():
    """prefix 데이터로 계산한 피벗 == 전체 계산 후 confirmed_ts<=cutoff 필터."""
    df = wave_df()
    full = confirmed_pivots(df, atr_k=3.0)
    for i in range(20, len(df) + 1, 5):
        part = confirmed_pivots(df.iloc[:i], atr_k=3.0)
        cutoff = df.index[i - 1]
        expected = [p for p in full if p.confirmed_ts <= cutoff]
        assert part == expected, f"prefix {i}봉에서 룩어헤드/누락 발생"


def test_pivots_too_short_returns_empty():
    assert confirmed_pivots(make_df([100.0] * 5)) == []
