"""페이퍼 운영 작업(panic 등) — CLI와 대시보드 서버가 공유.

WHY 분리: 비상정지는 CLI(`quantpilot panic`)와 웹 대시보드 버튼 두 경로로 호출된다.
로직을 한 곳에 두지 않으면 두 경로가 미묘하게 달라져(예: 한쪽만 persist_tick 원자성
누락) 가장 중요해야 할 안전장치가 경로별로 다르게 동작하는 사고가 난다.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from quantpilot.data.models import Instrument
from quantpilot.paper.models import PaperStateRow
from quantpilot.paper.store import load_state, make_run_key, persist_tick, set_panic_halted


@dataclass
class PanicResult:
    run_key: str
    had_position: bool
    pnl_net: float | None     # 청산 거래 net (포지션 없었으면 None)
    equity: float
    last_price: float | None


class PanicError(Exception):
    """panic 실행 불가(상태 없음 / Instrument 캐시 없음)."""


def execute_panic(session, symbol: str, timeframe: str, strategy: str) -> PanicResult:
    """보유 포지션 즉시 청산(최신 봉 종가) + panic_halted 정지 플래그 set.

    CLI panic 명령과 동일한 순서: panic_close → persist_tick(원자) → set_panic_halted.
    WHY persist_tick 단일 트랜잭션: 거래 기록과 상태(halted·포지션 해제)를 같은 commit에
    묶어야 중간 크래시 시 '거래는 기록됐는데 포지션은 살아있는' 불일치가 없다.
    """
    from quantpilot.backtest.data_loader import load_candles_df
    from quantpilot.paper.trader import TickContext, panic_close

    rk = make_run_key(symbol, timeframe, strategy)
    if session.get(PaperStateRow, rk) is None:
        raise PanicError(f"{rk}: 페이퍼 상태 없음. 할 일 없음.")
    st = load_state(session, rk, symbol=symbol, timeframe=timeframe,
                    strategy=strategy, capital=0.0, day_start_ts=0)
    inst = session.execute(select(Instrument).where(
        Instrument.symbol == symbol)).scalar_one_or_none()
    if inst is None:
        raise PanicError(f"{symbol} Instrument 캐시 없음. 먼저 'quantpilot collect'를 실행하세요.")
    df = load_candles_df(session, symbol, timeframe)
    last_price = float(df["close"].iloc[-1]) if not df.empty else (
        st.position.entry if st.position else 0.0)
    import time
    last_ts = int(df.index[-1]) if not df.empty else int(time.time() * 1000)
    ctx = TickContext(session=session, client=None, symbol=symbol, timeframe=timeframe,
                      strategy=None, capital=0.0, leverage=3,
                      ct_val=inst.ct_val, lot_sz=inst.lot_sz, run_key=rk)
    trade = panic_close(ctx, st, last_price=last_price, last_ts=last_ts)
    persist_tick(session, rk, st, [trade] if trade is not None else [])
    set_panic_halted(session, rk, True)
    return PanicResult(run_key=rk, had_position=trade is not None,
                       pnl_net=trade.pnl_net if trade is not None else None,
                       equity=st.equity, last_price=last_price)
