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


from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from quantpilot.data.models import Candle, FundingRate


def last_candle_ts(session, exchange: str, symbol: str, timeframe: str) -> int | None:
    """이 (거래소,심볼,봉)의 마지막 캔들 ts. 없으면 None.

    WHY: 증분 수집의 시작점. 다음 수집은 여기 다음 봉부터.
    """
    stmt = select(func.max(Candle.ts)).where(
        Candle.exchange == exchange,
        Candle.symbol == symbol,
        Candle.timeframe == timeframe,
    )
    return session.execute(stmt).scalar_one()


def upsert_candles(session, exchange: str, symbol: str, timeframe: str,
                   rows: list[dict], now_ms: int) -> int:
    """캔들 배치를 upsert. 신규 삽입 개수를 반환.

    WHY on_conflict_do_nothing: unique 제약(거래소,심볼,봉,ts)에 걸리는
    중복은 조용히 무시 → 재실행해도 안전(idempotent).
    신규 개수는 삽입 전후 카운트 차이로 계산(executemany rowcount는 비신뢰).
    """
    if not rows:
        return 0

    def _count() -> int:
        stmt = select(func.count()).select_from(Candle).where(
            Candle.exchange == exchange,
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
        return session.execute(stmt).scalar_one()

    before = _count()
    payload = [
        {
            "exchange": exchange, "symbol": symbol, "timeframe": timeframe,
            "ts": r["ts"], "open": r["open"], "high": r["high"],
            "low": r["low"], "close": r["close"], "volume": r["volume"],
            "inserted_at": now_ms,
        }
        for r in rows
    ]
    stmt = sqlite_insert(Candle).values(payload).on_conflict_do_nothing(
        index_elements=["exchange", "symbol", "timeframe", "ts"]
    )
    session.execute(stmt)
    session.commit()
    return _count() - before


def last_funding_ts(session, exchange: str, symbol: str) -> int | None:
    stmt = select(func.max(FundingRate.ts)).where(
        FundingRate.exchange == exchange,
        FundingRate.symbol == symbol,
    )
    return session.execute(stmt).scalar_one()


def upsert_funding(session, exchange: str, symbol: str,
                   rows: list[dict], now_ms: int) -> int:
    """funding 배치를 upsert. 신규 삽입 개수 반환."""
    if not rows:
        return 0

    def _count() -> int:
        stmt = select(func.count()).select_from(FundingRate).where(
            FundingRate.exchange == exchange,
            FundingRate.symbol == symbol,
        )
        return session.execute(stmt).scalar_one()

    before = _count()
    payload = [
        {"exchange": exchange, "symbol": symbol, "ts": r["ts"],
         "funding_rate": r["funding_rate"], "inserted_at": now_ms}
        for r in rows
    ]
    stmt = sqlite_insert(FundingRate).values(payload).on_conflict_do_nothing(
        index_elements=["exchange", "symbol", "ts"]
    )
    session.execute(stmt)
    session.commit()
    return _count() - before
