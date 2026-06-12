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
    # WHY 정밀 검증: notional = original_contracts × entry × ct_val = 10×100×0.01 = 10
    # funding = notional × rate = 10 × 0.001 = 0.01 (long은 양수 비용)
    assert abs(trades[0].funding - 0.01) < 1e-9, (
        f"funding 정확도 불일치: {trades[0].funding} != 0.01")


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
    from quantpilot.paper.store import PaperState, make_run_key, recent_trades
    from quantpilot.paper.trader import TickContext, run_one_tick
    tf = 3_600_000
    base = 1_700_000_000_000
    rows = [(base + i * tf, 100.0, 100.0, 100.0, 100.0) for i in range(3)]
    rows.append((base + 3 * tf, 100.0, 100.0, 89.0, 90.0))  # 마지막 봉 급락 → 손절
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
    # WHY equity != 초기값: 진입 수수료 차감 후 손절 손실이 실현됐으므로 1000보다 작아야 함
    assert st.equity != 1000.0, "진입+손절 후 equity가 변하지 않음 — 수수료/손실 미반영 의심"
    assert st.equity < 1000.0, "손절 손실로 equity가 줄어야 함"
    # WHY 거래 적재 확인: 손절이 발생했으므로 DB에 적어도 1건 기록돼야 함
    db_trades = recent_trades(session, rk, 100)
    assert len(db_trades) >= 1, "손절 거래가 DB에 없음"
    # 상태가 영속됐는지: 새 로드로 확인 (equity 포함)
    from quantpilot.paper.store import load_state
    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="t-long", capital=1000.0, day_start_ts=0)
    assert again.last_processed_bar_ts == base + 3 * tf
    # WHY equity 일치: persist_tick이 단일 commit이므로 재로드된 equity가 in-memory와 같아야 함
    assert again.equity == st.equity, (
        f"재로드 equity({again.equity}) != in-memory equity({st.equity})")


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


# ─── 숏 사이드 손절 test ──────────────────────────────────────────────────────

class _ShortOnceStrategy(IStrategy):
    """첫 진입 가능 시점에 short 1회(stop=price+5). 숏 손절 경로 검증용."""
    name = "t-short"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("short", 1.0, price + 5.0, {})
        return Signal("hold", 0.0, None, {})


