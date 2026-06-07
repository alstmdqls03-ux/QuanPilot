import pandas as pd

from quantpilot.paper.store import PaperState
from quantpilot.strategy.base import IStrategy, Signal


class _LongOnceStrategy(IStrategy):
    name = "t-long"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("long", 1.0, price - 5.0, {})
        return Signal("hold", 0.0, None, {})


def _ctx(strategy):
    from quantpilot.paper.trader import TickContext
    return TickContext(
        session=None, client=None, symbol="BTC-USDT-SWAP", timeframe="1h",
        strategy=strategy, capital=1000.0, leverage=3, ct_val=0.01, lot_sz=1.0,
        fee_bps=5.0, slippage_bps=2.0, run_key="BTC-USDT-SWAP|1h|t-long")


def _state(capital=1000.0):
    return PaperState(run_key="BTC-USDT-SWAP|1h|t-long", symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy="t-long", equity=capital,
                      day_start_equity=capital, day_start_ts=0)


def _window(closes, ts):
    n = len(closes)
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes},
        index=[ts - (n - 1 - i) * 3_600_000 for i in range(n)]).rename_axis("ts")


def test_process_bar_opens_position():
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    ts = 1_700_007_200_000
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is not None and st.position.side == "long"
    assert st.position.contracts > 0
    assert st.open_fee > 0 and st.equity < 1000.0  # 진입 수수료 차감
    assert trades == []
    assert st.last_processed_bar_ts == ts
