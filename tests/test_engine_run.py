import pandas as pd

from quantpilot.backtest.engine import run_backtest
from quantpilot.strategy.base import IStrategy, Signal


class _AlwaysLongOnceStrategy(IStrategy):
    """첫 진입 가능 시점에 long 1회, 이후 hold. 테스트용 결정적 전략."""
    name = "test-long"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("long", 1.0, price - 5.0, {})  # stop 5 아래
        return Signal("hold", 0.0, None, {})


def _candles(closes):
    tf = 3_600_000
    base = 1_700_000_000_000
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes, "volume": [1.0]*len(closes)},
        index=[base + i*tf for i in range(len(closes))],
    ).rename_axis("ts")


def test_run_backtest_produces_result_and_trades():
    # 진입 후 상승 → 타겟 도달로 익절(혹은 마지막 청산)
    closes = [100.0, 101, 102, 108, 115, 120]   # 상승 추세
    df = _candles(closes)
    result = run_backtest(
        candles=df, strategy=_AlwaysLongOnceStrategy(), capital=1000.0,
        ct_val=0.01, lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
        funding_events=[], oos_split_ts=df.index[4],
    )
    assert result.equity_curve  # 곡선 생성됨
    assert len(result.equity_curve) == len(df) - _AlwaysLongOnceStrategy().lookback
    # 거래가 최소 1건 발생(진입→청산)
    assert isinstance(result.trades, list)


def test_run_backtest_is_deterministic():
    closes = [100.0, 101, 99, 102, 98, 103, 97, 104]
    df = _candles(closes)
    kw = dict(capital=1000.0, ct_val=0.01, lot_sz=1.0, leverage=3,
              fee_bps=5, slippage_bps=2, funding_events=[], oos_split_ts=df.index[5])
    r1 = run_backtest(candles=df, strategy=_AlwaysLongOnceStrategy(), **kw)
    r2 = run_backtest(candles=df, strategy=_AlwaysLongOnceStrategy(), **kw)
    assert r1.equity_curve == r2.equity_curve