def test_process_bar_short_stop_closes_and_realizes():
    """숏 포지션에서 stop-out 경로 검증: long 대칭 테스트.

    WHY 별도 테스트: 숏 check_exits는 high≥stop 조건을 사용하며, PnL 부호(entry-exit)가
    롱과 반대. 슬리피지도 청산 방향이 'buy'(위로 불리)로 뒤집힌다. 롱 손절 테스트만으로는
    이 분기들이 커버되지 않음.

    시나리오: entry=100.0, stop=105.0, side="short".
    bar의 high=106 ≥ stop=105 → 전량 손절.
    WHY equity < 진입 전: 숏 손절은 stop 가격이 entry보다 높으므로 entry-stop < 0 → 손실.
    """
    from quantpilot.backtest.models import Position
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_HoldStrategy())
    st = _state()
    # 숏: entry=100.0, stop=105.0 (entry보다 위). 손절 시 pnl = entry-exit < 0.
    st.position = Position(side="short", entry=100.0, contracts=10, stop=105.0,
                           targets_remaining=[(95.0, 0.33), (90.0, 0.33), (85.0, 0.34)],
                           opened_ts=1_700_000_000_000, original_contracts=10)
    open_fee = 0.5
    st.open_fee = open_fee
    st.equity -= open_fee  # 진입 수수료 이미 차감된 상태 시뮬레이션
    # WHY eq_pre_entry: pnl_net = pnl_gross - (open_fee + close_fee) - funding
    # equity 경로: eq_pre_entry - open_fee + (pnl_gross - close_fee) = eq_pre_entry + pnl_net
    eq_pre_entry = st.equity + open_fee  # = 1000.0 (진입 전 원금)
    ts = 1_700_003_600_000
    window = _window([100.0, 102.0], ts)
    # high=106 ≥ stop=105 → 숏 손절 발동
    bar = {"ts": ts, "open": 102.0, "high": 106.0, "low": 101.0, "close": 102.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is None, "손절 후 포지션이 남아 있음"
    assert len(trades) == 1, f"거래 수 {len(trades)} != 1"
    assert trades[0].reason == "stop", f"reason={trades[0].reason}, expected 'stop'"
    assert trades[0].side == "short"
    # 숏 손절: stop=105보다 높은 가격(슬리피지 포함)에서 buy 청산 → 손실
    assert st.equity < eq_pre_entry, "숏 손절 손실로 equity가 줄어야 함"
    assert st.daily_realized_pnl < 0, "숏 손절은 일일 실현 PnL을 감소시켜야 함"
    # 보존 불변식: 최종 equity == 진입 전 원금 + pnl_net
    assert abs(st.equity - (eq_pre_entry + trades[0].pnl_net)) < 1e-6, (
        f"equity 보존 불일치: {st.equity} != {eq_pre_entry + trades[0].pnl_net}")


# ─── 열린 포지션 재시작 (restart-with-open-position) test ───────────────────

def test_run_one_tick_skips_persist_when_panic_halted(session):
    """run_one_tick은 panic_halted가 DB에 세팅돼 있으면 persist_tick을 건너뛰어야(Bug 1 회귀 가드).

    시나리오: panic이 이 틱 도중에 걸렸을 때 루프가 stale in-memory 상태를 DB에 쓰면
    panic이 청산한 포지션·정지 플래그를 덮어쓴다. persist 직전에 panic_halted를 재확인해
    stale 상태를 쓰지 않고 DB 상태(panic이 기록한 값)를 반환해야 함.

    WHY save_state 먼저: set_panic_halted는 행이 있어야 동작(row is not None 조건).
    panic CLI도 기존 런에 대해서만 호출 가능(paper 시작 후에야 행이 생긴다).
    """
    from quantpilot.paper.store import (
        PaperState, load_state, make_run_key, read_panic_halted, save_state,
        set_panic_halted)
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
    # 행이 먼저 있어야 set_panic_halted가 동작(실제로도 panic CLI는 paper 시작 후 호출)
    save_state(session, st)
    # panic 프로세스가 panic_halted를 세팅(틱 도중에 걸린 상황 시뮬)
    set_panic_halted(session, rk, True)
    st2, trades = run_one_tick(ctx, st)
    # panic_halted가 세팅됐으므로 거래는 없고 persist를 건너뜀
    assert trades == [], "panic_halted 상태에서 거래가 발생해선 안 됨"
    # DB 상태(panic_halted=True)가 여전히 True여야 — 루프가 덮어쓰지 않음
    assert read_panic_halted(session, rk) is True, "루프 persist가 panic_halted를 덮어써선 안 됨"


def test_tickcontext_htf_field_defaults_none():
    """TickContext에 htf 옵션 필드가 있고 기본값 None이어야 함(기존 호출 불변)."""
    from quantpilot.paper.trader import TickContext
    ctx = TickContext(session=None, client=None, symbol="BTC-USDT-SWAP", timeframe="1h",
                      strategy=_HoldStrategy(), capital=1000.0, leverage=3,
                      ct_val=0.01, lot_sz=1.0, run_key="rk")
    # htf 필드 존재 + 기본 None
    assert hasattr(ctx, "htf"), "TickContext에 htf 필드 없음"
    assert ctx.htf is None, f"htf 기본값이 None이 아님: {ctx.htf}"


def test_run_one_tick_htf_branch_calls_set_htf(session):
    """ctx.htf가 설정되면 run_one_tick이 매 틱 strategy.set_htf를 호출해야 함.

    WHY 매 틱 재로드: 페이퍼는 실시간 운용 중 4h 봉이 닫힐 수 있으므로
    매 틱 최신 HTF 캔들을 전략에 주입해야 S6 판정이 신선하게 유지된다.
    백테는 한 번만 주입해도 되지만 페이퍼는 틱마다 재주입이 필요.
    """
    from quantpilot.paper.store import PaperState, make_run_key
    from quantpilot.paper.trader import TickContext, run_one_tick

    tf = 3_600_000
    base = 1_700_000_000_000

    # LTF 1h 봉 3개 시딩
    rows = [(base + i * tf, 100.0, 101.0, 99.0, 100.0) for i in range(3)]
    _seed_candles(session, "BTC-USDT-SWAP", "1h", rows)
    # 4h 봉 1개 시딩 (htf_df 로드를 위해)
    from quantpilot.data.models import Candle
    session.add(Candle(exchange="okx", symbol="BTC-USDT-SWAP", timeframe="4h",
                       ts=base, open=100.0, high=102.0, low=98.0, close=100.0,
                       volume=1.0, inserted_at=base))
    session.commit()

    # set_htf 호출을 추적하는 스파이 전략
    class _SpyStrategy(_HoldStrategy):
        def __init__(self):
            super().__init__()
            self.htf_calls = []
            self.htf_ms = 4 * tf
            self.ltf_ms = tf

        def set_htf(self, df):
            self.htf_calls.append(df)

    spy = _SpyStrategy()
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-hold")
    ctx = TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=spy, capital=1000.0, leverage=3,
                      ct_val=0.01, lot_sz=1.0, run_key=rk, htf="4h")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-hold", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    run_one_tick(ctx, st)
    assert len(spy.htf_calls) > 0, "ctx.htf가 설정됐는데 set_htf가 호출되지 않음"


