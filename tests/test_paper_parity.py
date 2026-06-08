"""백테스트 == 페이퍼 parity 테스트(crown jewel).

WHY 이 테스트: 동일한 봉 시퀀스를 ①run_backtest 통째 ②process_bar 봉마다 실행해
거래와 최종 equity가 일치하는지 강제한다. 두 경로가 달라지면 페이퍼 결과를 신뢰할 수 없음.
"""
import pandas as pd

from quantpilot.backtest.engine import run_backtest
from quantpilot.paper.store import PaperState, make_run_key
from quantpilot.paper.trader import TickContext, process_bar
from quantpilot.strategy.base import IStrategy, Signal


class _LongOnce(IStrategy):
    name = "p-long"

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


def _candles(closes):
    tf = 3_600_000
    base = 1_700_000_000_000
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes,
         "volume": [1.0] * len(closes)},
        index=[base + i * tf for i in range(len(closes))]).rename_axis("ts")


def test_paper_matches_backtest():
    # 동일 봉 시퀀스를 ①run_backtest 통째 ②process_bar 봉마다 → 거래·최종 equity 일치
    closes = [100.0, 100, 100, 90]   # 진입 후 급락 → 손절(끝에 flat)
    df = _candles(closes)
    bt = run_backtest(candles=df, strategy=_LongOnce(), capital=1000.0, ct_val=0.01,
                      lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
                      funding_events=[], oos_split_ts=df.index[-1])

    rk = make_run_key("BTC-USDT-SWAP", "1h", "p-long")
    ctx = TickContext(session=None, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_LongOnce(), capital=1000.0,
                      leverage=3, ct_val=0.01, lot_sz=1.0, fee_bps=5, slippage_bps=2,
                      run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="p-long", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    lookback = ctx.strategy.lookback  # 엔진과 동일 시작 인덱스 보장(하드코딩 시 어긋날 위험)
    paper_trades = []
    for i in range(lookback, len(df)):
        t = int(df.index[i])
        window = df.iloc[i - lookback + 1: i + 1]
        bar = {"ts": t, "open": float(df.at[t, "open"]), "high": float(df.at[t, "high"]),
               "low": float(df.at[t, "low"]), "close": float(df.at[t, "close"])}
        st, trades = process_bar(ctx, st, bar, window, funding_events=[])
        paper_trades.extend(trades)

    # 거래 일치(side/entry/exit/reason/pnl_net)
    def key(t):
        return (t.side, round(t.entry, 6), round(t.exit, 6), t.reason,
                round(t.pnl_net, 6))
    assert [key(t) for t in paper_trades] == [key(t) for t in bt.trades]
    # 최종 실현 equity 일치 (끝에 flat이므로 곡선 마지막 = 실현)
    assert abs(st.equity - bt.equity_curve[-1][1]) < 1e-6
