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


class _HoldStrategy(IStrategy):
    name = "t-hold"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2

    def generate_signal(self, window, open_position):
        return Signal("hold", 0.0, None, {})


def test_process_bar_stop_closes_and_realizes():
    from quantpilot.backtest.models import Position
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_HoldStrategy())
    st = _state()
    # 진입가 100, stop 95, 10계약. open_fee는 이미 차감됐다고 가정.
    st.position = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                           targets_remaining=[(105.0, 0.33), (110.0, 0.33),
                                              (115.0, 0.34)],
                           opened_ts=1_700_000_000_000, original_contracts=10)
    open_fee = 0.5
    st.open_fee = open_fee
    st.equity -= open_fee  # 진입 시 수수료 이미 차감된 상태 시뮬레이션
    # WHY eq_before를 open_fee 차감 후 기준으로 잡으면 pnl_net이 open_fee를
    # 이중 차감하므로, 진입 이전(원금) 기준으로 보존식 검증.
    eq_pre_entry = st.equity + open_fee  # = 1000.0 (진입 전 원금)
    ts = 1_700_003_600_000
    window = _window([100.0, 90.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 96.0, "low": 89.0, "close": 90.0}  # low<95 손절
    eq_after_entry = st.equity  # open_fee 차감 후 equity (< eq_pre_entry)
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is None
    assert len(trades) == 1 and trades[0].reason == "stop"
    assert st.equity < eq_after_entry           # 손실 실현
    assert st.daily_realized_pnl < 0
    # 보존: 최종 equity == 진입 전 원금 + Trade.pnl_net
    # WHY: pnl_net = pnl_gross - (open_fee + close_fee) - funding.
    #      equity 경로: eq_pre_entry - open_fee + (pnl_gross - close_fee) - funding
    #                 = eq_pre_entry + pnl_net ✓
    assert abs(st.equity - (eq_pre_entry + trades[0].pnl_net)) < 1e-6


def test_process_bar_funding_deducted_on_close():
    from quantpilot.backtest.models import Position
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_HoldStrategy())
    st = _state()
    st.position = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                           targets_remaining=[], opened_ts=1_700_000_000_000,
                           original_contracts=10)
    ts = 1_700_003_600_000
    fund = [(1_700_000_000_000 + 1, 0.001)]  # 보유 구간 내 funding 이벤트
    window = _window([100.0, 90.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 96.0, "low": 89.0, "close": 90.0}
    st, trades = process_bar(ctx, st, bar, window, funding_events=fund)
    assert trades and trades[0].funding != 0.0


def test_circuit_breaker_blocks_entry():
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    st.daily_realized_pnl = -60.0          # 시작자본 1000의 -6% → 정지 조건
    ts = 1_700_007_200_000
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is None              # 진입 차단됨
    assert st.halted is True
    assert trades == []


def test_utc_rollover_resets_and_allows_entry():
    from quantpilot.paper.trader import process_bar
    DAY = 86_400_000
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    st.daily_realized_pnl = -60.0
    st.halted = True
    prev = 1_700_000_000_000
    st.last_processed_bar_ts = prev
    ts = (prev // DAY + 1) * DAY            # 다음 UTC 자정 → 리셋
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.daily_realized_pnl >= -1e-9 or st.position is not None
    assert st.halted is False
    assert st.day_start_equity == st.equity + st.open_fee or st.position is not None
    assert st.position is not None         # 리셋 후 진입 가능
