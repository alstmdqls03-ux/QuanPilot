"""event-driven 백테스트 엔진. per-bar step + 배치 루프.

per-bar step(check_exits)은 Week 3 페이퍼가 그대로 재사용(바깥 루프만 교체).
"""
from __future__ import annotations

from quantpilot.backtest.costs import apply_slippage, fee_for, funding_between
from quantpilot.backtest.models import BacktestResult, Fill, Position, Trade
from quantpilot.risk.liquidation import StopBeyondLiquidationError, assert_stop_within_liquidation
from quantpilot.risk.sizing import InsufficientCapitalError, calculate_position_size
from quantpilot.risk.take_profit import build_targets


def _pnl(side: str, entry: float, exit_price: float, contracts: int, ct_val: float) -> float:
    """gross 손익(USDT). long은 (exit-entry), short은 (entry-exit)."""
    diff = (exit_price - entry) if side == "long" else (entry - exit_price)
    return diff * contracts * ct_val


def close_fill(pos: Position, raw_price: float, contracts: int, ts: int,
               reason: str, fee_bps: float, slippage_bps: float, ct_val: float) -> Fill:
    # 청산 방향: long 청산은 sell(아래로 불리), short 청산은 buy(위로 불리)
    side = "sell" if pos.side == "long" else "buy"
    price = apply_slippage(raw_price, slippage_bps, side)
    notional = contracts * price * ct_val
    fee = fee_for(notional, fee_bps)
    pnl = _pnl(pos.side, pos.entry, price, contracts, ct_val)
    return Fill(ts=ts, price=price, contracts=contracts, fee=fee, reason=reason, pnl_gross=pnl)


def build_trade(pos: Position, fills: list[Fill], last_ts: int,
                funding: float, open_fee: float) -> Trade:
    """한 포지션의 fills를 Trade로 집계(보고용). 백테·페이퍼 공용.

    WHY 공용: 백테와 페이퍼가 동일한 Trade 구성을 써야 parity가 성립.
    equity는 호출부에서 체결 즉시 반영되므로 여기선 보고 집계만.
    """
    gross = sum(f.pnl_gross for f in fills)
    fees = open_fee + sum(f.fee for f in fills)
    sold = sum(f.contracts for f in fills)
    avg_exit = sum(f.price * f.contracts for f in fills) / sold if sold else pos.entry
    return Trade(side=pos.side, entry=pos.entry, exit=avg_exit,
                 contracts=pos.original_contracts, pnl_gross=gross, fees=fees,
                 funding=funding, pnl_net=gross - fees - funding,
                 opened_ts=pos.opened_ts, closed_ts=last_ts,
                 reason=fills[-1].reason if fills else "exit_signal")


def check_exits(pos: Position, bar: dict, fee_bps: float, slippage_bps: float,
                ct_val: float, be_trail_after_tp1: bool = False) -> tuple[Position | None, list[Fill]]:
    """이 봉에서 손절/분할익절 체결 판정. (남은포지션 or None, fills) 반환.

    WHY '손절 먼저': 한 봉이 stop과 target을 동시에 건드리면 봉 내부 순서를 모름.
    보수적으로 손절이 먼저 체결됐다고 가정 → 백테스트 over-optimism 방지.
    """
    high, low = bar["high"], bar["low"]

    # 1) 손절 먼저: long은 low≤stop, short은 high≥stop
    stop_hit = (pos.side == "long" and low <= pos.stop) or \
               (pos.side == "short" and high >= pos.stop)
    if stop_hit:
        fill = close_fill(pos, pos.stop, pos.contracts, bar["ts"], "stop",
                          fee_bps, slippage_bps, ct_val)
        return None, [fill]

    # 2) 분할 익절: 가까운 타겟부터 봉이 닿았나 (long은 high≥target, short은 low≤target)
    fills: list[Fill] = []
    remaining = list(pos.targets_remaining)
    idx = 1
    contracts_left = pos.contracts
    for price, frac in pos.targets_remaining:
        hit = (pos.side == "long" and high >= price) or \
              (pos.side == "short" and low <= price)
        if not hit:
            idx += 1
            continue
        qty = int(round(pos.original_contracts * frac))
        qty = min(qty, contracts_left)
        if qty <= 0:
            remaining.remove((price, frac))
            idx += 1
            continue
        fills.append(close_fill(pos, price, qty, bar["ts"], f"tp{idx}",
                                fee_bps, slippage_bps, ct_val))
        contracts_left -= qty
        remaining.remove((price, frac))
        idx += 1

    if not fills:
        return pos, []
    if contracts_left <= 0:
        return None, fills
    pos.contracts = contracts_left
    pos.targets_remaining = remaining
    # WHY BE 트레일: BOT-SPEC §7.1 — 50% 익절(TP1) 후 손절을 본전으로 이동해
    # '이긴 거래를 진 거래로 만들지 않는다'. 같은 봉에서는 손절 먼저 검사가 이미
    # 끝났으므로 이동된 stop은 다음 봉부터 적용된다(보수 가정 유지).
    if be_trail_after_tp1 and any(f.reason == "tp1" for f in fills):
        pos.stop = pos.entry
    return pos, fills


