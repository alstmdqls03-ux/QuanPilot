"""백테스트/페이퍼 공용 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Position:
    side: Literal["long", "short"]
    entry: float
    contracts: int                          # 남은 계약 수(부분 익절로 줄어듦)
    stop: float
    targets_remaining: list[tuple[float, float]]  # [(price, fraction_of_original), ...]
    opened_ts: int
    original_contracts: int = 0             # 진입 시 총 계약(부분 익절 수량 계산용)

    def __post_init__(self):
        if self.original_contracts == 0:
            self.original_contracts = self.contracts


@dataclass
class Fill:
    ts: int
    price: float
    contracts: int
    fee: float
    reason: str                             # "stop"|"tp1"|"tp2"|"tp3"|"exit_signal"
    pnl_gross: float                        # 이 체결분의 gross 손익(USDT)


@dataclass
class Trade:
    """청산 완료된 한 포지션 요약(여러 부분 체결의 집계)."""
    side: str
    entry: float
    exit: float                             # 가중평균 청산가
    contracts: int                          # 진입 총 계약
    pnl_gross: float
    fees: float
    funding: float
    pnl_net: float
    opened_ts: int
    closed_ts: int
    reason: str                             # 마지막 체결 사유 또는 "partial"


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[tuple[int, float]]   # [(ts, equity_usd), ...]
    split_ts: int                           # train/OOS 경계 ts
    train_metrics: dict = field(default_factory=dict)
    oos_metrics: dict = field(default_factory=dict)
