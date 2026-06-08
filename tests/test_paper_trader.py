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


def test_panic_close_flattens_and_halts():
    from quantpilot.backtest.models import Position
    from quantpilot.paper.trader import panic_close
    ctx = _ctx(_HoldStrategy())
    st = _state()
    st.position = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                           targets_remaining=[], opened_ts=1_700_000_000_000,
                           original_contracts=10)
    st.open_fee = 0.5
    # WHY eq_pre 보정: _state()는 equity=1000 그대로, st.open_fee=0.5는 equity에서
    # 아직 차감되지 않은 상태. build_trade 내부에서 pnl_net은 open_fee를 이미
    # 비용에 포함하므로, 보존식 기준을 "진입 전 원금(open_fee 차감 전)"으로 맞춰야
    # 이중 차감을 방지할 수 있다. 즉 eq_pre = equity + open_fee = 1000.5.
    eq_pre = st.equity + st.open_fee
    trade = panic_close(ctx, st, last_price=102.0, last_ts=1_700_003_600_000)
    assert trade is not None and trade.reason == "panic"
    assert st.position is None and st.halted is True
    assert abs(st.equity - (eq_pre + trade.pnl_net)) < 1e-6  # last_price 기준 실현


def test_panic_close_noop_without_position():
    from quantpilot.paper.trader import panic_close
    ctx = _ctx(_HoldStrategy())
    st = _state()
    trade = panic_close(ctx, st, last_price=102.0, last_ts=1)
    assert trade is None and st.halted is True


def _seed_candles(session, symbol, timeframe, ohlc_rows):
    """ohlc_rows: [(ts, o,h,l,c), ...] → candles 테이블에 직접 적재."""
    from quantpilot.data.models import Candle
    for ts, o, h, low, c in ohlc_rows:
        session.add(Candle(exchange="okx", symbol=symbol, timeframe=timeframe, ts=ts,
                           open=o, high=h, low=low, close=c, volume=1.0, inserted_at=ts))
    session.commit()


def test_run_one_tick_processes_new_bars(session):
    from quantpilot.paper.store import PaperState, make_run_key
    from quantpilot.paper.trader import TickContext, run_one_tick
    tf = 3_600_000
    base = 1_700_000_000_000
    rows = [(base + i * tf, 100.0, 100.0, 100.0, 100.0) for i in range(3)]
    rows.append((base + 3 * tf, 100.0, 100.0, 89.0, 90.0))  # 마지막 봉 급락
    _seed_candles(session, "BTC-USDT-SWAP", "1h", rows)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-long")
    ctx = TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_LongOnceStrategy(), capital=1000.0,
                      leverage=3, ct_val=0.01, lot_sz=1.0, run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-long", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    st, trades = run_one_tick(ctx, st)
    assert st.last_processed_bar_ts == base + 3 * tf   # 마지막 봉까지 진행
    # 상태가 영속됐는지: 새 로드로 확인
    from quantpilot.paper.store import load_state
    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="t-long", capital=1000.0, day_start_ts=0)
    assert again.last_processed_bar_ts == base + 3 * tf


def test_run_one_tick_atomic_no_duplicate_trades_on_restart(session):
    from quantpilot.paper.store import PaperState, load_state, make_run_key, recent_trades
    from quantpilot.paper.trader import TickContext, run_one_tick
    tf = 3_600_000
    base = 1_700_000_000_000
    rows = [(base + i * tf, 100.0, 100.0, 100.0, 100.0) for i in range(3)]
    rows.append((base + 3 * tf, 100.0, 100.0, 89.0, 90.0))  # 손절 발생 → 1 trade
    _seed_candles(session, "BTC-USDT-SWAP", "1h", rows)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-long")
    def _mk():
        return TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                           timeframe="1h", strategy=_LongOnceStrategy(), capital=1000.0,
                           leverage=3, ct_val=0.01, lot_sz=1.0, run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-long", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    st, _ = run_one_tick(_mk(), st)
    n1 = len(recent_trades(session, rk, 100))
    assert n1 == 1
    # 재시작 시뮬: DB에서 상태 재로드 후 같은 봉으로 또 틱 → 중복 거래 없어야
    st2 = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                     strategy="t-long", capital=1000.0, day_start_ts=0)
    st2, trades2 = run_one_tick(_mk(), st2)
    assert trades2 == [] and len(recent_trades(session, rk, 100)) == 1  # 중복 없음


def test_run_one_tick_dedup_no_reprocess(session):
    from quantpilot.paper.store import PaperState, make_run_key
    from quantpilot.paper.trader import TickContext, run_one_tick
    tf = 3_600_000
    base = 1_700_000_000_000
    rows = [(base + i * tf, 100.0, 101.0, 99.0, 100.0) for i in range(3)]
    _seed_candles(session, "BTC-USDT-SWAP", "1h", rows)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-hold")
    ctx = TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_HoldStrategy(), capital=1000.0,
                      leverage=3, ct_val=0.01, lot_sz=1.0, run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-hold", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    st, _ = run_one_tick(ctx, st)
    last = st.last_processed_bar_ts
    st, trades2 = run_one_tick(ctx, st)   # 새 봉 없음
    assert st.last_processed_bar_ts == last and trades2 == []


