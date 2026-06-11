"""RSI 다이버전스(S2) — BOT-SPEC의 핵심 반전 시그널.

원문 규칙 매핑:
- 상승 다이버전스 = 가격 LL + RSI HL, 'RSI 과매도(<=30) 구간 발생만 유효' (숏은 거울)
- 컨펌 = 봉마감 대기 → 피벗 확정(ZigZag의 ATR×k 반대 이동이 '강한 반등' 역할)
- F1 폐기 = 컨펌 후 비교점 재이탈 시 폐기: anchor 저점(롱) 또는 고점(숏)을
  저가/고가 기준으로 재이탈하면 무효
- 더블 = 같은 방향 연속 2쌍 → 신뢰 보너스
WHY 피벗 confirmed_ts 게이트: 미확정 극점으로 다이버전스를 만들면 룩어헤드.
WHY in_zone은 anchor RSI만 검사: '과매도 구간 발생'은 최종 저점이 과매도이면 충분.
  prev RSI까지 요구하면 신호가 지나치게 좁아진다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantpilot.strategy.pivots import Pivot


@dataclass(frozen=True)
class Divergence:
    side: str          # "long" | "short"
    anchor: Pivot      # 둘째(최근) 피벗 — 손절 기준점으로도 사용
    prev: Pivot
    confirmed: bool
    double: bool


def detect_divergence(pivots: list[Pivot], rsi: pd.Series, side: str,
                      now_ts: int, lows: pd.Series | None,
                      highs: pd.Series | None,
                      extreme: float = 30.0) -> Divergence | None:
    """now_ts 시점에 유효한 최신 다이버전스를 반환(없으면 None).

    Args:
        pivots:  ZigZag 피벗 목록 (confirmed_ts 순으로 정렬돼 있어야 함)
        rsi:     봉 ts 인덱스 → RSI 값 시리즈
        side:    "long" | "short"
        now_ts:  현재 타임스탬프 (confirmed_ts <= now_ts 인 피벗만 사용)
        lows:    F1 검사용 저가 시계열 (롱 전용; 롤링 창 저가 등)
        highs:   F1 검사용 고가 시계열 (숏 전용)
        extreme: 과매도/과매수 경계 (롱=30, 숏=70)

    Returns:
        Divergence 또는 None
    """
    kind = "L" if side == "long" else "H"

    # WHY confirmed_ts <= now_ts 필터: 미확정 피벗은 룩어헤드 오염원
    sel = [p for p in pivots if p.kind == kind and p.confirmed_ts <= now_ts]
    if len(sel) < 2:
        return None

    prev, anchor = sel[-2], sel[-1]

    # RSI 인덱스에 피벗 ts가 없으면 비교 불가 → None
    if anchor.ts not in rsi.index or prev.ts not in rsi.index:
        return None

    r_prev = float(rsi.loc[prev.ts])
    r_anchor = float(rsi.loc[anchor.ts])

    if side == "long":
        price_div = anchor.price < prev.price          # LL: 가격 저점 하락
        rsi_div = r_anchor > r_prev                    # HL: RSI 저점 상승
        in_zone = r_anchor <= extreme                  # 과매도 구간 발생
        series = lows

        def breach(v: float) -> bool:                  # 재이탈 = anchor 저점 하향 돌파
            return v < anchor.price
    else:
        price_div = anchor.price > prev.price          # HH: 가격 고점 상승
        rsi_div = r_anchor < r_prev                    # LH: RSI 고점 하락
        in_zone = r_anchor >= extreme                  # 과매수 구간 발생
        series = highs

        def breach(v: float) -> bool:                  # 재이탈 = anchor 고점 상향 돌파
            return v > anchor.price

    if not (price_div and rsi_div and in_zone):
        return None

    # F1: 피벗 확정 이후 ~ now_ts까지 비교점 재이탈 시 폐기
    # WHY anchor.ts 기준 절개: anchor 이전의 이탈은 다이버전스 형성 전이므로 무관
    if series is not None:
        window = series[(series.index > anchor.ts) & (series.index <= now_ts)]
        if any(breach(float(v)) for v in window):
            return None

    # 더블 다이버전스: 직전 쌍(sel[-3]→prev)도 같은 방향 다이버전스인지 확인
    # WHY 연속 2쌍: 신호 강도(신뢰 보너스)만 부여하며 진입 조건 자체는 단일 쌍과 동일
    double = False
    if len(sel) >= 3:
        p2 = sel[-3]
        if p2.ts in rsi.index:
            r2 = float(rsi.loc[p2.ts])
            if side == "long":
                double = prev.price < p2.price and r_prev > r2
            else:
                double = prev.price > p2.price and r_prev < r2

    return Divergence(side=side, anchor=anchor, prev=prev,
                      confirmed=True, double=double)
