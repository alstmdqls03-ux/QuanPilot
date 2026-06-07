import pandas as pd

from quantpilot.strategy.indicators import rsi, atr, ema


def test_ema_matches_pandas_ewm():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = ema(s, period=3)
    expected = s.ewm(span=3, adjust=False).mean()
    assert (out - expected).abs().max() < 1e-9


def test_rsi_all_gains_approaches_100():
    # 단조 상승 → 손실 0 → RSI가 100에 수렴
    close = pd.Series([float(i) for i in range(1, 60)])
    r = rsi(close, period=14)
    assert r.iloc[-1] > 99.0


def test_rsi_all_losses_approaches_0():
    close = pd.Series([float(i) for i in range(60, 1, -1)])
    r = rsi(close, period=14)
    assert r.iloc[-1] < 1.0


def test_rsi_in_range():
    close = pd.Series([10, 11, 10.5, 11.2, 10.8, 11.5, 11.1, 10.9, 11.3, 11.0,
                       10.7, 11.4, 11.2, 10.6, 11.1, 11.3])
    r = rsi(close, period=14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_atr_positive_and_tracks_range():
    high = pd.Series([10.0, 11, 12, 11, 13])
    low = pd.Series([9.0, 10, 11, 10, 11])
    close = pd.Series([9.5, 10.5, 11.5, 10.5, 12])
    a = atr(high, low, close, period=3)
    assert (a.dropna() > 0).all()
