"""일일 손실 서킷 브레이커 (순수 함수).

WHY 순수: I/O·시계 의존 없이 인자만으로 판정 → 경계값 테스트가 자명하고 결정적.
영속(halted 플래그)·시계는 호출부(trader)가 담당.
"""
from __future__ import annotations

_DAY_MS = 86_400_000


def should_halt(day_start_equity: float, daily_realized_pnl: float,
                threshold: float = 0.05) -> bool:
    """하루 실현 손익이 그날 시작 자본의 -threshold(기본 -5%)에 닿으면 True(신규 진입 차단).

    WHY 실현 기준: 미실현은 봉마다 출렁여 과민 정지. 닫힌 손익만으로 일일 한도 판정.
    보유 포지션의 손절/익절은 막지 않는다(이미 5% 사이징 불변식으로 한정). 차단은 *새 베팅*만.
    """
    return daily_realized_pnl <= -threshold * day_start_equity


def is_new_utc_day(prev_ts_ms: int, cur_ts_ms: int) -> bool:
    """두 ms epoch ts가 서로 다른 UTC 날짜면 True → 일일 카운터/halt 리셋 신호.

    WHY UTC: funding·거래소 일일 경계가 UTC. 로컬 타임존 의존 제거(결정적).
    """
    return prev_ts_ms // _DAY_MS != cur_ts_ms // _DAY_MS
