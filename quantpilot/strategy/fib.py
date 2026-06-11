"""피보나치 되돌림(S4) — 직전 '확정' 파동 기준.

WHY 확정 파동만: 진행 중 파동에 걸면 끝점이 계속 변해 레벨이 흔들린다(룩어헤드).
원문 승계: 주시 레벨 0.382/0.5/0.618, 진입 존 = 0.5~0.618.
"""
from __future__ import annotations

from quantpilot.strategy.pivots import Pivot

LEVELS = (0.382, 0.5, 0.618)


def last_wave(pivots: list[Pivot], now_ts: int) -> tuple[float, float] | None:
    """now_ts 기준 확정된 마지막 파동 (시작가, 끝가). 피벗 2개 미만이면 None."""
    sel = [p for p in pivots if p.confirmed_ts <= now_ts]
    if len(sel) < 2:
        return None
    return (sel[-2].price, sel[-1].price)


def fib_levels(start: float, end: float) -> dict[float, float]:
    """파동(start→end)의 되돌림 레벨. 레벨 r = end + (start-end)*r."""
    return {r: end + (start - end) * r for r in LEVELS}


def in_entry_zone(price: float, levels: dict[float, float]) -> bool:
    """진입 존 = 0.5~0.618 레벨 사이(파동 방향 무관하게 min/max로 판정)."""
    lo, hi = sorted((levels[0.5], levels[0.618]))
    return lo <= price <= hi
