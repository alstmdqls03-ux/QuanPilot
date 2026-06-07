import pandas as pd

from quantpilot.strategy.rsi_mean_reversion import RsiMeanReversion
from quantpilot.backtest.models import Position


def _window(closes):
    n = len(closes)
    return pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": [1.0] * n,
    })


def test_long_signal_on_oversold():
    s = RsiMeanReversion(timeframe="1h")
    closes = [float(x) for x in range(60, 1, -1)]  # 급락 → RSI 낮음
    sig = s.generate_signal(_window(closes), open_position=None)
    assert sig.side == "long"
    assert sig.suggested_stop is not None and sig.suggested_stop < closes[-1]


def test_short_signal_on_overbought():
    s = RsiMeanReversion(timeframe="1h")
    closes = [float(x) for x in range(1, 60)]  # 급등 → RSI 높음
    sig = s.generate_signal(_window(closes), open_position=None)
    assert sig.side == "short"
    assert sig.suggested_stop is not None and sig.suggested_stop > closes[-1]


def test_exit_when_rsi_neutral_and_position_open():
    s = RsiMeanReversion(timeframe="1h", exit_band=(45.0, 55.0))
    # 횡보 → RSI ~50
    closes = [10.0, 10.1, 9.9, 10.05, 9.95] * 12
    pos = Position(side="long", entry=10.0, contracts=5, stop=9.5,
                   targets_remaining=[], opened_ts=1)
    sig = s.generate_signal(_window(closes), open_position=pos)
    assert sig.side in ("exit", "hold")


def test_lookback_is_set():
    assert RsiMeanReversion(timeframe="1h").lookback >= 30
