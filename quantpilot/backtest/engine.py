"""event-driven 백테스트 엔진. per-bar step + 배치 루프.

per-bar step(check_exits)은 Week 3 페이퍼가 그대로 재사용(바깥 루프만 교체).
"""
from __future__ import annotations

from quantpilot.backtest.costs import apply_slippage, fee_for
from quantpilot.backtest.models import Fill, Position


def _pnl(side: str, entry: float, exit_price: float, contracts: int, ct_val: float) -> float:
    """gross 손익(USDT). long은 (exit-entry), short은 (entry-exit)."""
    diff = (exit_price - entry) if side == "long" else (entry - exit_price)
    return diff * contracts * ct_val


def _close_fill(pos: Position, raw_price: float, contracts: int, ts: int,
                reason: str, fee_bps: float, slippage_bps: float, ct_val: float) -> Fill:
    # 청산 방향: long 청산은 sell(아래로 불리), short 청산은 buy(위로 불리)
    side = "sell" if pos.side == "long" else "buy"
    price = apply_slippage(raw_price, slippage_bps, side)
    notional = contracts * price * ct_val
    fee = fee_for(notional, fee_bps)
    pnl = _pnl(pos.side, pos.entry, price, contracts, ct_val)
    return Fill(ts=ts, price=price, contracts=contracts, fee=fee, reason=reason, pnl_gross=pnl)


def check_exits(pos: Position, bar: dict, fee_bps: float, slippage_bps: float,
                ct_val: float) -> tuple[Position | None, list[Fill]]:
    """이 봉에서 손절/분할익절 체결 판정. (남은포지션 or None, fills) 반환.

    WHY '손절 먼저': 한 봉이 stop과 target을 동시에 건드리면 봉 내부 순서를 모름.
    보수적으로 손절이 먼저 체결됐다고 가정 → 백테스트 over-optimism 방지.
    """
    high, low = bar["high"], bar["low"]

    # 1) 손절 먼저: long은 low≤stop, short은 high≥stop
    stop_hit = (pos.side == "long" and low <= pos.stop) or \
               (pos.side == "short" and high >= pos.stop)
    if stop_hit:
        fill = _close_fill(pos, pos.stop, pos.contracts, bar["ts"], "stop",
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
        fills.append(_close_fill(pos, price, qty, bar["ts"], f"tp{idx}",
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
    return pos, fills
