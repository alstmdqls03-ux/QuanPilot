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


class _LongThenExitStrategy(IStrategy):
    """1회 long 진입 후, 보유 중이면 exit 신호. exit_signal 경로 검증용."""
    name = "test-exit"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._step = 0

    def generate_signal(self, window, open_position):
        self._step += 1
        if open_position is None and self._step == 1:
            return Signal("long", 1.0, float(window["close"].iloc[-1]) - 5.0, {})
        if open_position is not None:
            return Signal("exit", 0.0, None, {})
        return Signal("hold", 0.0, None, {})


class _ShortOnceStrategy(IStrategy):
    """첫 진입 가능 시점에 short 1회, 이후 hold. 숏 경로 검증용."""
    name = "test-short"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("short", 1.0, price + 5.0, {})  # stop 위
        return Signal("hold", 0.0, None, {})


def _ohlc(rows):
    # rows: [(open, high, low, close), ...] → ts 인덱스 DataFrame
    tf = 3_600_000
    base = 1_700_000_000_000
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows],
         "volume": [1.0] * len(rows)},
        index=[base + i * tf for i in range(len(rows))],
    ).rename_axis("ts")


def test_partial_tp_realized_into_equity_curve():
    # 회귀: 부분익절 실현손익이 그 봉의 equity 곡선에 즉시 반영돼야 한다.
    # (예전 버그: 청산까지 미뤄져 곡선이 가짜로 하락 → Sharpe/MaxDD 왜곡.)
    # bar0,1 warmup. bar2 진입(close 100, stop 95). bar3 high가 tp1(105) 도달, stop 미발동.
    df = _ohlc([(100, 100, 100, 100), (100, 100, 100, 100),
                (100, 100, 100, 100), (100, 106, 99, 100)])
    r = run_backtest(
        candles=df, strategy=_AlwaysLongOnceStrategy(), capital=10000.0,
        ct_val=1.0, lot_sz=1.0, leverage=10, fee_bps=0, slippage_bps=0,
        funding_events=[], oos_split_ts=df.index[3],
    )
    entry_eq = r.equity_curve[0][1]   # 진입봉
    tp1_eq = r.equity_curve[1][1]     # tp1 봉
    # 100계약 진입, tp1에서 round(100*0.33)=33계약 ×(105-100)=165 실현 → 곡선 상승
    assert tp1_eq > entry_eq, "부분익절 봉에서 곡선이 상승해야 함(실현익 즉시 반영)"
    assert abs(tp1_eq - (10000.0 + 165.0)) < 1e-6


def test_equity_curve_conservation_on_full_close():
    # 포지션이 전액 청산되면 최종 equity == 자본 + 모든 거래 pnl_net (실현 일치).
    df = _ohlc([(100, 100, 100, 100), (100, 100, 100, 100),
                (100, 100, 100, 100), (100, 100, 89, 90)])  # bar3 손절
    r = run_backtest(
        candles=df, strategy=_AlwaysLongOnceStrategy(), capital=10000.0,
        ct_val=1.0, lot_sz=1.0, leverage=10, fee_bps=0, slippage_bps=0,
        funding_events=[], oos_split_ts=df.index[3],
    )
    assert r.trades, "손절로 1건 청산되어야 함"
    final_eq = r.equity_curve[-1][1]
    assert abs(final_eq - (10000.0 + sum(t.pnl_net for t in r.trades))) < 1e-6


def test_run_backtest_deducts_funding():
    # 보유 구간 내 funding 이벤트가 거래 funding에 반영돼야 한다.
    df = _candles([100.0, 100, 100, 90])  # 진입 후 급락 → 손절 전액 청산
    fund = [(int(df.index[2]) + 1, 0.001)]  # 진입 직후(보유 구간 [open, close) 내)
    r = run_backtest(
        candles=df, strategy=_AlwaysLongOnceStrategy(), capital=1000.0,
        ct_val=0.01, lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
        funding_events=fund, oos_split_ts=df.index[3],
    )
    assert r.trades
    assert any(t.funding != 0.0 for t in r.trades)


def test_run_backtest_exit_signal_closes():
    df = _candles([100.0, 101, 102, 103, 104, 105])  # 완만 상승, stop/tp 미발동
    r = run_backtest(
        candles=df, strategy=_LongThenExitStrategy(), capital=1000.0,
        ct_val=0.01, lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
        funding_events=[], oos_split_ts=df.index[4],
    )
    assert any(t.reason == "exit_signal" for t in r.trades)


def test_run_backtest_short_position():
    df = _candles([100.0, 99, 98, 92, 85, 80])  # 하락 추세 → 숏 경로
    r = run_backtest(
        candles=df, strategy=_ShortOnceStrategy(), capital=1000.0,
        ct_val=0.01, lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
        funding_events=[], oos_split_ts=df.index[4],
    )
    assert r.equity_curve
    assert all(t.side == "short" for t in r.trades)


def test_stop_loss_with_slippage_stays_within_risk_budget():
    # 안전 e2e: 슬리피지 큰 손절도 실현 손실이 5% 예산을 (반올림 여유 내) 넘지 않아야.
    # 슬리피지를 사이징에서 빼면 이 한도를 초과한다(Codex #1 회귀).
    df = _ohlc([(100, 100, 100, 100), (100, 100, 100, 100),
                (100, 100, 100, 100), (100, 100, 89, 90)])  # bar3 손절
    r = run_backtest(
        candles=df, strategy=_AlwaysLongOnceStrategy(), capital=1000.0,
        ct_val=0.01, lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=20,
        funding_events=[], oos_split_ts=df.index[3],
    )
    assert r.trades, "손절로 1건 청산되어야 함"
    realized_loss = 1000.0 - r.equity_curve[-1][1]
    assert realized_loss <= 1000.0 * 0.05 * 1.02  # 5% 예산 + 정수계약 여유