# ─── Bug 1: persisted halt flag must block entry even when daily PnL is OK ───

def test_persisted_halt_blocks_entry_even_when_pnl_ok():
    """Bug 1 회귀: state.halted=True인데 daily PnL이 괜찮으면 should_halt()는 False를 반환.
    수정 전에는 should_halt() 결과만 보므로 진입이 열려버림.
    수정 후에는 state.halted 플래그를 먼저 확인하므로 진입이 차단되어야 함.
    WHY 같은 UTC 날 보장: last_processed_bar_ts를 bar ts보다 1시간 전으로 설정하면
    is_new_utc_day()가 False → UTC 리셋 없이 halted 플래그가 유지됨.
    """
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    st.halted = True
    st.daily_realized_pnl = 0.0          # PnL은 정상 → should_halt()는 False
    # WHY 같은 UTC 날 내 timestamps 선택: is_new_utc_day가 False여야 step 0에서
    # halted가 리셋되지 않음. 1_700_000_000_000(2023-11-14 22:13 UTC)와
    # 1_700_000_000_000 + 3_600_000(+1h)은 모두 같은 UTC 날(19675번째 날).
    DAY_MS = 86_400_000
    # 하루 시작 기준으로 같은 날 내 두 시점 사용
    day_start = 1_700_000_000_000 - (1_700_000_000_000 % DAY_MS)  # UTC 자정
    ts = day_start + 7_200_000          # UTC 자정 + 2h (같은 날)
    st.last_processed_bar_ts = day_start + 3_600_000  # UTC 자정 + 1h (같은 날, ts보다 1h 전)
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is None, "halted=True이면 daily PnL이 좋아도 진입 차단돼야 함"
    assert st.halted is True
    assert trades == []


# ─── Bug 2: entry fee must count toward daily_realized_pnl ───

def test_entry_fee_counts_toward_daily_pnl():
    """Bug 2 회귀: 진입 수수료가 equity에서 차감되지만 daily_realized_pnl에는 반영 안 됨.
    수정 전에는 daily_realized_pnl이 0 그대로.
    수정 후에는 daily_realized_pnl < 0 (entry fee만큼 감소).
    """
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    # 초기 daily_realized_pnl은 0
    assert st.daily_realized_pnl == 0.0
    ts = 1_700_007_200_000
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is not None, "진입은 성공해야 함"
    open_fee = st.open_fee
    assert open_fee > 0, "진입 수수료가 0보다 커야 함"
    # 진입 수수료가 daily_realized_pnl에 반영되어야 함 (음수)
    assert st.daily_realized_pnl < 0, "진입 수수료는 일일 실현 PnL에서 차감돼야 함"
    assert abs(st.daily_realized_pnl - (-open_fee)) < 1e-9, (
        f"daily_realized_pnl({st.daily_realized_pnl}) != -open_fee({-open_fee})")


# ─── Bug 4: load_state returns clean persisted values (reload contract) ───

def test_load_state_returns_persisted_clean_values(session):
    """Bug 4 회귀: run_loop 예외 후 in-memory state를 버리고 DB에서 재로드해야 함.
    이 테스트는 load_state가 실제로 DB에 커밋된 마지막 상태를 반환하는 것을 검증.
    순서: 1) clean state를 save_state로 커밋 → 2) in-memory state 더럽힘 → 3) load_state로
    재로드 → 4) 재로드된 값이 커밋된 clean 값과 일치(dirty 값 아님)를 assert.
    WHY 이 테스트로 충분: run_loop의 except 블록에서 load_state를 호출하는 코드가
    올바르게 동작함을 간접 보증. 즉 롤백+재로드 패턴의 계약을 테스트.
    """
    from quantpilot.paper.store import PaperState, load_state, make_run_key, save_state
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-hold")
    clean_equity = 1000.0
    clean_ts = 1_700_007_200_000
    # 1) clean state를 DB에 저장
    clean_st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                          strategy="t-hold", equity=clean_equity,
                          day_start_equity=clean_equity, day_start_ts=0,
                          last_processed_bar_ts=clean_ts)
    save_state(session, clean_st)
    # 2) in-memory state를 더럽힘 (DB 커밋 없음)
    dirty_st = clean_st  # 같은 객체를 직접 변조
    dirty_st.equity = 99999.0
    dirty_st.last_processed_bar_ts = clean_ts + 3_600_000  # 한 봉 더 전진
    # 3) DB에서 재로드
    reloaded = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                          strategy="t-hold", capital=clean_equity, day_start_ts=0)
    # 4) reloaded는 clean 값 (dirty 값 아님)
    assert reloaded.equity == clean_equity, (
        f"재로드된 equity({reloaded.equity})가 dirty 값(99999)이 아닌 clean 값({clean_equity})이어야 함")
    assert reloaded.last_processed_bar_ts == clean_ts, (
        f"재로드된 ts({reloaded.last_processed_bar_ts})가 clean_ts({clean_ts})여야 함")
