"""증분 시장 데이터 수집 + idempotent upsert.

WHY: collector는 "무엇을/언제 받을지"를 결정하고, 거래소 통신 세부는
OKXClient에 위임한다. DB 쓰기는 unique 제약 기반 upsert로 중복을 무시.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from quantpilot.data.models import Candle, FundingRate, Instrument
from quantpilot.exchange.instruments import parse_instrument
from quantpilot.timeframes import timeframe_to_ms

DAY_MS = 86_400_000


def drop_unclosed(rows: list[dict], timeframe_ms: int, now_ms: int) -> list[dict]:
    """아직 닫히지 않은(형성 중) 캔들을 제거.

    WHY: 형성 중인 봉은 OHLC가 계속 변함. 저장하면 재실행 때 같은 ts인데
    값이 달라져 idempotency가 깨지고 백테스트가 오염됨(lookahead bias).
    봉이 완전히 닫힌 것(ts + 봉길이 <= 현재)만 남긴다.
    """
    return [r for r in rows if r["ts"] + timeframe_ms <= now_ms]


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


def collect_ohlcv(session, client, symbol: str, timeframe: str, days: int,
                  now_ms: int, exchange: str = "okx", page_limit: int = 100) -> dict:
    """OHLCV 증분 수집.

    흐름: 시작점 결정 → 페이지네이션 → 미완성 봉 제거 → upsert → 요약.
    WHY now_ms 주입: 테스트에서 시간을 고정해 결정적으로 만들기 위함.
    """
    tf_ms = timeframe_to_ms(timeframe)

    last = last_candle_ts(session, exchange, symbol, timeframe)
    # WHY: 있으면 다음 봉부터(증분), 없으면 days일 전부터(최초 백필).
    since = (last + tf_ms) if last is not None else (now_ms - days * DAY_MS)

    total_inserted = 0
    cursor = since
    while cursor < now_ms:
        batch = client.fetch_ohlcv(symbol, timeframe, since_ms=cursor, limit=page_limit)
        if not batch:
            break
        # 이미 가진 마지막 ts 이하인 행이 섞여 와도 upsert가 걸러줌.
        closed = drop_unclosed(batch, tf_ms, now_ms)
        total_inserted += upsert_candles(session, exchange, symbol, timeframe, closed, now_ms)
        # 다음 커서: 받은 마지막 봉의 다음 봉.
        cursor = batch[-1]["ts"] + tf_ms
        # WHY batch[-1] 기준: drop_unclosed로 closed가 비어도 커서는 전진해야
        # 무한 루프를 피함(미완성 봉만 남은 마지막 페이지).
        if len(batch) < page_limit:
            break

    return {"symbol": symbol, "timeframe": timeframe, "inserted": total_inserted}


def collect_funding(session, client, symbol: str, days: int, now_ms: int,
                    exchange: str = "okx", page_limit: int = 100) -> dict:
    """funding rate 증분 수집 (8시간 주기). OHLCV와 동일한 증분 패턴."""
    eight_h = 8 * 3_600_000
    last = last_funding_ts(session, exchange, symbol)
    since = (last + eight_h) if last is not None else (now_ms - days * DAY_MS)

    total_inserted = 0
    cursor = since
    while cursor < now_ms:
        batch = client.fetch_funding(symbol, since_ms=cursor, limit=page_limit)
        if not batch:
            break
        total_inserted += upsert_funding(session, exchange, symbol, batch, now_ms)
        cursor = batch[-1]["ts"] + eight_h
        if len(batch) < page_limit:
            break

    return {"symbol": symbol, "inserted": total_inserted}


def upsert_instruments(session, client, now_ms: int, exchange: str = "okx") -> int:
    """거래소 마켓 전체를 받아 Instrument 캐시 upsert. 처리한 행 수 반환.

    WHY: Week 2 sizing이 ct_val을 읽으므로 수집 단계에서 미리 캐시.
    파싱 실패하는 마켓(필드 누락)은 건너뜀.
    """
    markets = client.load_markets()
    count = 0
    for market in markets.values():
        try:
            inst = parse_instrument(market, exchange=exchange)
        except (KeyError, TypeError, ValueError):
            continue  # ctVal 등이 없는 마켓(현물 등)은 스킵
        stmt = sqlite_insert(Instrument).values(
            **inst, updated_at=now_ms
        ).on_conflict_do_update(
            index_elements=["exchange", "symbol"],
            set_={
                "ct_val": inst["ct_val"], "ct_val_ccy": inst["ct_val_ccy"],
                "lot_sz": inst["lot_sz"], "min_sz": inst["min_sz"],
                "tick_sz": inst["tick_sz"], "updated_at": now_ms,
            },
        )
        # WHY on_conflict_do_update: 명세는 바뀔 수 있으니(틱사이즈 등)
        # 캔들과 달리 최신값으로 갱신.
        session.execute(stmt)
        count += 1
    session.commit()
    return count
