from sqlalchemy import select


def test_paper_tables_created(session):
    # init_db가 paper 테이블을 등록·생성했으면 빈 조회가 에러 없이 동작
    from quantpilot.paper.models import PaperStateRow, PaperTradeRow
    assert session.execute(select(PaperStateRow)).scalars().all() == []
    assert session.execute(select(PaperTradeRow)).scalars().all() == []


def test_make_run_key():
    from quantpilot.paper.store import make_run_key
    assert make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr") == "BTC-USDT-SWAP|1h|rsi-mr"


def test_load_empty_returns_fresh_state(session):
    from quantpilot.paper.store import load_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=1_700_000_000_000)
    assert st.equity == 1000.0 and st.day_start_equity == 1000.0
    assert st.position is None and st.halted is False
    assert st.last_processed_bar_ts is None


def test_save_then_load_no_position(session):
    from quantpilot.paper.store import load_state, save_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=1_700_000_000_000)
    st.equity = 1042.5
    st.daily_realized_pnl = -12.0
    st.halted = True
    st.last_processed_bar_ts = 1_700_003_600_000
    save_state(session, st)

    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    assert again.equity == 1042.5 and again.daily_realized_pnl == -12.0
    assert again.halted is True and again.last_processed_bar_ts == 1_700_003_600_000
    assert again.position is None
