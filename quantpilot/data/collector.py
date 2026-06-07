"""증분 시장 데이터 수집 + idempotent upsert.

WHY: collector는 "무엇을/언제 받을지"를 결정하고, 거래소 통신 세부는
OKXClient에 위임한다. DB 쓰기는 unique 제약 기반 upsert로 중복을 무시.
"""
from __future__ import annotations


def drop_unclosed(rows: list[dict], timeframe_ms: int, now_ms: int) -> list[dict]:
    """아직 닫히지 않은(형성 중) 캔들을 제거.

    WHY: 형성 중인 봉은 OHLC가 계속 변함. 저장하면 재실행 때 같은 ts인데
    값이 달라져 idempotency가 깨지고 백테스트가 오염됨(lookahead bias).
    봉이 완전히 닫힌 것(ts + 봉길이 <= 현재)만 남긴다.
    """
    return [r for r in rows if r["ts"] + timeframe_ms <= now_ms]
