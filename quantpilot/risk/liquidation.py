"""OKX isolated margin 청산가 근사 + 손절-청산 거리 가드."""
from __future__ import annotations


class StopBeyondLiquidationError(Exception):
    """손절이 청산 안전구역 밖이라 진입을 거부할 때."""


def liquidation_price(entry: float, leverage: int, side: str, mmr: float = 0.005) -> float:
    """isolated margin 청산가 근사.
    long:  entry × (1 - 1/lev + mmr)
    short: entry × (1 + 1/lev - mmr)
    """
    if side == "long":
        return entry * (1 - 1 / leverage + mmr)
    return entry * (1 + 1 / leverage - mmr)


def assert_stop_within_liquidation(entry: float, stop: float, leverage: int,
                                   side: str, mmr: float = 0.005, frac: float = 0.7) -> None:
    """손절이 청산보다 멀면 StopBeyondLiquidationError.

    WHY: 손절가가 청산가보다 멀면 손절 전에 강제 청산당한다(스톱 무의미).
    안전 여유로 청산 거리의 frac(0.7) 안쪽에 손절이 있어야 한다.
    """
    liq = liquidation_price(entry, leverage, side, mmr)
    if abs(stop - entry) > abs(liq - entry) * frac:
        raise StopBeyondLiquidationError(
            f"stop={stop} 가 청산가={liq:.2f} 의 {frac:.0%} 안전구역 밖 (entry={entry})"
        )
