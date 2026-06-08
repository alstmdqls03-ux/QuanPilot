from sqlalchemy import select


def test_paper_equity_table_created(session):
    from quantpilot.paper.models import PaperEquityRow
    assert session.execute(select(PaperEquityRow)).scalars().all() == []


def test_persist_tick_records_equity_and_load_curve(session):
    from quantpilot.paper.store import (
        PaperState, load_equity_curve, make_run_key, persist_tick)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    persist_tick(session, rk, st, [], equity_points=[(100, 1000.0), (200, 1005.0)])
    curve = load_equity_curve(session, rk)
    assert curve == [(100, 1000.0), (200, 1005.0)]


def test_persist_tick_equity_dedup_on_reprocess(session):
    # 같은 ts를 다시 기록해도 중복되지 않음(재시작 재처리 idempotency)
    from quantpilot.paper.store import (
        PaperState, load_equity_curve, make_run_key, persist_tick)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    persist_tick(session, rk, st, [], equity_points=[(100, 1000.0)])
    persist_tick(session, rk, st, [], equity_points=[(100, 1000.0), (200, 1005.0)])
    assert load_equity_curve(session, rk) == [(100, 1000.0), (200, 1005.0)]


def test_run_one_tick_records_equity_per_bar(session):
    from quantpilot.data.models import Candle
    from quantpilot.paper.store import PaperState, load_equity_curve, make_run_key
    from quantpilot.paper.trader import TickContext, run_one_tick
    from quantpilot.strategy.base import IStrategy, Signal

    class _Hold(IStrategy):
        name = "t-hold"
        def __init__(self):
            self.timeframe = "1h"; self.lookback = 2
        def generate_signal(self, window, open_position):
            return Signal("hold", 0.0, None, {})

    tf = 3_600_000
    base = 1_700_000_000_000
    for i in range(4):
        c = 100.0 + i
        session.add(Candle(exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
                           ts=base + i * tf, open=c, high=c, low=c, close=c,
                           volume=1.0, inserted_at=base + i * tf))
    session.commit()
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-hold")
    ctx = TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_Hold(), capital=1000.0, leverage=3,
                      ct_val=0.01, lot_sz=1.0, run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-hold", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    st, trades = run_one_tick(ctx, st)
    curve = load_equity_curve(session, rk)
    # 결정 봉 = iloc 2,3 (lookback=2) → 2 포인트. 포지션 없으니 equity=1000 flat.
    assert len(curve) == 2
    assert curve[0] == (base + 2 * tf, 1000.0)
    assert curve[1] == (base + 3 * tf, 1000.0)
