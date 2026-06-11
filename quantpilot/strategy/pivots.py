"""ZigZag 확정 피벗 — confluence 시그널(파동·매물대·다이버전스)의 공통 기반.

WHY '확정(confirmed)' 개념: 잠정 극점은 미래 봉이 갱신할 수 있어 그대로 쓰면
룩어헤드다. 극점에서 ATR×k 이상 반대 이동이 봉마감으로 확인된 시점(confirmed_ts)
이후에만 피벗을 노출한다 → i봉까지 데이터로 계산한 결과가 전체 데이터 계산의
prefix와 항상 일치(룩어헤드-프리 테스트로 강제).

소비자 주의: 거대 봉에서는 H/L 극점 설정과 확정이 같은 봉에서 동시에 발생해
confirmed_ts == ts인 피벗이 나올 수 있다. 봉마감 시 그 봉 high/low는 기지값이므로
룩어헤드가 아니다.
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
    WHY thr>0 게이트: 완전 횡보(ATR=0)에서 thr=0이면 hi_px-close>=0이 항상 참이어서
    매 봉 동일가 피벗이 폭주한다 — 의미 없는 신호이므로 차단.
    WHY numpy 사전 추출: 루프 안에서 iloc[i]를 매 봉 호출하면 Pandas 인덱싱
    오버헤드가 봉 수에 비례해 13× 느려진다. 배열로 미리 내려 한 번에 접근.
    WHY 블라인드 윈도우 반대 극값 추적: H 확정 시 lo_px를 확정봉 low로 리셋하면
    극점봉(hi_ts)과 확정봉 사이의 더 깊은 low(wick 포함)가 버려진다.
    hi 후보 추적 중에 opp_lo_px/opp_lo_ts로 그 구간의 최소 low를 함께 유지하다가
    H 확정 시 lo_px = opp_lo_px로 시딩 — 모두 과거 봉만 사용하므로 룩어헤드 없음.
    """
    if len(df) < atr_period + 1:
        return []
    a = atr(df["high"], df["low"], df["close"], atr_period)

    # [M-2] numpy 사전 추출: 루프마다 .iloc[i] 호출 대신 배열 인덱싱 사용
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    atr_arr = a.to_numpy()
    ts_arr = list(df.index)

    out: list[Pivot] = []
    hi_px, hi_ts = float(highs[0]), ts_arr[0]
    lo_px, lo_ts = float(lows[0]), ts_arr[0]
    direction: str | None = None   # None=미정, "up"=고점 추적 중, "down"=저점 추적 중

    # [I-2] 블라인드 윈도우 반대 극값: hi 추적 중 opp_lo, lo 추적 중 opp_hi 관리
    # opp_lo_px/opp_lo_ts: 마지막 hi_ts 이후의 최소 low (H 확정 시 lo 시딩에 사용)
    # opp_hi_px/opp_hi_ts: 마지막 lo_ts 이후의 최대 high (L 확정 시 hi 시딩에 사용)
    opp_lo_px, opp_lo_ts = float(lows[0]), ts_arr[0]
    opp_hi_px, opp_hi_ts = float(highs[0]), ts_arr[0]

    for i in range(len(df)):
        ts = ts_arr[i]
        hi = float(highs[i])
        lo = float(lows[i])
        close = float(closes[i])

        if direction in (None, "up"):
            # [I-2] hi 후보 갱신: 새 고점이면 opp_lo도 그 봉 low로 리셋
            if hi >= hi_px:
                hi_px, hi_ts = hi, ts
                opp_lo_px, opp_lo_ts = lo, ts  # 새 극점봉 기준으로 반대 추적 리셋
            else:
                # 극점봉 이후 봉: opp_lo를 min으로 갱신
                if lo < opp_lo_px:
                    opp_lo_px, opp_lo_ts = lo, ts

        if direction in (None, "down"):
            # [I-2] lo 후보 갱신: 새 저점이면 opp_hi도 그 봉 high로 리셋
            if lo <= lo_px:
                lo_px, lo_ts = lo, ts
                opp_hi_px, opp_hi_ts = hi, ts  # 새 극점봉 기준으로 반대 추적 리셋
            else:
                # 극점봉 이후 봉: opp_hi를 max로 갱신
                if hi > opp_hi_px:
                    opp_hi_px, opp_hi_ts = hi, ts

        if i < atr_period:
            continue

        thr = float(atr_arr[i]) * atr_k
        # [I-1] thr>0 게이트: ATR=0 횡보 구간 피벗 폭주 방지
        if thr <= 0:
            continue

        if direction in (None, "up") and hi_px - close >= thr:
            out.append(Pivot(ts=hi_ts, price=hi_px, kind="H", confirmed_ts=ts))
            direction = "down"
            # [I-2] H 확정: lo를 블라인드 윈도우(hi_ts 이후) 최소 low로 시딩
            lo_px, lo_ts = opp_lo_px, opp_lo_ts
            # 다음 lo 추적을 위해 opp_hi를 확정봉 high로 리셋
            opp_hi_px, opp_hi_ts = hi, ts

        elif direction in (None, "down") and close - lo_px >= thr:
            out.append(Pivot(ts=lo_ts, price=lo_px, kind="L", confirmed_ts=ts))
            direction = "up"
            # [I-2] L 확정: hi를 블라인드 윈도우(lo_ts 이후) 최대 high로 시딩
            hi_px, hi_ts = opp_hi_px, opp_hi_ts
            # 다음 hi 추적을 위해 opp_lo를 확정봉 low로 리셋
            opp_lo_px, opp_lo_ts = lo, ts

    return out
