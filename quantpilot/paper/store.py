"""페이퍼 상태/거래 영속 (I/O만). 매매 로직 없음.

PaperState = 메모리상 풍부한 상태(포지션·잔여 fill 포함). DB 행(PaperStateRow)과
상호 변환. 포지션의 targets_remaining/pending_fills는 JSON 직렬화.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from quantpilot.backtest.models import Fill, Position, Trade
from quantpilot.paper.models import PaperEquityRow, PaperStateRow, PaperTradeRow


@dataclass
class PaperState:
    run_key: str
    symbol: str
    timeframe: str
    strategy: str
    equity: float
    day_start_equity: float
    day_start_ts: int
    daily_realized_pnl: float = 0.0
    halted: bool = False
    panic_halted: bool = False
    last_processed_bar_ts: int | None = None
    position: Position | None = None
    open_fee: float = 0.0                 # 보유 포지션 진입 수수료(Trade 집계용)
    pending_fills: list[Fill] = field(default_factory=list)  # 분할익절 누적 fill


def make_run_key(symbol: str, timeframe: str, strategy: str) -> str:
    return f"{symbol}|{timeframe}|{strategy}"


def load_state(session, run_key: str, *, symbol: str, timeframe: str,
               strategy: str, capital: float, day_start_ts: int) -> PaperState:
    """run_key 상태를 복원. 없으면 초기 자본 fresh 상태."""
    row = session.get(PaperStateRow, run_key)
    if row is None:
        return PaperState(run_key=run_key, symbol=symbol, timeframe=timeframe,
                          strategy=strategy, equity=capital,
                          day_start_equity=capital, day_start_ts=day_start_ts)
    position = None
    open_fee = 0.0
    pending: list[Fill] = []
    if row.pos_side is not None:
        # WHY tuple() 변환: JSON은 리스트만 지원하므로 targets_remaining의
        # (price, fraction) 쌍을 tuple로 복원해야 Position 타입과 일치.
        targets = [tuple(t) for t in json.loads(row.pos_targets_remaining)]
        position = Position(
            side=row.pos_side, entry=row.pos_entry, contracts=row.pos_contracts,
            stop=row.pos_stop, targets_remaining=targets, opened_ts=row.pos_opened_ts,
            original_contracts=row.pos_original_contracts)
        open_fee = row.pos_open_fee or 0.0
        pending = [Fill(**f) for f in json.loads(row.pos_pending_fills or "[]")]
    return PaperState(
        run_key=run_key, symbol=row.symbol, timeframe=row.timeframe,
        strategy=row.strategy, equity=row.equity,
        day_start_equity=row.day_start_equity, day_start_ts=row.day_start_ts,
        daily_realized_pnl=row.daily_realized_pnl, halted=row.halted,
        panic_halted=bool(row.panic_halted),
        last_processed_bar_ts=row.last_processed_bar_ts,
        position=position, open_fee=open_fee, pending_fills=pending)


def _apply_state_to_row(session, state: "PaperState") -> None:
    """상태를 session에 반영(commit 없음). save_state / persist_tick 양쪽에서 재사용.

    WHY 분리: 거래 행과 진행위치를 동일 commit에 묶는 persist_tick이 이 로직을 재사용하기
    위해 commit을 호출부로 미룬 순수 row-mutation 헬퍼. 직접 호출하면 commit 없이 행만 바뀜.
    """
    row = session.get(PaperStateRow, state.run_key)
    if row is None:
        row = PaperStateRow(run_key=state.run_key)
        session.add(row)
    row.symbol = state.symbol
    row.timeframe = state.timeframe
    row.strategy = state.strategy
    row.equity = state.equity
    row.day_start_equity = state.day_start_equity
    row.day_start_ts = state.day_start_ts
    row.daily_realized_pnl = state.daily_realized_pnl
    row.halted = state.halted
    # WHY panic_halted 미기록: 루프가 panic 플래그를 덮어쓰면 안 됨. set_panic_halted(panic 전용)만 기록.
    row.last_processed_bar_ts = state.last_processed_bar_ts
    p = state.position
    if p is None:
        # WHY 명시적 NULL: 포지션 없을 때 잔여 필드가 이전 런 데이터를 물고 있으면
        # 재시작 시 포지션 있다고 잘못 복원될 수 있음 → 전부 초기화.
        row.pos_side = None
        row.pos_entry = None
        row.pos_contracts = None
        row.pos_original_contracts = None
        row.pos_stop = None
        row.pos_targets_remaining = None
        row.pos_opened_ts = None
        row.pos_open_fee = None
        row.pos_pending_fills = None
    else:
        row.pos_side = p.side
        row.pos_entry = p.entry
        row.pos_contracts = p.contracts
        row.pos_original_contracts = p.original_contracts
        row.pos_stop = p.stop
        # WHY list() 변환: tuple은 JSON 직렬화 불가, list로 변환 후 저장.
        row.pos_targets_remaining = json.dumps([list(t) for t in p.targets_remaining])
        row.pos_opened_ts = p.opened_ts
        row.pos_open_fee = state.open_fee
        row.pos_pending_fills = json.dumps([f.__dict__ for f in state.pending_fills])


def save_state(session, state: "PaperState") -> None:
    """상태를 upsert(원자적). 포지션 없으면 pos_* 전부 NULL."""
    _apply_state_to_row(session, state)
    session.commit()


def persist_tick(session, run_key: str, state: "PaperState", trades: "list[Trade]",
                 equity_points: "list[tuple[int, float]]" = ()) -> None:
    """한 틱의 청산 거래 + equity 포인트 + 상태를 단일 트랜잭션으로 영속(원자적).

    WHY 원자성: 거래·equity·진행위치(last_processed_bar_ts)를 같은 commit에 묶어야,
    틱 도중 강제 종료돼도 '일부만 적재된' 불일치가 안 생긴다. 재시작 시 같은 봉을 재처리해도
    equity는 UNIQUE(run_key,ts) on_conflict로 중복 안 됨.
    """
    for tr in trades:
        session.add(PaperTradeRow(
            run_key=run_key, side=tr.side, entry=tr.entry, exit=tr.exit,
            contracts=tr.contracts, pnl_gross=tr.pnl_gross, fees=tr.fees,
            funding=tr.funding, pnl_net=tr.pnl_net, opened_ts=tr.opened_ts,
            closed_ts=tr.closed_ts, reason=tr.reason))
    for ts, eq in equity_points:
        stmt = sqlite_insert(PaperEquityRow).values(
            run_key=run_key, ts=ts, equity=eq).on_conflict_do_nothing(
            index_elements=["run_key", "ts"])
        session.execute(stmt)
    _apply_state_to_row(session, state)
    session.commit()


def append_trade(session, run_key: str, trade: Trade) -> None:
    session.add(PaperTradeRow(
        run_key=run_key, side=trade.side, entry=trade.entry, exit=trade.exit,
        contracts=trade.contracts, pnl_gross=trade.pnl_gross, fees=trade.fees,
        funding=trade.funding, pnl_net=trade.pnl_net, opened_ts=trade.opened_ts,
        closed_ts=trade.closed_ts, reason=trade.reason))
    session.commit()


def recent_trades(session, run_key: str, n: int) -> list[Trade]:
    rows = session.execute(
        select(PaperTradeRow).where(PaperTradeRow.run_key == run_key)
        .order_by(PaperTradeRow.closed_ts.desc()).limit(n)).scalars().all()
    return [Trade(side=r.side, entry=r.entry, exit=r.exit, contracts=r.contracts,
                  pnl_gross=r.pnl_gross, fees=r.fees, funding=r.funding,
                  pnl_net=r.pnl_net, opened_ts=r.opened_ts, closed_ts=r.closed_ts,
                  reason=r.reason) for r in rows]


def load_equity_curve(session, run_key: str) -> list[tuple[int, float]]:
    """run_key의 equity 곡선을 ts 오름차순 [(ts, equity), ...]로. paper-report 입력."""
    rows = session.execute(
        select(PaperEquityRow).where(PaperEquityRow.run_key == run_key)
        .order_by(PaperEquityRow.ts)).scalars().all()
    return [(r.ts, r.equity) for r in rows]


def read_halted(session, run_key: str) -> bool:
    """DB의 halted를 신선하게 읽음(외부 프로세스 panic 반영). 행 없으면 False.

    WHY expire_all: 도는 루프의 세션은 상태 행을 캐시하고 있어, 별도 프로세스(panic)가
    커밋한 halted=True를 그냥 session.get으로는 못 본다. 캐시를 무효화해야 DB의 외부 변경을 본다.
    """
    session.expire_all()
    row = session.get(PaperStateRow, run_key)
    return bool(row.halted) if row is not None else False


def set_panic_halted(session, run_key: str, value: bool = True) -> None:
    """panic 전용 플래그 기록(루프는 절대 안 건드림). panic CLI가 호출.

    WHY 전용 writer: 루프의 persist_tick은 panic_halted를 안 쓰므로 panic이 직접 기록해야 한다.
    이 분리 덕에 루프가 도중에 persist해도 panic 정지를 덮어쓰지 못한다(Bug 1).
    """
    row = session.get(PaperStateRow, run_key)
    if row is not None:
        row.panic_halted = value
        session.commit()


def read_panic_halted(session, run_key: str) -> bool:
    """DB의 panic_halted를 신선하게 읽음(외부 panic 반영). 행 없으면 False.

    WHY expire_all: read_halted와 동일 — 루프의 캐시된 행은 별 프로세스 커밋을 안 본다.
    """
    session.expire_all()
    row = session.get(PaperStateRow, run_key)
    return bool(row.panic_halted) if row is not None else False
