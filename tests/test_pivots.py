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
    # 거대 봉은 극점 설정+확정이 같은 봉에서 가능(confirmed_ts == ts) — 룩어헤드 아님(봉마감 시 그 봉 high/low는 기지).
    assert all(p.confirmed_ts >= p.ts for p in pivots)


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


# ---------------------------------------------------------------------------
# [M-3] 신규 테스트: 각각 리뷰 수정 항목을 핀
# ---------------------------------------------------------------------------

def test_pivots_flat_data_no_flood():
    """완전 횡보(high==low==close, ATR=0) → 피벗 0개 (thr=0 폭주 방지).

    WHY: ATR=0인 봉에서 thr=0이면 hi_px-close>=0이 항상 참이 되어 매 봉 피벗 폭주.
    [I-1] thr>0 게이트가 이를 막아야 한다.
    """
    df = make_df([100.0] * 40, spread=0.0)
    assert confirmed_pivots(df) == []


def test_pivots_blind_window_wick_captured():
    """H 극점 후 확정 전의 깊은 wick이 다음 L 후보로 이어져야 함.

    WHY: 현재 구현은 H 확정 시 lo_px를 확정봉 low로 리셋하는데,
    극점봉(hi_ts)과 확정봉 사이에 더 깊은 low가 있으면 버려진다.
    [I-2] 블라인드 윈도우 최소 low 추적으로 이를 수정해야 한다.
    """
    closes = [100.0] * 20 + [104.0, 108.0, 112.0, 111.0, 99.0] + [100.0, 101.0] \
             + [104.0 + 2.0 * i for i in range(1, 8)]
    df = make_df(closes)
    # b23(close 111)의 low를 95로 깊게 (wick — 종가론 확정 안 됨)
    df.iloc[23, df.columns.get_loc("low")] = 95.0
    pivots = confirmed_pivots(df, atr_k=3.0)
    lows = [p for p in pivots if p.kind == "L" and p.ts >= df.index[20]]
    assert lows, "L 피벗이 있어야 함"
    assert lows[0].price == 95.0, "블라인드 윈도우의 깊은 wick(95)이 L 피벗이어야 함"


def test_pivots_giant_bar_same_ts_confirm():
    """거대 음봉: H 설정+확정이 같은 봉 — confirmed_ts == ts 허용.

    WHY: 거대 봉은 극점 설정+확정이 같은 봉에서 가능(confirmed_ts == ts).
    봉마감 시 그 봉 high/low는 기지값이므로 룩어헤드 아님.
    [I-3] assert >=로 완화해야 한다.
    """
    closes = [100.0] * 20 + [81.0] + [82.0, 83.0] + [90.0 + 3.0 * i for i in range(1, 6)]
    df = make_df(closes)
    df.iloc[20, df.columns.get_loc("high")] = 130.0
    df.iloc[20, df.columns.get_loc("low")] = 80.0
    pivots = confirmed_pivots(df, atr_k=3.0)
    h = next(p for p in pivots if p.kind == "H")
    assert h.price == 130.0 and h.confirmed_ts >= h.ts


def test_pivots_downtrend_first_pivot_is_high():
    """하락으로 시작하면 첫 피벗은 시작 고점 H."""
    closes = [100.0] * 20 + [100.0 - 2.5 * i for i in range(1, 15)]
    df = make_df(closes)
    pivots = confirmed_pivots(df, atr_k=3.0)
    assert pivots and pivots[0].kind == "H"
