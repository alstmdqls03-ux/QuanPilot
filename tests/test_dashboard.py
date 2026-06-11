"""MINCODE 대시보드 백엔드 테스트: api.build_state / ops.execute_panic / HTTP 서버.

WHY 파일 DB(tmp_path): 서버는 스레드별 세션을 쓰므로 :memory:는 공유 안 됨 —
기존 test_paper_killswitch와 같은 패턴.
"""
import http.client
import json
import threading
import time

import pytest

from quantpilot.backtest.models import Fill, Position
from quantpilot.dashboard.api import build_state
from quantpilot.data.db import init_db, make_engine, make_session_factory
from quantpilot.data.models import Candle, Instrument
from quantpilot.paper.ops import PanicError, execute_panic
from quantpilot.paper.store import (
    PaperState, load_state, make_run_key, persist_tick, read_panic_halted,
    recent_trades, save_state)
from quantpilot.risk.liquidation import liquidation_price

HOUR = 3_600_000
T0 = 1_780_000_000_000
SYM, TF, STRAT = "BTC-USDT-SWAP", "1h", "rsi-mr"


def _factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'qp.db'}")
    init_db(engine)
    return make_session_factory(engine)


def _seed(session, n_candles=40, with_position=True):
    """캔들 + Instrument + (포지션 1차익절 상태의) 페이퍼 상태 + 거래 1건 + equity 2점."""
    session.add(Instrument(exchange="okx", symbol=SYM, ct_val=0.01, ct_val_ccy="BTC",
                           lot_sz=1.0, min_sz=1.0, tick_sz=0.1, updated_at=T0))
    for i in range(n_candles):
        px = 60_000 + i * 10.0
        session.add(Candle(symbol=SYM, timeframe=TF, ts=T0 + i * HOUR,
                           open=px, high=px + 50, low=px - 50, close=px, volume=5.0,
                           inserted_at=T0))
    session.commit()
    rk = make_run_key(SYM, TF, STRAT)
    st = PaperState(run_key=rk, symbol=SYM, timeframe=TF, strategy=STRAT,
                    equity=1010.0, day_start_equity=1000.0, day_start_ts=T0,
                    daily_realized_pnl=10.0,
                    last_processed_bar_ts=T0 + (n_candles - 1) * HOUR)
    if with_position:
        # entry 60000, stop 59000 → R=1000. TP1(61000)은 이미 체결(2계약),
        # targets_remaining에는 TP2/TP3만 남음.
        st.position = Position(side="long", entry=60_000.0, contracts=3,
                               stop=59_000.0,
                               targets_remaining=[(62_000.0, 0.33), (63_000.0, 0.34)],
                               opened_ts=T0 + 10 * HOUR, original_contracts=5)
        st.open_fee = 1.5
        st.pending_fills = [Fill(ts=T0 + 12 * HOUR, price=61_000.0, contracts=2,
                                 fee=0.61, reason="tp1", pnl_gross=20.0)]
    save_state(session, st)
    from quantpilot.backtest.models import Trade
    tr = Trade(side="short", entry=62_000.0, exit=61_500.0, contracts=4,
               pnl_gross=20.0, fees=2.5, funding=0.5, pnl_net=17.0,
               opened_ts=T0 + 2 * HOUR, closed_ts=T0 + 5 * HOUR, reason="exit_signal")
    persist_tick(session, rk, st, [tr],
                 equity_points=[(T0 + 5 * HOUR, 1000.0), (T0 + 12 * HOUR, 1010.0)])
    return rk


# ---------- api.build_state ----------

def test_build_state_no_run(session):
    out = build_state(session, symbol=SYM, timeframe=TF, strategy=STRAT)
    assert out["run"] is False
    assert "run_key" in out


