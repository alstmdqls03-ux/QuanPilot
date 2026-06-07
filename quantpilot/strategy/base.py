"""전략 계약. Week 3 페이퍼·실거래가 이 인터페이스를 그대로 재사용한다."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

SignalSide = Literal["long", "short", "exit", "hold"]


@dataclass(frozen=True)
class Signal:
    side: SignalSide
    confidence: float                       # 0.0–1.0
    suggested_stop: float | None            # 절대 가격. long/short일 때만 의미
    meta: dict = field(default_factory=dict)  # 디버깅 — RSI값, 사유


class IStrategy(ABC):
    name: str
    timeframe: str
    lookback: int          # 필요한 봉 수 (지표 warmup 포함)

    @abstractmethod
    def generate_signal(self, window: pd.DataFrame, open_position) -> Signal:
        """window = 마지막 lookback개 닫힌 봉(오름차순). 현재 봉 = window.iloc[-1].
        전략이 window에서 지표를 직접 계산해 신호 반환. 상태 없음(stateless).

        WHY window 방식: 백테스트(과거 봉)든 페이퍼(새 봉)든 '최근 lookback개 봉'을
        넘기면 동일 동작 → 백테=페이퍼 일치. 매 봉 재계산은 순식간이라 속도 무관.
        """
        ...
