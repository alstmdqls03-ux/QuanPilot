"""DB 캔들 → pandas DataFrame + gap(구멍) 감지 게이트."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from quantpilot.data.models import Candle
from quantpilot.timeframes import timeframe_to_ms


def load_candles_df(session, symbol: str, timeframe: str,
                    start_ms: int | None = None, end_ms: int | None = None,
                    exchange: str = "okx") -> pd.DataFrame:
    """캔들을 ts 오름차순 DataFrame으로. index=ts(ms), cols=OHLCV."""
    stmt = select(Candle).where(
        Candle.exchange == exchange, Candle.symbol == symbol,
        Candle.timeframe == timeframe,
    )
    if start_ms is not None:
        stmt = stmt.where(Candle.ts >= start_ms)
    if end_ms is not None:
        stmt = stmt.where(Candle.ts <= end_ms)
    stmt = stmt.order_by(Candle.ts)
    rows = session.execute(stmt).scalars().all()
    df = pd.DataFrame(
        [{"ts": c.ts, "open": c.open, "high": c.high, "low": c.low,
          "close": c.close, "volume": c.volume} for c in rows]
    )
    if not df.empty:
        df = df.set_index("ts")
    else:
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df.index.name = "ts"
    return df


def detect_gaps(ts_list: list[int], timeframe_ms: int) -> tuple[int, list[tuple[int, int]]]:
    """연속 ts 사이 간격이 timeframe_ms보다 크면 누락. (누락봉수, [(start,end),...]) 반환.

    WHY: 백테스트 전 데이터 구멍을 감지. RSI는 연속 봉 가정이라 구멍이 결과를 왜곡.
    감지·경고만; 메우기는 collector.heal_gaps가 담당.
    """
    gaps = 0
    ranges: list[tuple[int, int]] = []
    for a, b in zip(ts_list, ts_list[1:]):
        step = b - a
        if step > timeframe_ms:
            missing = step // timeframe_ms - 1
            gaps += missing
            ranges.append((a + timeframe_ms, b - timeframe_ms))
    return gaps, ranges


def closed_htf_slice(htf_df: pd.DataFrame, now_ts: int, htf_ms: int,
                     ltf_ms: int) -> pd.DataFrame:
    """LTF 봉(ts=now_ts) 마감 시점에 '이미 마감된' HTF 봉만 반환.

    WHY: 캔들 ts는 봉 '시작' 시각. LTF 봉 마감 = now_ts+ltf_ms, HTF 봉 마감 =
    ts+htf_ms. 마감 안 된 HTF 봉을 보면 룩어헤드(미래 정보)가 된다.
    """
    return htf_df[htf_df.index + htf_ms <= now_ts + ltf_ms]


class DataGapError(Exception):
    """데이터 구멍 또는 부재로 백테스트를 막을 때."""


def load_with_gap_check(
    session,
    symbol: str,
    timeframe: str,
    allow_gaps: bool,
    start_ms: int | None = None,
    end_ms: int | None = None,
):
    """DataFrame 로드 + gap 검사. 반환 (df, gaps, ranges).
    allow_gaps=False이고 gap>0이면 DataGapError.

    WHY start_ms/end_ms 파라미터: walk-forward 평가에서 전략을 여러 구간에 독립
    적용하려면 같은 DB에서 ts 구간을 잘라 백테스트해야 한다. 기본값 None=기존 전체
    로드 동작이므로 기존 호출 코드를 바꾸지 않아도 된다.
    """
    df = load_candles_df(session, symbol, timeframe, start_ms=start_ms, end_ms=end_ms)
    if df.empty:
        raise DataGapError(f"{symbol} {timeframe} 데이터가 없음. 먼저 'quantpilot collect' 실행.")
    tf_ms = timeframe_to_ms(timeframe)
    gaps, ranges = detect_gaps(list(df.index), tf_ms)
    if gaps > 0 and not allow_gaps:
        raise DataGapError(
            f"{timeframe} {gaps}개 봉 누락(구간 {len(ranges)}곳). "
            f"--allow-gaps로 무시하거나 데이터를 다시 수집하세요."
        )
    return df, gaps, ranges
