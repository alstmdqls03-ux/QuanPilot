"""RSI mean-reversion baseline. RSI<low→long, RSI>high→short, 중립 복귀→exit.

WHY baseline: 수익성 단정이 아니라 infra 검증용 신호 생성기. 파라미터는
외부 검증된 범위 차용(확증편향 방지). 본인 가설은 Week 4 회고 후.
"""
from __future__ import annotations

import pandas as pd

from quantpilot.strategy.base import IStrategy, Signal
from quantpilot.strategy.indicators import atr, rsi


class RsiMeanReversion(IStrategy):
    name = "rsi-mr"

    def __init__(self, timeframe: str, rsi_period: int = 14, atr_period: int = 14,
                 low: float = 30.0, high: float = 70.0,
                 exit_band: tuple[float, float] = (45.0, 55.0), atr_k: float = 1.5):
        self.timeframe = timeframe
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.low = low
        self.high = high
        self.exit_band = exit_band
        self.atr_k = atr_k
        # warmup: Wilder smoothing이 안정화되려면 기간의 몇 배 필요
        self.lookback = max(rsi_period, atr_period) * 3

    def generate_signal(self, window: pd.DataFrame, open_position) -> Signal:
        r = float(rsi(window["close"], self.rsi_period).iloc[-1])
        a = float(atr(window["high"], window["low"], window["close"], self.atr_period).iloc[-1])
        price = float(window["close"].iloc[-1])
        meta = {"rsi": r, "atr": a}

        if open_position is not None:
            # 보유 중: RSI가 중립 복귀하면 청산
            if self.exit_band[0] <= r <= self.exit_band[1]:
                return Signal("exit", 1.0, None, meta)
            return Signal("hold", 0.0, None, meta)

        if r < self.low:
            return Signal("long", min(1.0, (self.low - r) / self.low),
                          price - a * self.atr_k, meta)
        if r > self.high:
            return Signal("short", min(1.0, (r - self.high) / (100 - self.high)),
                          price + a * self.atr_k, meta)
        return Signal("hold", 0.0, None, meta)