def test_restart_with_open_position_then_stop(session):
    """열린 포지션이 DB에 있는 상태에서 재시작한 뒤 손절 봉을 처리하는 경로 검증.

    WHY 이 테스트: store.load_state가 open_fee/targets_remaining/pending_fills를
    올바르게 역직렬화해서 금융 로직이 실행되는지 e2e로 확인. 역직렬화 오류는
    포지션이 사라지거나 잘못된 PnL이 계산되는 조용한 버그를 유발함.

    단계:
      (a) 충분한 warmup + 진입봉 적재 → run_one_tick → position 열림 확인 + DB 저장 확인
      (b) 손절봉 추가 적재
      (c) load_state로 fresh 재시작 시뮬 → run_one_tick(HoldStrategy) → 손절 실현 확인

    WHY HoldStrategy for restart tick: 재시작 시 신호 전략 인스턴스가 새로 생성되므로
    _entered 플래그가 초기화돼 포지션 청산 직후 즉시 재진입하는 코너케이스가 발생.
    재시작 안전성 검증의 핵심은 load_state 역직렬화 + 손절 처리이므로, 재진입 신호를
    내지 않는 HoldStrategy로 재시작 틱을 구동한다.
    """
    from quantpilot.paper.store import PaperState, load_state, make_run_key, recent_trades
    from quantpilot.paper.trader import TickContext, run_one_tick
    tf = 3_600_000
    base = 1_700_000_000_000
    symbol = "BTC-USDT-SWAP"
    rk = make_run_key(symbol, "1h", "t-long")

    # (a) warmup 2봉 + 진입봉 1봉: 진입만 일어나고 손절은 아직 없음
    # high=low=close=100 → stop(95) 미발동, TP(~105)도 미발동
    rows_a = [(base + i * tf, 100.0, 101.0, 99.0, 100.0) for i in range(3)]
    _seed_candles(session, symbol, "1h", rows_a)

    ctx_entry = TickContext(session=session, client=None, symbol=symbol,
                            timeframe="1h", strategy=_LongOnceStrategy(), capital=1000.0,
                            leverage=3, ct_val=0.01, lot_sz=1.0, run_key=rk)
    st0 = PaperState(run_key=rk, symbol=symbol, timeframe="1h",
                     strategy="t-long", equity=1000.0, day_start_equity=1000.0,
                     day_start_ts=0)
    st0, _ = run_one_tick(ctx_entry, st0)

    # 진입됐는지 확인
    assert st0.position is not None, "warmup+진입봉 후 포지션이 열려야 함"
    assert st0.position.side == "long"
    assert st0.open_fee > 0

    # DB에서 재로드해도 포지션이 복원돼야 함 (직렬화 round-trip)
    st_reloaded_a = load_state(session, rk, symbol=symbol, timeframe="1h",
                                strategy="t-long", capital=1000.0, day_start_ts=0)
    assert st_reloaded_a.position is not None, (
        "DB reload 후 position이 복원되지 않음 — 직렬화 실패")
    assert st_reloaded_a.open_fee > 0, "open_fee가 DB에서 복원되지 않음"
    assert len(st_reloaded_a.position.targets_remaining) > 0, (
        "targets_remaining이 DB에서 복원되지 않음")

    # (b) 손절봉 1개 추가: low=89 ≤ stop=95
    _seed_candles(session, symbol, "1h",
                  [(base + 3 * tf, 90.0, 96.0, 89.0, 90.0)])

    # (c) fresh 재시작: load_state로 상태 복원 후 run_one_tick
    # WHY HoldStrategy: 손절 후 즉시 재진입하지 않도록 → 재시작 역직렬화 경로만 검증
    st_fresh = load_state(session, rk, symbol=symbol, timeframe="1h",
                          strategy="t-long", capital=1000.0, day_start_ts=0)
    eq_pre_entry = st_fresh.equity + st_fresh.open_fee  # 진입 전 원금 기준(보존식)

    ctx_hold = TickContext(session=session, client=None, symbol=symbol,
                           timeframe="1h", strategy=_HoldStrategy(), capital=1000.0,
                           leverage=3, ct_val=0.01, lot_sz=1.0, run_key=rk)
    st_final, trades_b = run_one_tick(ctx_hold, st_fresh)

    # 손절 후 포지션 없음
    assert st_final.position is None, "손절 후 포지션이 남아 있음"
    # 정확히 1건의 거래(손절)
    db_trades = recent_trades(session, rk, 100)
    assert len(db_trades) == 1, f"DB 거래 수 {len(db_trades)} != 1"
    assert db_trades[0].reason == "stop", f"reason={db_trades[0].reason}"
    # equity 보존: 최종 equity == 진입 전 원금 + pnl_net
    assert abs(st_final.equity - (eq_pre_entry + db_trades[0].pnl_net)) < 1e-6, (
        f"equity 보존 불일치: {st_final.equity} != {eq_pre_entry + db_trades[0].pnl_net}")
