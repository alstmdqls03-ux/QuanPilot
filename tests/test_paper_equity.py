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
