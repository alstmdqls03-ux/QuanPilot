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


def test_save_then_load_with_position(session):
    from quantpilot.backtest.models import Fill, Position
    from quantpilot.paper.store import load_state, save_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    st.position = Position(side="long", entry=100.0, contracts=7, stop=95.0,
                           targets_remaining=[(105.0, 0.33), (110.0, 0.34)],
                           opened_ts=1_700_000_000_000, original_contracts=10)
    st.open_fee = 0.35
    st.pending_fills = [Fill(ts=1_700_003_600_000, price=105.0, contracts=3,
                             fee=0.16, reason="tp1", pnl_gross=15.0)]
    save_state(session, st)

    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    p = again.position
    assert p is not None
    assert p.side == "long" and p.contracts == 7 and p.original_contracts == 10
    assert p.targets_remaining == [(105.0, 0.33), (110.0, 0.34)]
    assert again.open_fee == 0.35
    assert len(again.pending_fills) == 1 and again.pending_fills[0].reason == "tp1"


def test_position_cleared_on_resave(session):
    # 포지션을 None으로 다시 저장하면 pos_* 가 NULL로 비워져야 함
    from quantpilot.backtest.models import Position
    from quantpilot.paper.store import load_state, save_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    st.position = Position(side="short", entry=100.0, contracts=5, stop=105.0,
                           targets_remaining=[], opened_ts=1, original_contracts=5)
    save_state(session, st)
    st.position = None
    save_state(session, st)
    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    assert again.position is None


def test_append_and_recent_trades(session):
    from quantpilot.backtest.models import Trade
    from quantpilot.paper.store import append_trade, recent_trades, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    for i in range(3):
        append_trade(session, rk, Trade(
            side="long", entry=100.0, exit=105.0, contracts=10, pnl_gross=50.0,
            fees=1.0, funding=0.0, pnl_net=49.0, opened_ts=i, closed_ts=100 + i,
            reason="tp1"))
    got = recent_trades(session, rk, 2)
    assert len(got) == 2
    assert got[0].closed_ts == 102 and got[1].closed_ts == 101  # 최신순
