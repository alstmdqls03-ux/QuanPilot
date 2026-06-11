"""매물대(공급/수요 박스) — BOT-SPEC S1.

WHY 피벗 군집 방식: '횡보하며 오래 거래된 구간'의 정량화로, 확정 피벗이 비슷한
가격대에 반복 출현한 구간을 박스로 본다. 원문 규칙 승계: ① 이탈/돌파는 봉마감
기준만(휩소 V4) ② 이탈된 박스는 지우지 않고 역할 전환(지지↔저항) ③ 첫 터치 가중.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Zone:
    top: float
    bottom: float
    created_ts: int        # 마지막 구성 피벗 ts
    touches: int           # 구성 피벗 수
    broken_dir: str | None  # None=원형 | "down"=하향이탈(이후 저항) | "up"=상향돌파(이후 지지)


def build_zones(pivots, atr_value: float, cluster_k: float = 0.5,
                min_touches: int = 2,
                closes: pd.Series | None = None,
                break_proximity_k: float = 0.25) -> list[Zone]:
    """확정 피벗을 가격 근접(ATR×cluster_k)으로 군집해 박스 생성 + 이탈 판정.

    closes: 박스 생성 이후의 '종가' 시계열(index=ts). 종가가 bottom 아래로 마감하면
    broken_dir="down", top 위로 마감하면 "up". 장중 고저는 보지 않는다(휩소 무시).

    WHY 비대칭 이탈 기준:
    - 하향(down): c < bottom — 지지 박스 저점 아래 종가는 즉시 의미 있는 이탈.
    - 상향(up): c > top + ATR×break_proximity_k — 박스 상단 근방의 약한 상승은
      노이즈(리테스트 가능성)로 취급해 ATR×proximity 버퍼 이상 벗어났을 때만 인정.
      이로써 '종가=top+proximity_buffer'처럼 경계에 딱 걸린 경우 이탈 처리를 피한다.
    """
    if not pivots or atr_value <= 0:
        return []
    eps = atr_value * cluster_k
    up_buf = atr_value * break_proximity_k  # 상향 이탈 버퍼(하향엔 미사용)
    ordered = sorted(pivots, key=lambda p: p.price)
    groups: list[list] = [[ordered[0]]]
    for p in ordered[1:]:
        if p.price - groups[-1][-1].price <= eps:
            groups[-1].append(p)
        else:
            groups.append([p])
    zones: list[Zone] = []
    for g in groups:
        if len(g) < min_touches:
            continue
        top = max(p.price for p in g)
        bottom = min(p.price for p in g)
        created = max(p.ts for p in g)
        broken: str | None = None
        if closes is not None and len(closes):
            after = closes[closes.index > created]
            for _, c in after.items():
                if c < bottom:
                    broken = "down"
                    break
                if c > top + up_buf:
                    broken = "up"
                    break
        zones.append(Zone(top=top, bottom=bottom, created_ts=created,
                          touches=len(g), broken_dir=broken))
    return sorted(zones, key=lambda z: z.bottom)


def touch_side(zones: list[Zone], price: float, atr_value: float,
               side: str, proximity_k: float = 0.25) -> Zone | None:
    """롱=지지 터치 / 숏=저항 터치 판정. 근접 허용폭 = ATR×proximity_k.

    지지: 원형 박스 상단(위에서 내려와 닿음) 또는 상향돌파된 박스 상단(플립 리테스트).
    저항: 원형 박스 하단(아래에서 올라와 닿음) 또는 하향이탈된 박스 하단(플립).
    """
    tol = atr_value * proximity_k
    for z in zones:
        if side == "long":
            edge_ok = z.broken_dir in (None, "up")
            if edge_ok and abs(price - z.top) <= tol and price >= z.bottom:
                return z
        else:
            edge_ok = z.broken_dir in (None, "down")
            if edge_ok and abs(price - z.bottom) <= tol and price <= z.top:
                return z
    return None


def first_zone_above(zones: list[Zone], price: float) -> float | None:
    """현재가 위 첫 박스 하단 경계 — 롱의 TP1/G2 손익비 계산용(목표 경로의 첫 벽)."""
    edges = [z.bottom for z in zones if z.bottom > price]
    return min(edges) if edges else None


def first_zone_below(zones: list[Zone], price: float) -> float | None:
    """현재가 아래 첫 박스 상단 경계 — 숏의 TP1/G2용."""
    edges = [z.top for z in zones if z.top < price]
    return max(edges) if edges else None
