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
                closes: pd.Series | None = None) -> list[Zone]:
    """확정 피벗을 가격 근접(ATR×cluster_k)으로 군집해 박스 생성 + 이탈 판정.

    closes: 박스 생성 이후의 '종가' 시계열(index=ts). 종가가 bottom 아래로 마감하면
    broken_dir="down", top 위로 마감하면 "up". 장중 고저는 보지 않는다(휩소 무시).

    # WHY 대칭·무버퍼: 원전 규칙은 '봉마감 종가의 경계 통과'뿐 — 방향별 버퍼는 근거 없는 자유변수.
    """
    if not pivots or atr_value <= 0:
        return []
    eps = atr_value * cluster_k
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
            # WHY 마지막 교차: 원문 '역할 전환(지지↔저항)'은 양방향 — down 이탈 후 top 위 종가
            # 복귀(reclaim)면 다시 지지다. 첫 교차 break 없이 모든 after 종가를 순회하며 갱신.
            for _, c in after.items():
                if c < bottom:
                    broken = "down"
                elif c > top:
                    broken = "up"
        # WHY created=피벗 ts 기준: H 앵커 군집은 피벗 확정 전 종가에 의해 '생성 시점에 이미
        # 깨진' 상태일 수 있다 — 판정 시점엔 전부 과거 데이터라 룩어헤드 아님("그 레벨은 이미
        # 깨졌었다"는 사실 반영).
        zones.append(Zone(top=top, bottom=bottom, created_ts=created,
                          touches=len(g), broken_dir=broken))
    return sorted(zones, key=lambda z: z.bottom)


def touch_side(zones: list[Zone], price: float, atr_value: float,
               side: str, proximity_k: float = 0.25) -> Zone | None:
    """롱=지지 터치 / 숏=저항 터치 판정. 근접 허용폭 = ATR×proximity_k.

    지지: 원형 박스 상단 또는 상향돌파된 박스 상단(플립 리테스트).
    저항: 원형 박스 하단 또는 하향이탈된 박스 하단(플립).
    단일 price API라 접근 방향은 검증하지 않는다 — 경계 근접 여부만 판정(방향 컨텍스트는
    호출자 몫).
    # WHY 최근접 후보: 다중 근접 후보 시 가장 가까운 벽이 행동 기준.
    """
    tol = atr_value * proximity_k
    best: Zone | None = None
    best_dist: float = float("inf")
    for z in zones:
        if side == "long":
            edge_ok = z.broken_dir in (None, "up")
            if edge_ok and abs(price - z.top) <= tol and price >= z.bottom:
                dist = abs(price - z.top)
                if dist < best_dist:
                    best_dist = dist
                    best = z
        else:
            edge_ok = z.broken_dir in (None, "down")
            if edge_ok and abs(price - z.bottom) <= tol and price <= z.top:
                dist = abs(price - z.bottom)
                if dist < best_dist:
                    best_dist = dist
                    best = z
    return best


def first_zone_above(zones: list[Zone], price: float) -> float | None:
    """현재가 위 첫 박스 하단 경계 — 롱의 TP1/G2 손익비 계산용(목표 경로의 첫 벽)."""
    edges = [z.bottom for z in zones if z.bottom > price]
    return min(edges) if edges else None


def first_zone_below(zones: list[Zone], price: float) -> float | None:
    """현재가 아래 첫 박스 상단 경계 — 숏의 TP1/G2용."""
    edges = [z.top for z in zones if z.top < price]
    return max(edges) if edges else None
