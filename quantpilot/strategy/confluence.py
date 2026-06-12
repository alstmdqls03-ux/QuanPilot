"""confluence(BOT-SPEC 모드 A 코어) — 근거 겹침 점수제 진입.

점수표(스펙 §4.5): S1 매물대 ±2 / S2 다이버전스 ±2(+더블1) / S4 피보존 +1 /
S5 RSI극단 +1 / S6 4h 동발 +1(캡2). 진입: 총점>=4 & 계열>=2(risk 0.5배) /
총점>=6 & 계열>=3(1.0배). 게이트: G2 손익비>=rr_min(TP1=첫 매물대 — V6 내장),
V1 원웨이 차단. 모든 판정 봉마감 기준. 청산은 엔진 소유: TP 사다리 50/40/10
(meta.targets) + TP1 후 본전 트레일(be_trail_after_tp1) + 손절. exit 신호 없음
— 러너(10%)는 BE 트레일/손절이 정리.
"""
from __future__ import annotations

import pandas as pd

from quantpilot.backtest.data_loader import closed_htf_slice
from quantpilot.strategy.base import IStrategy, Signal
from quantpilot.strategy.divergence import detect_divergence
from quantpilot.strategy.fib import fib_levels, in_entry_zone, last_wave
from quantpilot.strategy.indicators import atr, rsi
from quantpilot.strategy.pivots import confirmed_pivots
from quantpilot.strategy.zones import (
    build_zones, first_zone_above, first_zone_below, touch_side)

HOUR_MS = 3_600_000


