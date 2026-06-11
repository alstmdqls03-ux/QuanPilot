"""ZigZag 확정 피벗 — confluence 시그널(파동·매물대·다이버전스)의 공통 기반.

WHY '확정(confirmed)' 개념: 잠정 극점은 미래 봉이 갱신할 수 있어 그대로 쓰면
룩어헤드다. 극점에서 ATR×k 이상 반대 이동이 봉마감으로 확인된 시점(confirmed_ts)
이후에만 피벗을 노출한다 → i봉까지 데이터로 계산한 결과가 전체 데이터 계산의
prefix와 항상 일치(룩어헤드-프리 테스트로 강제).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantpilot.strategy.indicators import atr


@dataclass(frozen=True)
class Pivot:
    ts: int            # 극점이 발생한 봉 ts
    price: float       # 극점 가격 (H는 high, L은 low)
    kind: str          # "H" | "L"
    confirmed_ts: int  # 이 봉 마감에 확정됨 — 소비자는 confirmed_ts <= now만 사용


def confirmed_pivots(df: pd.DataFrame, atr_k: float = 3.0,
                     atr_period: int = 14) -> list[Pivot]:
    """ZigZag: 잠정 극점에서 종가가 ATR×k 이상 반대로 가면(봉마감) 극점 확정.

    WHY 종가 기준 확정: 장중 스파이크(휩소)로 피벗이 확정되는 것을 막는다(V4).
    WHY ATR warmup 전 확정 금지: 초기 ATR(Wilder ewm)은 불안정해 임계가 무의미.
    """
    if len(df) < atr_period + 1:
        return []
    a = atr(df["high"], df["low"], df["close"], atr_period)
    ts_arr = list(df.index)
    out: list[Pivot] = []
    hi_px, hi_ts = float(df["high"].iloc[0]), ts_arr[0]
    lo_px, lo_ts = float(df["low"].iloc[0]), ts_arr[0]
    direction: str | None = None   # None=미정, "up"=고점 추적 중, "down"=저점 추적 중
    for i in range(len(df)):
        ts = ts_arr[i]
        hi, lo = float(df["high"].iloc[i]), float(df["low"].iloc[i])
        close = float(df["close"].iloc[i])
        if direction in (None, "up") and hi >= hi_px:
            hi_px, hi_ts = hi, ts
        if direction in (None, "down") and lo <= lo_px:
            lo_px, lo_ts = lo, ts
        if i < atr_period:
            continue
        thr = float(a.iloc[i]) * atr_k
        if direction in (None, "up") and hi_px - close >= thr:
            out.append(Pivot(ts=hi_ts, price=hi_px, kind="H", confirmed_ts=ts))
            direction = "down"
            lo_px, lo_ts = lo, ts
        elif direction in (None, "down") and close - lo_px >= thr:
            out.append(Pivot(ts=lo_ts, price=lo_px, kind="L", confirmed_ts=ts))
            direction = "up"
            hi_px, hi_ts = hi, ts
    return out
