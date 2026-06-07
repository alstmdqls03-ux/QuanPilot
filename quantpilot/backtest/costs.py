"""백테스트 비용: slippage / fee / funding. 전부 순수 함수."""
from __future__ import annotations


def apply_slippage(price: float, slippage_bps: float, side: str) -> float:
    """체결가를 불리한 쪽으로 slippage_bps 만큼 이동.
    buy(매수 진입/숏청산)는 위로, sell(매도 진입/롱청산)은 아래로.
    """
    adj = price * (slippage_bps / 10000.0)
    return price + adj if side == "buy" else price - adj


def fee_for(notional: float, fee_bps: float) -> float:
    """체결 수수료 = notional × fee_bps. (notional = contracts × price × ct_val)"""
    return abs(notional) * (fee_bps / 10000.0)


def funding_between(events: list[tuple[int, float]], notional: float, side: str,
                    open_ts: int, close_ts: int) -> float:
    """[open_ts, close_ts) 구간에 든 funding 이벤트를 합산해 지불액 반환.

    long은 +funding_rate면 지불(+부호), short은 반대.
    events = [(ts, funding_rate), ...].
    WHY: 8h마다 포지션 notional × funding_rate. 롱이 펀딩 양수일 때 숏에게 지불.
    """
    sign = 1.0 if side == "long" else -1.0
    total = 0.0
    for ts, rate in events:
        if open_ts <= ts < close_ts:
            total += sign * notional * rate
    return total