def open_position(side: str, bar: dict, stop: float, capital: float, ct_val: float,
                  lot_sz: float, leverage: int, fee_bps: float, slippage_bps: float,
                  targets: list[tuple[float, float]] | None = None):
    """진입 시도. 사이징/청산가드 통과 시 Position 반환, 아니면 (None, 0fee)."""
    raw_entry = bar["close"]
    buy_side = "buy" if side == "long" else "sell"
    entry = apply_slippage(raw_entry, slippage_bps, buy_side)
    try:
        assert_stop_within_liquidation(entry, stop, leverage, side)
        # slippage_bps 전달: 사이징이 손절 슬리피지를 5% 예산에 반영해야 불변식 유지.
        sizing = calculate_position_size(capital, 0.05, entry, stop, ct_val, lot_sz,
                                         leverage=leverage, fee_bps=fee_bps,
                                         slippage_bps=slippage_bps)
    except (StopBeyondLiquidationError, InsufficientCapitalError):
        return None, 0.0
    # WHY 주입 허용: confluence는 구조 기반 타깃(첫 매물대/피보)을 쓴다. None이면
    # 기존 R-배수 사다리 그대로 → 기존 전략(rsi-mr) 거동 변화 0.
    if targets is None:
        targets = build_targets(entry, stop, side)
    pos = Position(side=side, entry=entry, contracts=sizing.contracts, stop=stop,
                   targets_remaining=targets, opened_ts=bar["ts"],
                   original_contracts=sizing.contracts)
    entry_fee = fee_for(sizing.contracts * entry * ct_val, fee_bps)
    return pos, entry_fee


def run_backtest(candles, strategy, capital, ct_val, lot_sz, leverage,
                 fee_bps, slippage_bps, funding_events, oos_split_ts) -> BacktestResult:
    """봉 하나씩 재생하며 백테스트. funding_events=[(ts,rate),...]."""
    equity = capital
    position: Position | None = None
    open_fee = 0.0
    trades: list[Trade] = []
    curve: list[tuple[int, float]] = []
    pending_fills: list[Fill] = []
    rows = candles.reset_index().to_dict("records")  # ts 포함 dict 리스트

    for i in range(strategy.lookback, len(rows)):
        bar = rows[i]
        window = candles.iloc[i - strategy.lookback + 1: i + 1]

        # 1) 열린 포지션 → 손절/익절 체결. 체결분은 즉시 equity에 실현(부분익절 포함).
        #    WHY 즉시 실현: 부분익절 실현손익을 청산까지 미루면 그 봉에서 equity 곡선이
        #    가짜로 하락(체결분이 미실현에서 빠지는데 실현엔 안 더해짐) → Sharpe/MaxDD 왜곡.
        if position is not None:
            position2, fills = check_exits(position, bar, fee_bps, slippage_bps, ct_val,
                                           be_trail_after_tp1=getattr(strategy, "be_trail_after_tp1", False))
            if fills:
                equity += sum(f.pnl_gross for f in fills) - sum(f.fee for f in fills)
                pending_fills.extend(fills)
            if position2 is None:  # 완전 청산됨
                notional = position.original_contracts * position.entry * ct_val
                funding = funding_between(funding_events, notional, position.side,
                                          position.opened_ts, bar["ts"])
                equity -= funding
                trades.append(build_trade(position, pending_fills, bar["ts"], funding, open_fee))
                position, open_fee, pending_fills = None, 0.0, []
            else:
                position = position2

        # 2) 전략 신호 (market-on-close 모델)
        #    WHY 같은 봉 진입 OK: 신호는 '닫힌 봉 i'의 OHLC로 계산되고, 진입은 그 봉의
        #    종가에 체결된다. 봉이 닫힌 뒤 종가로 행동 → look-ahead 아님(미래 데이터 미사용).
        signal = strategy.generate_signal(window, position)

        # 3) 신호 처리
        if signal.side in ("long", "short") and position is None:
            position, open_fee = open_position(
                signal.side, bar, signal.suggested_stop, equity, ct_val, lot_sz,
                leverage, fee_bps, slippage_bps,
                targets=signal.meta.get("targets"))
            if position is not None:
                equity -= open_fee  # 진입 수수료 즉시 실현
            pending_fills = []
        elif signal.side == "exit" and position is not None:
            fill = close_fill(position, bar["close"], position.contracts, bar["ts"],
                              "exit_signal", fee_bps, slippage_bps, ct_val)
            equity += fill.pnl_gross - fill.fee
            pending_fills.append(fill)
            notional = position.original_contracts * position.entry * ct_val
            funding = funding_between(funding_events, notional, position.side,
                                      position.opened_ts, bar["ts"])
            equity -= funding
            trades.append(build_trade(position, pending_fills, bar["ts"], funding, open_fee))
            position, open_fee, pending_fills = None, 0.0, []

        # 4) equity 곡선 (실현분 equity + 잔여 계약 미실현)
        unreal = 0.0
        if position is not None:
            unreal = _pnl(position.side, position.entry, bar["close"],
                          position.contracts, ct_val)
        curve.append((bar["ts"], equity + unreal))

    return BacktestResult(trades=trades, equity_curve=curve, split_ts=int(oos_split_ts))
