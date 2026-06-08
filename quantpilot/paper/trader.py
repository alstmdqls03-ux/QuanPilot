"""페이퍼 트레이더 — 실시간 루프(조립만). 매매 판단은 엔진/전략, 정지는 circuit_breaker,
영속은 store에 위임. process_bar는 네트워크 없이 결정적(테스트 가능).
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import pandas as pd

from quantpilot.backtest.costs import funding_between
from quantpilot.backtest.engine import _pnl, build_trade, check_exits, close_fill, open_position
from quantpilot.paper import store
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
        # WHY should_halt + state.halted 동시 체크:
        #   ① should_halt: 하루 실현손익이 -5% 한도를 넘으면 신규 베팅 차단.
        #   ② state.halted: panic_close 또는 이전 서킷 트립이 남긴 sticky 플래그.
        #      panic 시점의 daily_realized_pnl이 정상 범위였더라도 halted=True이면
        #      should_halt()는 False를 반환하므로, 플래그를 별도로 확인해야 함.
        #      UTC 자정 롤오버(step 0)가 halted를 False로 초기화하므로 같은 UTC 날
        #      내에서만 sticky — 다음 날 자동 해제.
        # 기존 포지션 손절/익절은 막지 않는다(사이징 불변식으로 이미 한정).
        if state.halted or should_halt(state.day_start_equity, state.daily_realized_pnl):
            state.halted = True  # 정지 유지(서킷 또는 panic). UTC 리셋 전까지 신규 진입 차단
        else:
            pos, open_fee = open_position(
                signal.side, bar, signal.suggested_stop, state.equity, ctx.ct_val,
                ctx.lot_sz, ctx.leverage, ctx.fee_bps, ctx.slippage_bps)
            if pos is not None:
                # WHY 진입 수수료 즉시 차감: 백테(run_backtest L164)와 동일. 수수료를
                # 청산 시점으로 미루면 equity가 일시 과대 계상 → 사이징 불변식 위반 가능.
                state.equity -= open_fee
                # WHY daily_realized_pnl에도 반영: 진입 수수료는 즉각 실현된 비용이므로
                # 일일 -5% 서킷 계산에 포함해야 함. 반영 안 하면 수수료 누적으로 실제
                # 자본 손실이 5%를 초과해도 서킷이 울리지 않는 불변식 누수 발생.
                # 또한 완전 청산 시 Trade.pnl_net = pnl_gross - (open_fee + close_fee) - funding
                # 이므로 daily_realized_pnl의 trade 기여분이 pnl_net과 정확히 일치해야 함.
                state.daily_realized_pnl -= open_fee
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


def run_one_tick(ctx: TickContext, state: PaperState):
    """1틱: (client 있으면)폴링 → 최신 닫힌 봉 로드 → 새 봉만 process_bar → 영속.

    엔진 백테와 동일하게 결정 시작점은 봉 인덱스 lookback(첫 lookback개는 warmup window).

    WHY engine-parity 룰: backtest.run_backtest가 iloc >= lookback에서만 신호를 내므로
    페이퍼도 동일 기준을 지켜야 백테 결과와 비교 가능(같은 전략·같은 데이터 → 같은 신호).
    WHY collect_ohlcv만 2일: 증분 폴링이므로 최근 2일치만 가져오면 충분. 더 길게 잡으면
    불필요한 API 호출·upsert 비용이 증가.
    """
    from sqlalchemy import select

    from quantpilot.backtest.data_loader import load_candles_df
    from quantpilot.data.collector import collect_ohlcv
    from quantpilot.data.models import FundingRate

    if ctx.client is not None:
        # 증분 폴링. 실패는 호출부(run_loop)가 try로 흡수 → 루프 생존.
        collect_ohlcv(ctx.session, ctx.client, ctx.symbol, ctx.timeframe,
                      days=2, now_ms=int(time.time() * 1000))

    df = load_candles_df(ctx.session, ctx.symbol, ctx.timeframe)
    if df.empty:
        return state, []

    funding_events = [
        (f.ts, f.funding_rate) for f in ctx.session.execute(
            select(FundingRate).where(FundingRate.symbol == ctx.symbol)
            .order_by(FundingRate.ts)).scalars().all()]

    lookback = ctx.strategy.lookback
    last = state.last_processed_bar_ts
    all_trades = []
    equity_points: list[tuple[int, float]] = []
    for pos_iloc in range(len(df)):
        t = int(df.index[pos_iloc])
        if last is not None and t <= last:
            continue                      # 이미 처리한 봉(중복 방지)
        if pos_iloc < lookback:
            # WHY 진행만 하고 process_bar 안 함: warmup window가 부족하면 지표 계산
            # 불가 → 신호 오류. 백테(run_backtest)와 동일하게 lookback개까지는 스킵.
            state.last_processed_bar_ts = t   # warmup: 진행만(곡선 기록 X)
            continue
        window = df.iloc[pos_iloc - lookback + 1: pos_iloc + 1]
        bar = {"ts": t, "open": float(df.at[t, "open"]), "high": float(df.at[t, "high"]),
               "low": float(df.at[t, "low"]), "close": float(df.at[t, "close"])}
        state, trades = process_bar(ctx, state, bar, window, funding_events)
        all_trades.extend(trades)
        # equity 포인트 = 실현 + 미실현(그 봉 종가 기준). 백테 equity_curve와 동일 의미.
        # WHY 미실현 포함: 보유 중 drawdown이 곡선에 반영돼야 MaxDD/Sharpe가 백테와 같은 잣대.
        unreal = (_pnl(state.position.side, state.position.entry, bar["close"],
                       state.position.contracts, ctx.ct_val)
                  if state.position is not None else 0.0)
        equity_points.append((t, state.equity + unreal))

    # WHY persist_tick(단일 commit): 거래·equity·last_processed_bar_ts를 같은 트랜잭션에
    # 묶어야 틱 도중 강제 종료돼도 '거래는 적재됐는데 진행위치는 안 밀린' 불일치가 없다.
    # 불일치 상태로 재시작하면 같은 봉을 재처리해 거래가 중복 적재된다(append-only라 못 거름).
    store.persist_tick(ctx.session, ctx.run_key, state, all_trades, equity_points)
    return state, all_trades


def run_loop(ctx: TickContext, state: PaperState):
    """무한 루프(얇은 래퍼). 폴링 실패는 흡수하고 다음 틱에서 재시도 → 루프 생존.

    WHY 오류 흡수: 네트워크 순단이나 일시적 OKX API 오류로 루프가 죽으면 안 됨.
    에러 로그만 남기고 다음 poll_seconds 뒤에 재시도. 심각한 계정 오류(권한 등)는
    kill switch(panic_close)나 운영자 개입으로 처리 — 여기서 판별하지 않음.
    """
    while True:
        try:
            state, _ = run_one_tick(ctx, state)
        except Exception as e:  # noqa: BLE001  운영 중 단발 오류로 죽지 않게
            print(f"[paper] tick 오류(건너뜀, 상태 재로드): {e}", file=sys.stderr)
            try:
                ctx.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            # WHY 재로드: 실패한 틱에서 in-memory state가 더럽혀졌을 수 있음(equity·진행위치
            # 전진, DB 미커밋). persist_tick은 틱 끝에서만 commit하므로 예외 발생 시 DB는
            # 이전 커밋 상태 그대로. 마지막 커밋 상태로 되돌려 다음 틱이 깨끗한 상태에서
            # 재처리 → 중복/유실 방지.
            state = store.load_state(ctx.session, ctx.run_key, symbol=ctx.symbol,
                                     timeframe=ctx.timeframe, strategy=state.strategy,
                                     capital=state.day_start_equity,
                                     day_start_ts=state.day_start_ts)
        time.sleep(ctx.poll_seconds)
