"""기술적 지표 — 직접 구현(순수 함수). 입력 pd.Series → 출력 pd.Series.

WHY 직접 구현: 전략의 edge가 지표 해석이라 수학을 소유해야 디버깅 가능.
외부 라이브러리(pandas-ta/ta-lib) 의존성·블랙박스를 피한다.
"""
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """지수이동평균. span=period 의 표준 EMA."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI. 0~100.

    WHY ewm(alpha=1/period): Wilder smoothing은 alpha=1/period 인 EMA와 동일.
    delta>0은 상승분(gain), delta<0은 하락분(loss). RS=avgGain/avgLoss.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    # avg_loss==0이면 rs=inf → rsi=100. pandas가 inf 처리.
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range. true range의 Wilder EMA.

    TR = max(high-low, |high-prev_close|, |low-prev_close|).
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()
