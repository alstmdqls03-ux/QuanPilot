"""페이퍼 트레이더 — 실시간 루프(조립만). 매매 판단은 엔진/전략, 정지는 circuit_breaker,
영속은 store에 위임. process_bar는 네트워크 없이 결정적(테스트 가능).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantpilot.backtest.costs import funding_between
from quantpilot.backtest.engine import build_trade, check_exits, close_fill, open_position
from quantpilot.paper.store import PaperState
from quantpilot.risk.circuit_breaker import is_new_utc_day, should_halt


@dataclass
class TickContext:
    session: object
    client: object
    symbol: str
    timeframe: str
    strategy: object        # IStrategy
    capital: float
    leverage: int
    ct_val: float
    lot_sz: float
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    poll_seconds: int = 60
    run_key: str = ""


def process_bar(ctx: TickContext, state: PaperState, bar: dict,
                window: pd.DataFrame, funding_events=None):
    """한 닫힌 봉을 상태에 반영. (state, list[Trade]) 반환.

    순서(백테 엔진과 동일): UTC 리셋 → 청산 판정(즉시 실현) → 신호 → 진입/청산.

    WHY 순서 고정: 백테 run_backtest와 동일한 단계 순서를 유지해야 백테=페이퍼 parity 성립.
    순서가 다르면 같은 데이터를 돌려도 다른 결과가 나올 수 있음(특히 같은 봉에서
    진입+손절이 겹치는 코너케이스).
    """
    funding_events = funding_events or []
    trades = []

    # 0) UTC 일자 경계 → 일일 카운터/halt 리셋
    # WHY UTC 기준 리셋: OKX funding 정산 및 거래소 일일 경계가 모두 UTC 00:00 기준.
    # 로컬 타임존 의존을 제거해 서버 시간대와 무관하게 결정적 동작 보장.
    if state.last_processed_bar_ts is not None and \
            is_new_utc_day(state.last_processed_bar_ts, bar["ts"]):
        state.day_start_equity = state.equity
        state.daily_realized_pnl = 0.0
        state.day_start_ts = bar["ts"]
        state.halted = False  # 새 날이면 halt 해제 — 어제 손실 한도가 오늘 영향 안 줌

    # 1) 보유 포지션 청산 판정 (체결 즉시 equity 실현 — 백테와 동일 불변식)
    # WHY 즉시 실현: 부분익절 실현손익을 완전청산까지 미루면 그 봉에서 equity 곡선이
    # 가짜 하락 → Sharpe/MaxDD 왜곡. 백테(run_backtest)와 동일 처리.
    if state.position is not None:
        pos2, fills = check_exits(state.position, bar, ctx.fee_bps,
                                  ctx.slippage_bps, ctx.ct_val)
        if fills:
            realized = sum(f.pnl_gross for f in fills) - sum(f.fee for f in fills)
            state.equity += realized
            state.daily_realized_pnl += realized
            state.pending_fills.extend(fills)
        if pos2 is None:
            # 완전 청산 → Trade 집계 후 포지션 비움
            trades.append(_close_out(ctx, state, bar["ts"], funding_events))
        else:
            state.position = pos2

    # 2) 전략 신호
    signal = ctx.strategy.generate_signal(window, state.position)

    # 3) 신호 처리
    if signal.side in ("long", "short") and state.position is None:
        # WHY should_halt 체크: 하루 실현손익이 -5% 한도를 넘으면 신규 베팅 차단.
        # 기존 포지션 손절/익절은 막지 않는다(사이징 불변식으로 이미 한정).
        if should_halt(state.day_start_equity, state.daily_realized_pnl):
            state.halted = True  # 서킷 차단: 신규 진입 안 함
        else:
            pos, open_fee = open_position(
                signal.side, bar, signal.suggested_stop, state.equity, ctx.ct_val,
                ctx.lot_sz, ctx.leverage, ctx.fee_bps, ctx.slippage_bps)
            if pos is not None:
                # WHY 진입 수수료 즉시 차감: 백테(run_backtest L164)와 동일. 수수료를
                # 청산 시점으로 미루면 equity가 일시 과대 계상 → 사이징 불변식 위반 가능.
                state.equity -= open_fee
                state.position = pos
                state.open_fee = open_fee
            # WHY 무조건 리셋: 엔진(run_backtest L165)과 동일 구조. 신규 진입 신호 시점엔
            # pending_fills가 항상 비어 있어야 하므로 진입 실패 시에도 비워 둔다(구조 일치).
            state.pending_fills = []
    elif signal.side == "exit" and state.position is not None:
        # 전략이 명시적 청산 신호를 냄 → 시장가 전량 청산
        fill = close_fill(state.position, bar["close"], state.position.contracts,
                          bar["ts"], "exit_signal", ctx.fee_bps, ctx.slippage_bps,
                          ctx.ct_val)
        state.equity += fill.pnl_gross - fill.fee
        state.daily_realized_pnl += fill.pnl_gross - fill.fee
        state.pending_fills.append(fill)
        trades.append(_close_out(ctx, state, bar["ts"], funding_events))

    state.last_processed_bar_ts = bar["ts"]
    return state, trades


def panic_close(ctx: TickContext, state: PaperState, last_price: float,
                last_ts: int):
    """비상정지: 보유 포지션을 last_price에 전량 청산 + halted=True. Trade 반환(없으면 None).

    WHY last_price=최신 닫힌 봉 종가: 페이퍼는 실주문이 없어 그게 가장 최근 관측가.
    WHY halted=True 먼저: 포지션 유무와 관계없이 halt 플래그를 세워야 이후 process_bar가
    신규 진입을 차단한다. 청산 실패(예외)가 발생해도 halt 상태는 유지돼야 함.
    """
    state.halted = True
    if state.position is None:
        return None
    fill = close_fill(state.position, last_price, state.position.contracts, last_ts,
                      "panic", ctx.fee_bps, ctx.slippage_bps, ctx.ct_val)
    state.equity += fill.pnl_gross - fill.fee
    state.daily_realized_pnl += fill.pnl_gross - fill.fee
    state.pending_fills.append(fill)
    return _close_out(ctx, state, last_ts, [])


def _close_out(ctx: TickContext, state: PaperState, last_ts: int, funding_events):
    """완전 청산 마무리: funding 차감 + Trade 집계 + 포지션 비움. 청산된 Trade 반환.

    WHY funding 여기서 차감: funding은 포지션 전체 보유 기간에 걸친 비용이므로
    완전 청산 시점에 한 번만 정산. 부분익절마다 나눠 차감하면 계산 복잡성 증가
    및 분할 오차 위험 → 백테(run_backtest L144-148)와 동일 처리.
    """
    pos = state.position
    notional = pos.original_contracts * pos.entry * ctx.ct_val
    funding = funding_between(funding_events, notional, pos.side, pos.opened_ts, last_ts)
    state.equity -= funding
    state.daily_realized_pnl -= funding
    trade = build_trade(pos, state.pending_fills, last_ts, funding, state.open_fee)
    state.position = None
    state.open_fee = 0.0
    state.pending_fills = []
    return trade