class ConfluenceStrategy(IStrategy):
    name = "confluence"
    be_trail_after_tp1 = True      # 엔진이 getattr로 읽음

    def __init__(self, timeframe: str = "1h", htf_df: pd.DataFrame | None = None,
                 rsi_period: int = 14, atr_period: int = 14,
                 zigzag_atr_k: float = 3.0, oversold: float = 30.0,
                 overbought: float = 70.0,
                 entry_min: int = 4, entry_families: int = 2,
                 strong_min: int = 6, strong_families: int = 3,
                 rr_min: float = 1.5,
                 one_way_lookback: int = 20, one_way_ratio: float = 0.8,
                 htf_ms: int = 4 * HOUR_MS, ltf_ms: int = HOUR_MS,
                 lookback: int = 200):
        self.timeframe = timeframe
        self.htf_df = htf_df
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.zigzag_atr_k = zigzag_atr_k
        self.oversold = oversold
        self.overbought = overbought
        self.entry_min = entry_min
        self.entry_families = entry_families
        self.strong_min = strong_min
        self.strong_families = strong_families
        self.rr_min = rr_min
        self.one_way_lookback = one_way_lookback
        self.one_way_ratio = one_way_ratio
        self.htf_ms = htf_ms
        self.ltf_ms = ltf_ms
        # WHY 200: 피벗·매물대는 수십 봉 구조 필요. RSI/ATR warmup 포함 여유.
        self.lookback = lookback

    def set_htf(self, df: pd.DataFrame) -> None:
        self.htf_df = df

    def _one_way(self, window: pd.DataFrame, side: str) -> bool:
        """V1: 직전 N봉 동일방향 봉 비율 > x → 역추세 진입 금지."""
        tail = window.iloc[-self.one_way_lookback:]
        if len(tail) < self.one_way_lookback:
            return False
        down = float((tail["close"] < tail["open"]).mean())
        up = float((tail["close"] > tail["open"]).mean())
        return down > self.one_way_ratio if side == "long" else up > self.one_way_ratio

    def _fib_levels_for(self, side: str, pivots: list, now_ts: int) -> dict | None:
        """S4: 파동 방향과 side 짝짓기 — 상승 파동 되돌림=롱 전용, 하락=숏 전용.

        WHY: 방향을 안 보면 같은 0.5~0.618 가격대가 양방향 점수에 살포된다(리뷰 I-5).
        """
        wave = last_wave(pivots, now_ts)
        if wave is None:
            return None
        start, end = wave
        wave_up = end > start
        if (side == "long" and wave_up) or (side == "short" and not wave_up):
            return fib_levels(start, end)
        return None

    def _score_side(self, side: str, window: pd.DataFrame, pivots: list,
                    zones: list, rsi_s: pd.Series, atr_v: float,
                    now_ts: int) -> tuple[int, set, dict]:
        close = float(window["close"].iloc[-1])
        score, families, detail = 0, set(), {}
        z = touch_side(zones, close, atr_v, side)
        if z is not None:
            score += 2
            families.add("zone")
            detail["S1"] = {"top": z.top, "bottom": z.bottom, "touches": z.touches}
        div = detect_divergence(
            pivots, rsi_s, side, now_ts,
            lows=window["low"], highs=window["high"],
            extreme=self.oversold if side == "long" else self.overbought)
        if div is not None:
            score += 2
            families.add("divergence")
            detail["S2"] = {"anchor": div.anchor.price, "double": div.double}
            if div.double:
                score += 1
        levels = self._fib_levels_for(side, pivots, now_ts)
        if levels and in_entry_zone(close, levels):
            score += 1
            families.add("fib")
            detail["S4"] = levels
        r_now = float(rsi_s.iloc[-1])
        if (side == "long" and r_now <= self.oversold) or \
           (side == "short" and r_now >= self.overbought):
            score += 1
            families.add("rsi_extreme")
            detail["S5"] = r_now
        # S6: 핵심 시그널(S1/S2)이 4h에서도 동시 성립 — +1씩, 캡 +2.
        # WHY HTF 분리: HTF 피벗·존은 별도 계산만 — LTF 리스트와 절대 병합 금지.
        if self.htf_df is not None and len(self.htf_df):
            htf = closed_htf_slice(self.htf_df, now_ts, self.htf_ms, self.ltf_ms)
            if len(htf) >= max(self.rsi_period, self.atr_period) + 2:
                bonus = 0
                h_piv = confirmed_pivots(htf, self.zigzag_atr_k, self.atr_period)
                h_atr = float(atr(htf["high"], htf["low"], htf["close"],
                                  self.atr_period).iloc[-1])
                h_zones = build_zones(h_piv, h_atr, closes=htf["close"])
                if "zone" in families and \
                        touch_side(h_zones, close, h_atr, side) is not None:
                    bonus += 1
                h_rsi = rsi(htf["close"], self.rsi_period)
                h_div = detect_divergence(
                    h_piv, h_rsi, side, now_ts,
                    lows=htf["low"], highs=htf["high"],
                    extreme=self.oversold if side == "long" else self.overbought)
                if "divergence" in families and h_div is not None:
                    bonus += 1
                if bonus:
                    score += min(bonus, 2)
                    detail["S6"] = min(bonus, 2)
        detail["stop_anchor"] = div.anchor.price if div else None
        return score, families, detail

    def generate_signal(self, window: pd.DataFrame, open_position) -> Signal:
        if open_position is not None:
            return Signal("hold", 0.0, None, {"why": "position_open"})
        if len(window) < self.lookback:
            return Signal("hold", 0.0, None, {"why": "warmup"})
        now_ts = int(window.index[-1])
        close = float(window["close"].iloc[-1])
        pivots = confirmed_pivots(window, self.zigzag_atr_k, self.atr_period)
        atr_v = float(atr(window["high"], window["low"], window["close"],
                          self.atr_period).iloc[-1])
        rsi_s = rsi(window["close"], self.rsi_period)
        zones = build_zones(pivots, atr_v, closes=window["close"])

        best = None
        for side in ("long", "short"):
            score, families, detail = self._score_side(
                side, window, pivots, zones, rsi_s, atr_v, now_ts)
            if score >= self.entry_min and len(families) >= self.entry_families:
                if best is None or score > best[1]:
                    best = (side, score, families, detail)
        if best is None:
            return Signal("hold", 0.0, None, {"why": "score"})
        side, score, families, detail = best

        if self._one_way(window, side):
            return Signal("hold", 0.0, None, {"blocked": "V1", "score": score})

        # 손절: 다이버전스 anchor(=비교 저/고점) 우선, 없으면 직전 확정 동종 피벗 ± 0.1 ATR
        anchor = detail.get("stop_anchor")
        if anchor is None:
            kind = "L" if side == "long" else "H"
            sel = [p for p in pivots if p.confirmed_ts <= now_ts and p.kind == kind]
            if not sel:
                return Signal("hold", 0.0, None, {"blocked": "no_pivot"})
            anchor = sel[-1].price
        stop = anchor - 0.1 * atr_v if side == "long" else anchor + 0.1 * atr_v
        risk = abs(close - stop)
        if risk <= 0:
            return Signal("hold", 0.0, None, {"blocked": "zero_risk"})

        # TP1=경로상 첫 매물대 경계(없으면 1.5R) — G2 손익비 분자이자 V6(경로 차단) 내장.
        # TP2=피보(방향 짝지은 파동) 최원 레벨이 TP1보다 멀면 그것, 아니면 2.5R.
        if side == "long":
            tp1 = first_zone_above(zones, close) or close + 1.5 * risk
            tp2 = max(tp1 + 0.5 * risk, close + 2.5 * risk)
            lv = self._fib_levels_for(side, pivots, now_ts)
            if lv:
                cand = max(lv.values())
                if cand > tp1:
                    tp2 = cand
            rr = (tp1 - close) / risk
        else:
            tp1 = first_zone_below(zones, close) or close - 1.5 * risk
            tp2 = min(tp1 - 0.5 * risk, close - 2.5 * risk)
            lv = self._fib_levels_for(side, pivots, now_ts)
            if lv:
                cand = min(lv.values())
                if cand < tp1:
                    tp2 = cand
            rr = (close - tp1) / risk
        if rr < self.rr_min:
            return Signal("hold", 0.0, None,
                          {"blocked": "G2", "rr": rr, "score": score})

        strong = score >= self.strong_min and len(families) >= self.strong_families
        meta = {"score": score, "families": len(families),
                "family_set": sorted(families),
                "risk_mult": 1.0 if strong else 0.5,
                "targets": [(tp1, 0.5), (tp2, 0.4)],
                "rr_tp1": rr, "detail": detail}
        return Signal(side, 1.0 if strong else 0.5, stop, meta)