def test_build_state_full(tmp_path):
    SL = _factory(tmp_path)
    s = SL()
    _seed(s)
    out = build_state(s, symbol=SYM, timeframe=TF, strategy=STRAT)
    assert out["run"] is True
    last_close = 60_000 + 39 * 10.0
    assert out["price"] == last_close
    assert len(out["candles"]) == 40
    assert len(out["rsi"]) == 40                       # 캔들과 정렬된 시리즈
    assert out["rsi"][-1] is not None
    # 포지션 파생값 — 실코드(liquidation_price, _pnl)와 일치해야 함
    pos = out["position"]
    assert pos["side"] == "long" and pos["contracts"] == 3
    assert pos["r_unit"] == pytest.approx(1000.0)
    assert pos["r_now"] == pytest.approx((last_close - 60_000) / 1000.0)
    assert pos["liq"] == pytest.approx(liquidation_price(60_000.0, 3, "long"))
    assert pos["unrealized"] == pytest.approx((last_close - 60_000) * 3 * 0.01)
    # TP 사다리: TP1 체결됨(잔여 타깃에 없음), TP2/TP3 대기
    ladder = pos["ladder"]
    assert [r["label"] for r in ladder] == ["TP1", "TP2", "TP3"]
    assert ladder[0]["filled"] is True and ladder[0]["fill_price"] == 61_000.0
    assert ladder[1]["filled"] is False and ladder[2]["filled"] is False
    # 서킷브레이커: 이익이면 used=0
    assert out["breaker"]["limit_usd"] == pytest.approx(50.0)
    assert out["breaker"]["used_usd"] == 0.0
    # 거래/곡선/지표
    assert len(out["trades"]) == 1 and out["trades"][0]["pnl_net"] == 17.0
    assert len(out["equity_curve"]) == 2
    assert out["metrics"] is not None
    # equity = 실현 + 미실현
    assert out["equity"] == pytest.approx(1010.0 + pos["unrealized"])
    json.dumps(out)                                    # JSON 직렬화 가능해야 함


def test_build_state_breaker_used_on_loss(tmp_path):
    SL = _factory(tmp_path)
    s = SL()
    rk = _seed(s, with_position=False)
    st = load_state(s, rk, symbol=SYM, timeframe=TF, strategy=STRAT,
                    capital=0.0, day_start_ts=0)
    st.daily_realized_pnl = -30.0
    save_state(s, st)
    out = build_state(s, symbol=SYM, timeframe=TF, strategy=STRAT)
    assert out["breaker"]["used_usd"] == pytest.approx(30.0)
    assert out["position"] is None
    # 포지션 없으면 다음 진입 사이징 미리보기 제공
    assert out["next_trade_max_loss"] is None or out["next_trade_max_loss"] > 0


# ---------- ops.execute_panic ----------

def test_execute_panic_closes_position_and_sets_flag(tmp_path):
    SL = _factory(tmp_path)
    s = SL()
    rk = _seed(s)
    r = execute_panic(s, SYM, TF, STRAT)
    assert r.had_position is True
    assert read_panic_halted(SL(), rk) is True         # 별 세션에서도 보임
    st = load_state(SL(), rk, symbol=SYM, timeframe=TF, strategy=STRAT,
                    capital=0.0, day_start_ts=0)
    assert st.position is None and st.halted is True
    trades = recent_trades(SL(), rk, 10)
    assert any(t.reason == "panic" for t in trades)


def test_execute_panic_no_state_raises(session):
    with pytest.raises(PanicError):
        execute_panic(session, SYM, TF, STRAT)


def test_cli_panic_uses_shared_ops(tmp_path, monkeypatch):
    """CLI panic 회귀: ops 경유 후에도 동작(포지션 없음 경로)."""
    from click.testing import CliRunner
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.chdir(tmp_path)
    from quantpilot.cli import cli
    r = CliRunner().invoke(cli, ["panic"])
    assert r.exit_code == 0
    assert "상태 없음" in r.output


# ---------- HTTP 서버 ----------

@pytest.fixture
def served(tmp_path):
    from quantpilot.dashboard.server import make_server
    SL = _factory(tmp_path)
    s = SL()
    _seed(s)
    s.close()
    srv = make_server(SL, symbol=SYM, timeframe=TF, strategy=STRAT, port=0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    time.sleep(0.05)
    yield srv.server_address[1], SL
    srv.shutdown()


def _req(port, method, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def test_server_state_and_index(served):
    port, _ = served
    code, body = _req(port, "GET", "/api/state")
    assert code == 200
    data = json.loads(body)
    assert data["run"] is True and data["position"]["side"] == "long"
    code, body = _req(port, "GET", "/")
    assert code == 200 and b"MINCODE" in body
    code, _ = _req(port, "GET", "/static/js/app.jsx")
    assert code == 200
    code, _ = _req(port, "GET", "/../../etc/passwd")
    assert code == 404


def test_server_panic_endpoint(served):
    port, SL = served
    code, body = _req(port, "POST", "/api/panic")
    assert code == 200
    data = json.loads(body)
    assert data["ok"] is True and data["had_position"] is True
    assert read_panic_halted(SL(), make_run_key(SYM, TF, STRAT)) is True
