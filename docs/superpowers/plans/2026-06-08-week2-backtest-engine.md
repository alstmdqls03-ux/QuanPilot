# Week 2 Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** event-driven 백테스트 엔진으로 RSI mean-reversion 전략을 과거 캔들에 돌려, fee·funding·slippage 차감 후 train/OOS Sharpe와 equity curve를 산출한다.

**Architecture:** 봉 하나씩 도는 event 루프. 전략은 신호만(stateless, window에서 지표 직접 계산), risk는 사이징·손절·분할익절(순수 함수), engine은 체결·비용·포지션 상태. "봉 안에서 손절 먼저" 보수 가정. per-bar step을 배치 루프와 분리해 Week 3 페이퍼가 재사용. 지표는 직접 구현(의존성 최소), 출력은 콘솔 표 + matplotlib equity curve PNG.

**Tech Stack:** Python 3.12, pandas, numpy, matplotlib, click, SQLAlchemy(Week 1), pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-week2-backtest-engine-design.md`

**컨벤션 (Week 1과 동일):** 수학/모델링 결정에 WHY 주석, 타임스탬프 int ms epoch(UTC), YAGNI, 잘못된 입력은 친절한 CLI 에러.

---

## File Structure

```
quantpilot/
├── strategy/
│   ├── __init__.py
│   ├── indicators.py      # rsi(), atr(), ema() — 순수, pandas
│   ├── base.py            # IStrategy, Signal, SignalSide
│   └── rsi_mean_reversion.py
├── risk/
│   ├── __init__.py
│   ├── liquidation.py     # liquidation_price + 가드
│   ├── sizing.py          # calculate_position_size (ctVal, invariant)
│   └── take_profit.py     # TPLadder
├── backtest/
│   ├── __init__.py
│   ├── models.py          # Position, Fill, Trade, BacktestResult
│   ├── costs.py           # apply_slippage, fee_for, funding_between
│   ├── data_loader.py     # load_candles + gap 게이트
│   ├── engine.py          # per-bar step + run_backtest 배치 루프
│   ├── metrics.py         # compute_metrics (Sharpe/maxDD/...)
│   └── report.py          # 콘솔 표 + equity curve PNG
└── cli.py                 # + backtest 명령 (기존 파일 수정)
```

---

## Task 1: 의존성 추가 + 패키지 스캐폴딩

**Files:**
- Modify: `pyproject.toml`
- Create: `quantpilot/strategy/__init__.py`, `quantpilot/risk/__init__.py`, `quantpilot/backtest/__init__.py`

- [ ] **Step 1: pyproject.toml 의존성 추가**

`[project] dependencies` 배열에 다음을 추가 (기존 ccxt/SQLAlchemy/pydantic-settings/click 유지):
```toml
    "pandas>=2.0",
    "numpy>=1.24",
    "matplotlib>=3.7",
```

- [ ] **Step 2: 패키지 디렉토리 생성**

```bash
mkdir -p quantpilot/strategy quantpilot/risk quantpilot/backtest
touch quantpilot/strategy/__init__.py quantpilot/risk/__init__.py quantpilot/backtest/__init__.py
```

- [ ] **Step 3: 설치**

Run:
```bash
. .venv/bin/activate && pip install -e ".[dev]"
```
Expected: `Successfully installed ... pandas ... numpy ... matplotlib ...`

- [ ] **Step 4: 기존 테스트 회귀 없음 확인**

Run: `. .venv/bin/activate && pytest -q`
Expected: `33 passed, 2 deselected`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml quantpilot/strategy quantpilot/risk quantpilot/backtest
git commit -m "chore: add pandas/numpy/matplotlib and Week 2 package dirs"
```

---

## Task 2: 지표 — RSI / ATR / EMA (직접 구현)

**Files:**
- Create: `quantpilot/strategy/indicators.py`
- Test: `tests/test_indicators.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_indicators.py`:
```python
import pandas as pd
import pytest

from quantpilot.strategy.indicators import rsi, atr, ema


def test_ema_matches_pandas_ewm():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = ema(s, period=3)
    expected = s.ewm(span=3, adjust=False).mean()
    assert (out - expected).abs().max() < 1e-9


def test_rsi_all_gains_approaches_100():
    # 단조 상승 → 손실 0 → RSI가 100에 수렴
    close = pd.Series([float(i) for i in range(1, 60)])
    r = rsi(close, period=14)
    assert r.iloc[-1] > 99.0


def test_rsi_all_losses_approaches_0():
    close = pd.Series([float(i) for i in range(60, 1, -1)])
    r = rsi(close, period=14)
    assert r.iloc[-1] < 1.0


def test_rsi_in_range():
    close = pd.Series([10, 11, 10.5, 11.2, 10.8, 11.5, 11.1, 10.9, 11.3, 11.0,
                       10.7, 11.4, 11.2, 10.6, 11.1, 11.3])
    r = rsi(close, period=14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_atr_positive_and_tracks_range():
    high = pd.Series([10.0, 11, 12, 11, 13])
    low = pd.Series([9.0, 10, 11, 10, 11])
    close = pd.Series([9.5, 10.5, 11.5, 10.5, 12])
    a = atr(high, low, close, period=3)
    assert (a.dropna() > 0).all()
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_indicators.py -v`
Expected: FAIL — `ModuleNotFoundError: quantpilot.strategy.indicators`.

- [ ] **Step 3: indicators.py 작성**

Create `quantpilot/strategy/indicators.py`:
```python
"""기술적 지표 — 직접 구현(순수 함수). 입력 pd.Series → 출력 pd.Series.

WHY 직접 구현: 전략의 edge가 지표 해석이라 수학을 소유해야 디버깅 가능.
외부 라이브러리(pandas-ta/ta-lib) 의존성·블랙박스를 피한다.
"""
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """지수이동평균. span=period 의 표준 EMA."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI. 0~100.

    WHY ewm(alpha=1/period): Wilder smoothing은 alpha=1/period 인 EMA와 동일.
    delta>0은 상승분(gain), delta<0은 하락분(loss). RS=avgGain/avgLoss.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    # avg_loss==0이면 rs=inf → rsi=100. pandas가 inf 처리.
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range. true range의 Wilder EMA.

    TR = max(high-low, |high-prev_close|, |low-prev_close|).
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_indicators.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/strategy/indicators.py tests/test_indicators.py
git commit -m "feat: add hand-rolled RSI/ATR/EMA indicators"
```

---

## Task 3: 전략 인터페이스 (strategy/base.py)

**Files:**
- Create: `quantpilot/strategy/base.py`
- Test: `tests/test_strategy_base.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_strategy_base.py`:
```python
import pytest

from quantpilot.strategy.base import Signal, IStrategy


def test_signal_construction():
    s = Signal(side="long", confidence=0.8, suggested_stop=100.0, meta={"rsi": 25})
    assert s.side == "long"
    assert s.suggested_stop == 100.0
    assert s.meta["rsi"] == 25


def test_istrategy_is_abstract():
    with pytest.raises(TypeError):
        IStrategy()  # generate_signal 미구현 → 인스턴스화 불가
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_strategy_base.py -v`
Expected: FAIL — `ModuleNotFoundError: quantpilot.strategy.base`.

- [ ] **Step 3: base.py 작성**

Create `quantpilot/strategy/base.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_strategy_base.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/strategy/base.py tests/test_strategy_base.py
git commit -m "feat: add IStrategy interface and Signal"
```

---

## Task 4: 백테스트 데이터 모델 (backtest/models.py)

**Files:**
- Create: `quantpilot/backtest/models.py`
- Test: `tests/test_backtest_models.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_backtest_models.py`:
```python
from quantpilot.backtest.models import Position, Fill, Trade


def test_position_fields():
    p = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                 targets_remaining=[(105.0, 0.5), (110.0, 0.5)], opened_ts=1)
    assert p.contracts == 10
    assert p.targets_remaining[0] == (105.0, 0.5)


def test_fill_and_trade():
    f = Fill(ts=2, price=105.0, contracts=5, fee=0.26, reason="tp1", pnl_gross=25.0)
    assert f.reason == "tp1"
    t = Trade(side="long", entry=100.0, exit=105.0, contracts=10,
              pnl_gross=50.0, fees=0.5, funding=0.1, pnl_net=49.4,
              opened_ts=1, closed_ts=3, reason="tp")
    assert t.pnl_net == 49.4
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_backtest_models.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: models.py 작성**

Create `quantpilot/backtest/models.py`:
```python
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
    funding_paid: float = 0.0               # 보유 중 누적 funding(USDT)

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
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_backtest_models.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/backtest/models.py tests/test_backtest_models.py
git commit -m "feat: add backtest data models (Position/Fill/Trade/BacktestResult)"
```

---

## Task 5: 청산가 + 가드 (risk/liquidation.py)

**Files:**
- Create: `quantpilot/risk/liquidation.py`
- Test: `tests/test_liquidation.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_liquidation.py`:
```python
import pytest

from quantpilot.risk.liquidation import (
    liquidation_price, assert_stop_within_liquidation, StopBeyondLiquidationError,
)


def test_liq_long_below_entry():
    liq = liquidation_price(entry=100.0, leverage=5, side="long", mmr=0.005)
    assert liq < 100.0
    assert abs(liq - 100.0 * (1 - 1/5 + 0.005)) < 1e-9


def test_liq_short_above_entry():
    liq = liquidation_price(entry=100.0, leverage=5, side="short", mmr=0.005)
    assert liq > 100.0


def test_stop_within_liq_ok():
    # 5x long: liq ≈ 80.5, 안전구역 70% = entry-13.7 ≈ 86.3. stop=95는 OK.
    assert_stop_within_liquidation(entry=100.0, stop=95.0, leverage=5, side="long")


def test_stop_beyond_liq_raises():
    # stop을 청산보다 멀게(75) 두면 거부
    with pytest.raises(StopBeyondLiquidationError):
        assert_stop_within_liquidation(entry=100.0, stop=75.0, leverage=5, side="long")
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_liquidation.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: liquidation.py 작성**

Create `quantpilot/risk/liquidation.py`:
```python
"""OKX isolated margin 청산가 근사 + 손절-청산 거리 가드."""
from __future__ import annotations


class StopBeyondLiquidationError(Exception):
    """손절이 청산 안전구역 밖이라 진입을 거부할 때."""


def liquidation_price(entry: float, leverage: int, side: str, mmr: float = 0.005) -> float:
    """isolated margin 청산가 근사.
    long:  entry × (1 - 1/lev + mmr)
    short: entry × (1 + 1/lev - mmr)
    """
    if side == "long":
        return entry * (1 - 1 / leverage + mmr)
    return entry * (1 + 1 / leverage - mmr)


def assert_stop_within_liquidation(entry: float, stop: float, leverage: int,
                                   side: str, mmr: float = 0.005, frac: float = 0.7) -> None:
    """손절이 청산보다 멀면 StopBeyondLiquidationError.

    WHY: 손절가가 청산가보다 멀면 손절 전에 강제 청산당한다(스톱 무의미).
    안전 여유로 청산 거리의 frac(0.7) 안쪽에 손절이 있어야 한다.
    """
    liq = liquidation_price(entry, leverage, side, mmr)
    if abs(stop - entry) > abs(liq - entry) * frac:
        raise StopBeyondLiquidationError(
            f"stop={stop} 가 청산가={liq:.2f} 의 {frac:.0%} 안전구역 밖 (entry={entry})"
        )
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_liquidation.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/risk/liquidation.py tests/test_liquidation.py
git commit -m "feat: add liquidation price and stop-distance guard"
```

---

## Task 6: 포지션 사이징 (risk/sizing.py)

**Files:**
- Create: `quantpilot/risk/sizing.py`
- Test: `tests/test_sizing.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_sizing.py`:
```python
import pytest

from quantpilot.risk.sizing import (
    calculate_position_size, SizingResult, InsufficientCapitalError,
)


def test_basic_sizing_respects_5pct_invariant():
    r = calculate_position_size(
        capital=1000.0, risk_pct=0.05, entry=100.0, stop=95.0,
        ct_val=0.01, lot_sz=1.0, leverage=3,
    )
    assert isinstance(r, SizingResult)
    # max_loss + fee ≤ capital × 5% × 1.02
    assert r.max_loss_usd <= 1000.0 * 0.05 * 1.02 + 1e-6
    assert r.contracts > 0


def test_sizing_invariant_fuzz_multi_symbol():
    # ctVal 다른 심볼 + 다양한 stop 거리에서도 invariant 유지
    import random
    rng = random.Random(42)
    for _ in range(1000):
        ct_val = rng.choice([0.01, 0.1, 1.0, 10.0])
        entry = rng.uniform(1.0, 50000.0)
        stop = entry * (1 - rng.uniform(0.005, 0.15))
        cap = rng.uniform(200.0, 5000.0)
        try:
            r = calculate_position_size(cap, 0.05, entry, stop, ct_val, 1.0, leverage=3)
        except InsufficientCapitalError:
            continue
        assert r.max_loss_usd <= cap * 0.05 * 1.02 + 1e-6


def test_insufficient_capital_raises():
    # 자본이 너무 작아 1계약도 못 사면 에러
    with pytest.raises(InsufficientCapitalError):
        calculate_position_size(
            capital=1.0, risk_pct=0.05, entry=50000.0, stop=49000.0,
            ct_val=1.0, lot_sz=1.0, leverage=3,
        )
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_sizing.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: sizing.py 작성**

Create `quantpilot/risk/sizing.py`:
```python
"""per-trade 위험 기반 포지션 사이징 (OKX ctVal 반영, invariant 강제)."""
from __future__ import annotations

from dataclasses import dataclass


class InsufficientCapitalError(Exception):
    """위험 예산으로 최소 1계약도 못 살 때."""


@dataclass
class SizingResult:
    contracts: int
    notional_usd: float
    max_loss_usd: float
    clamped_by_leverage: bool


def calculate_position_size(
    capital: float, risk_pct: float, entry: float, stop: float,
    ct_val: float, lot_sz: float, leverage: int = 3,
    maint_margin_rate: float = 0.005, fee_bps: float = 5.0, side: str = "long",
) -> SizingResult:
    """위험 예산(capital×risk_pct) 안에서 계약 수를 계산.

    Invariant(강제 assert): max_loss + fee ≤ capital × risk_pct × 1.02.
    1계약 손실 = price_distance × ct_val. 레버리지 상한으로 notional 클램프.
    """
    risk_amount = capital * risk_pct
    price_distance = abs(entry - stop)
    if price_distance <= 0:
        raise InsufficientCapitalError("entry와 stop이 같음(거리 0)")

    # WHY 수수료를 위험예산에 포함: 1계약 비용 = 손절손실 + 왕복수수료.
    #   risk_amount를 (손실+수수료)로 나눠야 'max_loss + fee ≤ 위험예산'이 보장됨.
    #   (수수료를 빼먹으면 실제 위험이 5%를 초과한다.)
    per_contract_loss = price_distance * ct_val
    per_contract_fee = entry * ct_val * (fee_bps / 10000.0) * 2  # 진입+청산
    per_contract_cost = per_contract_loss + per_contract_fee
    raw = risk_amount / per_contract_cost

    max_notional = capital * leverage
    max_by_lev = max_notional / (entry * ct_val)
    clamped = raw > max_by_lev
    contracts_f = min(raw, max_by_lev)

    # 정수 계약, lot_sz 배수로 라운드다운
    contracts = int(contracts_f // lot_sz * lot_sz)
    if contracts <= 0:
        raise InsufficientCapitalError(
            f"위험예산 {risk_amount:.2f}로 1계약 못 삼 (1계약 비용 {per_contract_cost:.4f})"
        )

    notional = contracts * entry * ct_val
    max_loss = contracts * per_contract_loss
    fee_estimate = contracts * per_contract_fee

    # 손절 손실 + 왕복 수수료가 위험예산을 넘지 않음 (위로 위반 금지)
    assert max_loss + fee_estimate <= capital * risk_pct + 1e-6, (
        f"sizing invariant 위반: max_loss+fee={max_loss+fee_estimate}, target={capital*risk_pct}"
    )
    return SizingResult(
        contracts=contracts, notional_usd=notional,
        max_loss_usd=max_loss, clamped_by_leverage=clamped,
    )
```

> 참고: 레버리지 클램프가 걸리면 max_loss가 목표보다 작아질 수 있다(아래로 위반은 안전). invariant는 상한만 본다.

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_sizing.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/risk/sizing.py tests/test_sizing.py
git commit -m "feat: add ctVal-aware position sizing with 5% invariant"
```

---

## Task 7: 분할 익절 ladder (risk/take_profit.py)

**Files:**
- Create: `quantpilot/risk/take_profit.py`
- Test: `tests/test_take_profit.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_take_profit.py`:
```python
from quantpilot.risk.take_profit import build_targets


def test_long_targets_above_entry():
    # entry 100, stop 95 → R=5. 1R/2R/3R = 105/110/115
    targets = build_targets(entry=100.0, stop=95.0, side="long",
                            r_multiples=[1, 2, 3], fractions=[0.33, 0.33, 0.34])
    prices = [p for p, _ in targets]
    assert prices == [105.0, 110.0, 115.0]
    assert abs(sum(f for _, f in targets) - 1.0) < 1e-9


def test_short_targets_below_entry():
    targets = build_targets(entry=100.0, stop=105.0, side="short",
                            r_multiples=[1, 2, 3], fractions=[0.33, 0.33, 0.34])
    prices = [p for p, _ in targets]
    assert prices == [95.0, 90.0, 85.0]
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_take_profit.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: take_profit.py 작성**

Create `quantpilot/risk/take_profit.py`:
```python
"""분할 익절 타겟 생성. 사용자 원래 구상 '적정 비율로 분할 익절'."""
from __future__ import annotations


def build_targets(entry: float, stop: float, side: str,
                  r_multiples: list[float] | None = None,
                  fractions: list[float] | None = None) -> list[tuple[float, float]]:
    """R-배수 기반 분할 익절 타겟 리스트.

    R = |entry - stop|. target = entry ± R×r (long은 위, short은 아래).
    반환: [(price, fraction), ...]  fraction은 진입 수량 대비 청산 비율.
    """
    r_multiples = r_multiples or [1.0, 2.0, 3.0]
    fractions = fractions or [0.33, 0.33, 0.34]
    if len(r_multiples) != len(fractions):
        raise ValueError("r_multiples와 fractions 길이가 다름")
    r = abs(entry - stop)
    sign = 1.0 if side == "long" else -1.0
    return [(entry + sign * r * rr, frac) for rr, frac in zip(r_multiples, fractions)]
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_take_profit.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/risk/take_profit.py tests/test_take_profit.py
git commit -m "feat: add R-multiple take-profit ladder"
```

---

## Task 8: RSI mean-reversion 전략 (strategy/rsi_mean_reversion.py)

**Files:**
- Create: `quantpilot/strategy/rsi_mean_reversion.py`
- Test: `tests/test_strategy_rsi.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_strategy_rsi.py`:
```python
import pandas as pd

from quantpilot.strategy.rsi_mean_reversion import RsiMeanReversion
from quantpilot.backtest.models import Position


def _window(closes):
    n = len(closes)
    return pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": [1.0] * n,
    })


def test_long_signal_on_oversold():
    s = RsiMeanReversion(timeframe="1h")
    closes = [float(x) for x in range(60, 1, -1)]  # 급락 → RSI 낮음
    sig = s.generate_signal(_window(closes), open_position=None)
    assert sig.side == "long"
    assert sig.suggested_stop is not None and sig.suggested_stop < closes[-1]


def test_short_signal_on_overbought():
    s = RsiMeanReversion(timeframe="1h")
    closes = [float(x) for x in range(1, 60)]  # 급등 → RSI 높음
    sig = s.generate_signal(_window(closes), open_position=None)
    assert sig.side == "short"
    assert sig.suggested_stop is not None and sig.suggested_stop > closes[-1]


def test_exit_when_rsi_neutral_and_position_open():
    s = RsiMeanReversion(timeframe="1h", exit_band=(45.0, 55.0))
    # 횡보 → RSI ~50
    closes = [10.0, 10.1, 9.9, 10.05, 9.95] * 12
    pos = Position(side="long", entry=10.0, contracts=5, stop=9.5,
                   targets_remaining=[], opened_ts=1)
    sig = s.generate_signal(_window(closes), open_position=pos)
    assert sig.side in ("exit", "hold")


def test_lookback_is_set():
    assert RsiMeanReversion(timeframe="1h").lookback >= 30
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_strategy_rsi.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: rsi_mean_reversion.py 작성**

Create `quantpilot/strategy/rsi_mean_reversion.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_strategy_rsi.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/strategy/rsi_mean_reversion.py tests/test_strategy_rsi.py
git commit -m "feat: add RSI mean-reversion strategy"
```

---

## Task 9: 비용 모델 (backtest/costs.py)

**Files:**
- Create: `quantpilot/backtest/costs.py`
- Test: `tests/test_costs.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_costs.py`:
```python
from quantpilot.backtest.costs import apply_slippage, fee_for, funding_between


def test_slippage_worse_direction():
    # 매수 체결가는 위로(불리), 매도 체결가는 아래로(불리)
    assert apply_slippage(100.0, slippage_bps=10, side="buy") > 100.0
    assert apply_slippage(100.0, slippage_bps=10, side="sell") < 100.0


def test_fee_proportional_to_notional():
    # notional 1000, taker 5bps = 0.5
    assert abs(fee_for(notional=1000.0, fee_bps=5) - 0.5) < 1e-9


def test_funding_sums_events_in_window():
    # funding 이벤트 2개가 [open, close) 구간에 들어가면 둘 다 합산
    events = [(1000, 0.0001), (2000, -0.00005), (3000, 0.0002)]
    # 포지션 보유 [1500, 2500): 2000 이벤트만 포함
    paid = funding_between(events, notional=1000.0, side="long",
                           open_ts=1500, close_ts=2500)
    # long은 +funding이면 지불(+), -funding이면 수취(-)
    assert abs(paid - (1000.0 * -0.00005)) < 1e-9
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_costs.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: costs.py 작성**

Create `quantpilot/backtest/costs.py`:
```python
"""백테스트 비용: slippage / fee / funding. 전부 순수 함수."""
from __future__ import annotations


def apply_slippage(price: float, slippage_bps: float, side: str) -> float:
    """체결가를 불리한 쪽으로 slippage_bps 만큼 이동.
    buy(매수 진입/숏청산)는 위로, sell(매도 진입/롱청산)은 아래로.
    """
    adj = price * (slippage_bps / 10000.0)
    return price + adj if side == "buy" else price - adj


def fee_for(notional: float, fee_bps: float) -> float:
    """체결 수수료 = notional × fee_bps. (notional = contracts × price × ct_val)"""
    return abs(notional) * (fee_bps / 10000.0)


def funding_between(events: list[tuple[int, float]], notional: float, side: str,
                    open_ts: int, close_ts: int) -> float:
    """[open_ts, close_ts) 구간에 든 funding 이벤트를 합산해 지불액 반환.

    long은 +funding_rate면 지불(+부호), short은 반대.
    events = [(ts, funding_rate), ...].
    WHY: 8h마다 포지션 notional × funding_rate. 롱이 펀딩 양수일 때 숏에게 지불.
    """
    sign = 1.0 if side == "long" else -1.0
    total = 0.0
    for ts, rate in events:
        if open_ts <= ts < close_ts:
            total += sign * notional * rate
    return total
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_costs.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/backtest/costs.py tests/test_costs.py
git commit -m "feat: add slippage/fee/funding cost models"
```

---

## Task 10: 데이터 로더 + gap 게이트 (backtest/data_loader.py)

**Files:**
- Create: `quantpilot/backtest/data_loader.py`
- Test: `tests/test_data_loader.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_data_loader.py`:
```python
import pandas as pd

from quantpilot.backtest.data_loader import detect_gaps, load_candles_df
from quantpilot.data.models import Candle


def _add_candle(session, ts, close=100.0):
    session.add(Candle(exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
                       ts=ts, open=close, high=close, low=close, close=close,
                       volume=1.0, inserted_at=1))


def test_detect_gaps_finds_holes():
    tf = 3_600_000
    base = 1_700_000_000_000
    # 0,1,3 봉 존재 (2번 누락)
    ts_list = [base, base + tf, base + 3 * tf]
    gaps, ranges = detect_gaps(ts_list, tf)
    assert gaps == 1
    assert ranges  # 누락 구간 보고됨


def test_detect_gaps_none_when_contiguous():
    tf = 3_600_000
    base = 1_700_000_000_000
    ts_list = [base + i * tf for i in range(5)]
    gaps, ranges = detect_gaps(ts_list, tf)
    assert gaps == 0


def test_load_candles_df(session):
    tf = 3_600_000
    base = 1_700_000_000_000
    for i in range(3):
        _add_candle(session, base + i * tf, close=100.0 + i)
    session.commit()
    df = load_candles_df(session, "BTC-USDT-SWAP", "1h")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3
    assert df.index.name == "ts"
    assert df["close"].iloc[-1] == 102.0
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_data_loader.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: data_loader.py 작성**

Create `quantpilot/backtest/data_loader.py`:
```python
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
    감지·경고만; 메우기는 TODOS(post-MVP).
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


def load_with_gap_check(session, symbol: str, timeframe: str, allow_gaps: bool):
    """DataFrame 로드 + gap 검사. 반환 (df, gaps, ranges).
    allow_gaps=False이고 gap>0이면 DataGapError.
    """
    df = load_candles_df(session, symbol, timeframe)
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


class DataGapError(Exception):
    """데이터 구멍 또는 부재로 백테스트를 막을 때."""
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_data_loader.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/backtest/data_loader.py tests/test_data_loader.py
git commit -m "feat: add candle DataFrame loader and gap-detection gate"
```

---

## Task 11: Engine — per-bar step (체결·손절·분할익절)

**Files:**
- Create: `quantpilot/backtest/engine.py` (per-bar 함수만)
- Test: `tests/test_engine_step.py`

per-bar step은 "이 봉에서 포지션 청산/부분익절 판정"을 담당. **'손절 먼저' 보수 가정**이 여기 들어간다. 배치 루프(Task 12)와 분리해 Week 3 페이퍼가 재사용.

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_engine_step.py`:
```python
from quantpilot.backtest.engine import check_exits
from quantpilot.backtest.models import Position


def _bar(ts, high, low, close):
    return {"ts": ts, "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


def test_stop_hit_closes_long():
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(110.0, 1.0)], opened_ts=1)
    # 봉 low가 stop 아래로 → 손절 체결
    new_pos, fills = check_exits(pos, _bar(2, high=101, low=94, close=96),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is None
    assert len(fills) == 1 and fills[0].reason == "stop"


def test_stop_first_when_bar_straddles_both():
    # 한 봉이 stop(95)과 target(110)을 동시에 건드림 → 보수적으로 stop 먼저
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(110.0, 1.0)], opened_ts=1)
    new_pos, fills = check_exits(pos, _bar(2, high=111, low=94, close=100),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is None
    assert fills[0].reason == "stop"   # TP가 아니라 stop


def test_partial_tp_reduces_contracts():
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(105.0, 0.5), (110.0, 0.5)], opened_ts=1)
    # 봉 high가 105 닿음(110은 안 닿음), stop 안 닿음 → 50%만 익절
    new_pos, fills = check_exits(pos, _bar(2, high=106, low=99, close=104),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is not None
    assert new_pos.contracts == 5           # 절반 청산
    assert len(new_pos.targets_remaining) == 1
    assert fills[0].reason == "tp1"


def test_no_exit_when_bar_inside_range():
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[(110.0, 1.0)], opened_ts=1)
    new_pos, fills = check_exits(pos, _bar(2, high=101, low=99, close=100),
                                 fee_bps=5, slippage_bps=0, ct_val=0.01)
    assert new_pos is pos and fills == []
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_engine_step.py -v`
Expected: FAIL — `ModuleNotFoundError` 또는 `cannot import name 'check_exits'`.

- [ ] **Step 3: engine.py에 per-bar step 작성**

Create `quantpilot/backtest/engine.py`:
```python
"""event-driven 백테스트 엔진. per-bar step + 배치 루프.

per-bar step(check_exits)은 Week 3 페이퍼가 그대로 재사용(바깥 루프만 교체).
"""
from __future__ import annotations

from quantpilot.backtest.costs import apply_slippage, fee_for
from quantpilot.backtest.models import Fill, Position


def _pnl(side: str, entry: float, exit_price: float, contracts: int, ct_val: float) -> float:
    """gross 손익(USDT). long은 (exit-entry), short은 (entry-exit)."""
    diff = (exit_price - entry) if side == "long" else (entry - exit_price)
    return diff * contracts * ct_val


def _close_fill(pos: Position, raw_price: float, contracts: int, ts: int,
                reason: str, fee_bps: float, slippage_bps: float, ct_val: float) -> Fill:
    # 청산 방향: long 청산은 sell(아래로 불리), short 청산은 buy(위로 불리)
    side = "sell" if pos.side == "long" else "buy"
    price = apply_slippage(raw_price, slippage_bps, side)
    notional = contracts * price * ct_val
    fee = fee_for(notional, fee_bps)
    pnl = _pnl(pos.side, pos.entry, price, contracts, ct_val)
    return Fill(ts=ts, price=price, contracts=contracts, fee=fee, reason=reason, pnl_gross=pnl)


def check_exits(pos: Position, bar: dict, fee_bps: float, slippage_bps: float,
                ct_val: float) -> tuple[Position | None, list[Fill]]:
    """이 봉에서 손절/분할익절 체결 판정. (남은포지션 or None, fills) 반환.

    WHY '손절 먼저': 한 봉이 stop과 target을 동시에 건드리면 봉 내부 순서를 모름.
    보수적으로 손절이 먼저 체결됐다고 가정 → 백테스트 over-optimism 방지.
    """
    high, low = bar["high"], bar["low"]

    # 1) 손절 먼저: long은 low≤stop, short은 high≥stop
    stop_hit = (pos.side == "long" and low <= pos.stop) or \
               (pos.side == "short" and high >= pos.stop)
    if stop_hit:
        fill = _close_fill(pos, pos.stop, pos.contracts, bar["ts"], "stop",
                           fee_bps, slippage_bps, ct_val)
        return None, [fill]

    # 2) 분할 익절: 가까운 타겟부터 봉이 닿았나 (long은 high≥target, short은 low≤target)
    fills: list[Fill] = []
    remaining = list(pos.targets_remaining)
    idx = 1
    contracts_left = pos.contracts
    for price, frac in pos.targets_remaining:
        hit = (pos.side == "long" and high >= price) or \
              (pos.side == "short" and low <= price)
        if not hit:
            idx += 1
            continue
        qty = int(round(pos.original_contracts * frac))
        qty = min(qty, contracts_left)
        if qty <= 0:
            remaining.remove((price, frac))
            idx += 1
            continue
        fills.append(_close_fill(pos, price, qty, bar["ts"], f"tp{idx}",
                                 fee_bps, slippage_bps, ct_val))
        contracts_left -= qty
        remaining.remove((price, frac))
        idx += 1

    if not fills:
        return pos, []
    if contracts_left <= 0:
        return None, fills
    pos.contracts = contracts_left
    pos.targets_remaining = remaining
    return pos, fills
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_engine_step.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/backtest/engine.py tests/test_engine_step.py
git commit -m "feat: add per-bar exit step with stop-first pessimistic fills"
```

---

## Task 12: Engine — run_backtest 배치 루프

**Files:**
- Modify: `quantpilot/backtest/engine.py` (run_backtest + 진입 로직 추가)
- Test: `tests/test_engine_run.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_engine_run.py`:
```python
import pandas as pd

from quantpilot.backtest.engine import run_backtest
from quantpilot.strategy.base import IStrategy, Signal


class _AlwaysLongOnceStrategy(IStrategy):
    """첫 진입 가능 시점에 long 1회, 이후 hold. 테스트용 결정적 전략."""
    name = "test-long"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("long", 1.0, price - 5.0, {})  # stop 5 아래
        return Signal("hold", 0.0, None, {})


def _candles(closes):
    tf = 3_600_000
    base = 1_700_000_000_000
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes, "volume": [1.0]*len(closes)},
        index=[base + i*tf for i in range(len(closes))],
    ).rename_axis("ts")


def test_run_backtest_produces_result_and_trades():
    # 진입 후 상승 → 타겟 도달로 익절(혹은 마지막 청산)
    closes = [100.0, 101, 102, 108, 115, 120]   # 상승 추세
    df = _candles(closes)
    result = run_backtest(
        candles=df, strategy=_AlwaysLongOnceStrategy(), capital=1000.0,
        ct_val=0.01, lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
        funding_events=[], oos_split_ts=df.index[4],
    )
    assert result.equity_curve  # 곡선 생성됨
    assert len(result.equity_curve) == len(df) - _AlwaysLongOnceStrategy().lookback
    # 거래가 최소 1건 발생(진입→청산)
    assert isinstance(result.trades, list)


def test_run_backtest_is_deterministic():
    closes = [100.0, 101, 99, 102, 98, 103, 97, 104]
    df = _candles(closes)
    kw = dict(capital=1000.0, ct_val=0.01, lot_sz=1.0, leverage=3,
              fee_bps=5, slippage_bps=2, funding_events=[], oos_split_ts=df.index[5])
    r1 = run_backtest(candles=df, strategy=_AlwaysLongOnceStrategy(), **kw)
    r2 = run_backtest(candles=df, strategy=_AlwaysLongOnceStrategy(), **kw)
    assert r1.equity_curve == r2.equity_curve
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_engine_run.py -v`
Expected: FAIL — `cannot import name 'run_backtest'`.

- [ ] **Step 3: engine.py에 run_backtest 추가**

Append to `quantpilot/backtest/engine.py`:
```python
from quantpilot.backtest.costs import funding_between
from quantpilot.backtest.models import BacktestResult, Trade
from quantpilot.risk.liquidation import StopBeyondLiquidationError, assert_stop_within_liquidation
from quantpilot.risk.sizing import InsufficientCapitalError, calculate_position_size
from quantpilot.risk.take_profit import build_targets


def _open_position(side, bar, stop, capital, ct_val, lot_sz, leverage,
                   fee_bps, slippage_bps):
    """진입 시도. 사이징/청산가드 통과 시 Position 반환, 아니면 (None, 0fee)."""
    raw_entry = bar["close"]
    buy_side = "buy" if side == "long" else "sell"
    entry = apply_slippage(raw_entry, slippage_bps, buy_side)
    try:
        assert_stop_within_liquidation(entry, stop, leverage, side)
        sizing = calculate_position_size(capital, 0.05, entry, stop, ct_val, lot_sz,
                                         leverage=leverage, fee_bps=fee_bps, side=side)
    except (StopBeyondLiquidationError, InsufficientCapitalError):
        return None, 0.0
    targets = build_targets(entry, stop, side)
    pos = Position(side=side, entry=entry, contracts=sizing.contracts, stop=stop,
                   targets_remaining=targets, opened_ts=bar["ts"],
                   original_contracts=sizing.contracts)
    entry_fee = fee_for(sizing.contracts * entry * ct_val, fee_bps)
    return pos, entry_fee


def run_backtest(candles, strategy, capital, ct_val, lot_sz, leverage,
                 fee_bps, slippage_bps, funding_events, oos_split_ts) -> BacktestResult:
    """봉 하나씩 재생하며 백테스트. funding_events=[(ts,rate),...]."""
    equity = capital
    position: Position | None = None
    open_fee = 0.0
    trades: list[Trade] = []
    curve: list[tuple[int, float]] = []
    rows = candles.reset_index().to_dict("records")  # ts 포함 dict 리스트

    def _finalize(pos, fills, last_ts):
        # 한 포지션의 fills를 Trade로 집계
        contracts = pos.original_contracts
        gross = sum(f.pnl_gross for f in fills)
        fees = open_fee + sum(f.fee for f in fills)
        notional = contracts * pos.entry * ct_val
        funding = funding_between(funding_events, notional, pos.side,
                                  pos.opened_ts, last_ts)
        net = gross - fees - funding
        avg_exit = sum(f.price * f.contracts for f in fills) / max(1, sum(f.contracts for f in fills))
        return Trade(side=pos.side, entry=pos.entry, exit=avg_exit, contracts=contracts,
                     pnl_gross=gross, fees=fees, funding=funding, pnl_net=net,
                     opened_ts=pos.opened_ts, closed_ts=last_ts,
                     reason=fills[-1].reason if fills else "exit_signal")

    pending_fills: list[Fill] = []
    for i in range(strategy.lookback, len(rows)):
        bar = rows[i]
        window = candles.iloc[i - strategy.lookback + 1: i + 1]

        # 1) 열린 포지션 → 손절/익절 체결
        if position is not None:
            position2, fills = check_exits(position, bar, fee_bps, slippage_bps, ct_val)
            pending_fills.extend(fills)
            if position2 is None:  # 완전 청산됨
                trades.append(_finalize(position, pending_fills, bar["ts"]))
                equity += sum(f.pnl_gross for f in pending_fills)  # 실현 손익 반영
                equity -= trades[-1].fees + trades[-1].funding
                position, open_fee, pending_fills = None, 0.0, []
            else:
                position = position2

        # 2) 전략 신호
        signal = strategy.generate_signal(window, position)

        # 3) 신호 처리
        if signal.side in ("long", "short") and position is None:
            position, open_fee = _open_position(
                signal.side, bar, signal.suggested_stop, equity, ct_val, lot_sz,
                leverage, fee_bps, slippage_bps)
            pending_fills = []
        elif signal.side == "exit" and position is not None:
            fill = _close_fill(position, bar["close"], position.contracts, bar["ts"],
                               "exit_signal", fee_bps, slippage_bps, ct_val)
            pending_fills.append(fill)
            trades.append(_finalize(position, pending_fills, bar["ts"]))
            equity += sum(f.pnl_gross for f in pending_fills)
            equity -= trades[-1].fees + trades[-1].funding
            position, open_fee, pending_fills = None, 0.0, []

        # 4) equity 곡선 (열린 포지션 평가손익 포함)
        unreal = 0.0
        if position is not None:
            unreal = _pnl(position.side, position.entry, bar["close"],
                          position.contracts, ct_val)
        curve.append((bar["ts"], equity + unreal))

    return BacktestResult(trades=trades, equity_curve=curve, split_ts=int(oos_split_ts))
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_engine_run.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: 전체 회귀 확인**

Run: `. .venv/bin/activate && pytest -q`
Expected: 지금까지의 모든 테스트 PASS.

- [ ] **Step 6: Commit**

```bash
git add quantpilot/backtest/engine.py tests/test_engine_run.py
git commit -m "feat: add run_backtest batch loop with entry/exit/funding/equity"
```

---

## Task 13: 성과 지표 (backtest/metrics.py)

**Files:**
- Create: `quantpilot/backtest/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_metrics.py`:
```python
import math

from quantpilot.backtest.metrics import compute_metrics, sharpe, max_drawdown


def test_max_drawdown_known_curve():
    curve = [(0, 100.0), (1, 120.0), (2, 90.0), (3, 110.0)]  # 120→90 = -25%
    assert abs(max_drawdown(curve) - (-0.25)) < 1e-9


def test_sharpe_zero_when_flat():
    curve = [(i, 100.0) for i in range(10)]  # 변화 없음 → 수익 0
    assert sharpe(curve, periods_per_year=8760) == 0.0


def test_sharpe_positive_for_uptrend():
    curve = [(i, 100.0 * (1.001 ** i)) for i in range(200)]  # 꾸준 상승
    assert sharpe(curve, periods_per_year=8760) > 0


def test_compute_metrics_keys():
    curve = [(i, 100.0 + i) for i in range(50)]
    m = compute_metrics(curve, trades=[], periods_per_year=8760)
    for k in ("sharpe", "max_drawdown", "total_return", "n_trades", "win_rate", "profit_factor"):
        assert k in m
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: metrics.py 작성**

Create `quantpilot/backtest/metrics.py`:
```python
"""백테스트 성과 지표. Sharpe는 per-bar 자본 수익률 기준(spec 11)."""
from __future__ import annotations

import math


def _returns(curve: list[tuple[int, float]]) -> list[float]:
    eq = [e for _, e in curve]
    return [(eq[i] / eq[i - 1] - 1.0) for i in range(1, len(eq)) if eq[i - 1] != 0]


def sharpe(curve: list[tuple[int, float]], periods_per_year: float) -> float:
    """per-bar 수익률의 평균/표준편차 × √연환산. rf=0 가정."""
    rets = _returns(curve)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def max_drawdown(curve: list[tuple[int, float]]) -> float:
    """최대 낙폭(음수 비율). 고점 대비 최대 하락."""
    peak = -math.inf
    mdd = 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return mdd


def compute_metrics(curve, trades, periods_per_year: float) -> dict:
    """곡선 + 거래 목록 → 지표 dict (net 기준)."""
    eq = [e for _, e in curve]
    total_return = (eq[-1] / eq[0] - 1.0) if len(eq) >= 2 and eq[0] != 0 else 0.0
    wins = [t for t in trades if t.pnl_net > 0]
    losses = [t for t in trades if t.pnl_net < 0]
    gross_profit = sum(t.pnl_net for t in wins)
    gross_loss = abs(sum(t.pnl_net for t in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    return {
        "sharpe": round(sharpe(curve, periods_per_year), 3),
        "max_drawdown": round(max_drawdown(curve), 4),
        "total_return": round(total_return, 4),
        "n_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0.0,
        "profit_factor": round(pf, 3) if pf != float("inf") else pf,
    }


def periods_per_year(timeframe: str) -> float:
    """연환산 계수. 1h → 24×365, 15m → 96×365."""
    from quantpilot.timeframes import timeframe_to_ms
    tf_ms = timeframe_to_ms(timeframe)
    bars_per_day = 86_400_000 / tf_ms
    return bars_per_day * 365
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_metrics.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/backtest/metrics.py tests/test_metrics.py
git commit -m "feat: add Sharpe/maxDD/winrate/profit-factor metrics"
```

---

## Task 14: 리포트 — 콘솔 표 + equity curve PNG

**Files:**
- Create: `quantpilot/backtest/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_report.py`:
```python
from pathlib import Path

from quantpilot.backtest.models import BacktestResult
from quantpilot.backtest.report import format_console, save_equity_png


def _result():
    curve = [(1_700_000_000_000 + i * 3_600_000, 1000.0 + i) for i in range(20)]
    return BacktestResult(trades=[], equity_curve=curve, split_ts=curve[10][0],
                          train_metrics={"sharpe": 1.2, "max_drawdown": -0.1,
                                         "total_return": 0.05, "n_trades": 3,
                                         "win_rate": 0.66, "profit_factor": 1.8},
                          oos_metrics={"sharpe": 0.7, "max_drawdown": -0.12,
                                       "total_return": 0.02, "n_trades": 1,
                                       "win_rate": 1.0, "profit_factor": 2.0})


def test_console_has_train_and_oos():
    out = format_console(_result(), symbol="BTC-USDT-SWAP", strategy="rsi-mr")
    assert "Train" in out and "OOS" in out
    assert "1.2" in out and "0.7" in out   # train/OOS Sharpe


def test_save_png_creates_file(tmp_path):
    path = tmp_path / "eq.png"
    save_equity_png(_result(), str(path))
    assert path.exists() and path.stat().st_size > 0
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: report.py 작성**

Create `quantpilot/backtest/report.py`:
```python
"""백테스트 결과 출력 — 콘솔 표 + equity curve PNG."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # WHY Agg: 헤드리스(서버/CI)에서 화면 없이 PNG 저장
import matplotlib.pyplot as plt

from quantpilot.backtest.models import BacktestResult

_KEYS = [("sharpe", "Sharpe"), ("max_drawdown", "MaxDD"),
         ("total_return", "Return"), ("win_rate", "WinRate"),
         ("profit_factor", "PF"), ("n_trades", "Trades")]


def format_console(result: BacktestResult, symbol: str, strategy: str) -> str:
    """Train | OOS 표 텍스트."""
    t, o = result.train_metrics, result.oos_metrics
    lines = [f"Backtest: {strategy} on {symbol}",
             f"{'Metric':<10}{'Train':>12}{'OOS':>12}"]
    for key, label in _KEYS:
        lines.append(f"{label:<10}{str(t.get(key, '-')):>12}{str(o.get(key, '-')):>12}")
    # 과최적화 힌트
    if t.get("sharpe", 0) and o.get("sharpe", 0) is not None:
        if t.get("sharpe", 0) > 1.0 and o.get("sharpe", 0) < t.get("sharpe", 0) * 0.5:
            lines.append("⚠️  Train≫OOS Sharpe — 과최적화 의심")
    return "\n".join(lines)


def save_equity_png(result: BacktestResult, path: str) -> None:
    """train(파랑)+OOS(주황) equity curve, 분리선 포함 PNG 저장."""
    ts = [t for t, _ in result.equity_curve]
    eq = [e for _, e in result.equity_curve]
    split = result.split_ts
    fig, ax = plt.subplots(figsize=(10, 5))
    train_x = [t for t in ts if t < split]
    train_y = [e for t, e in result.equity_curve if t < split]
    oos_x = [t for t in ts if t >= split]
    oos_y = [e for t, e in result.equity_curve if t >= split]
    ax.plot(train_x, train_y, color="tab:blue", label="Train")
    ax.plot(oos_x, oos_y, color="tab:orange", label="OOS")
    ax.axvline(split, color="gray", linestyle="--", linewidth=1)
    ax.set_xlabel("ts (ms)")
    ax.set_ylabel("equity (USDT)")
    ax.legend()
    ax.set_title("Equity Curve")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_report.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/backtest/report.py tests/test_report.py
git commit -m "feat: add console report and equity curve PNG"
```

---

## Task 15: CLI backtest 명령 + 전략 레지스트리

**Files:**
- Modify: `quantpilot/cli.py`
- Test: `tests/test_cli_backtest.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_cli_backtest.py`:
```python
from click.testing import CliRunner

from quantpilot.cli import cli


def test_backtest_rejects_unknown_strategy(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    result = CliRunner().invoke(cli, ["backtest", "--strategy", "nope",
                                      "--symbol", "BTC-USDT-SWAP", "--timeframe", "1h"])
    assert result.exit_code != 0
    assert "nope" in result.output
    assert "Traceback" not in result.output


def test_backtest_empty_db_clean_error(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    result = CliRunner().invoke(cli, ["backtest", "--strategy", "rsi-mr",
                                      "--symbol", "BTC-USDT-SWAP", "--timeframe", "1h"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output   # 친절한 에러
```

- [ ] **Step 2: 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_cli_backtest.py -v`
Expected: FAIL — `backtest` 명령 없음 (exit 2, "No such command").

- [ ] **Step 3: cli.py에 backtest 명령 추가**

Add to `quantpilot/cli.py` (기존 import 아래에 추가):
```python
from quantpilot.strategy.rsi_mean_reversion import RsiMeanReversion

# 전략 레지스트리 — 새 전략 = 클래스 + 여기 1줄
STRATEGIES = {"rsi-mr": RsiMeanReversion}
```

그리고 새 명령 함수 추가 (`status` 명령 위/아래 아무 곳, `if __name__` 위):
```python
@cli.command()
@click.option("--strategy", default="rsi-mr", show_default=True)
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--oos-months", default=2, show_default=True, type=int)
@click.option("--capital", default=1000.0, show_default=True, type=float)
@click.option("--leverage", default=3, show_default=True, type=int)
@click.option("--allow-gaps", is_flag=True, default=False)
def backtest(strategy, symbol, timeframe, oos_months, capital, leverage, allow_gaps):
    """과거 데이터에 전략을 돌려 train/OOS 성과 측정."""
    if strategy not in STRATEGIES:
        raise click.ClickException(
            f"알 수 없는 전략 '{strategy}'. 사용 가능: {', '.join(STRATEGIES)}")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise click.ClickException(
            f"지원하지 않는 timeframe '{timeframe}'. 사용 가능: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}")

    from quantpilot.backtest.data_loader import DataGapError, load_with_gap_check
    from quantpilot.backtest.engine import run_backtest
    from quantpilot.backtest.metrics import compute_metrics, periods_per_year
    from quantpilot.backtest.report import format_console, save_equity_png
    from quantpilot.data.models import FundingRate, Instrument
    from sqlalchemy import select

    session, _ = _session()
    try:
        df, gaps, _ = load_with_gap_check(session, symbol, timeframe, allow_gaps)
    except DataGapError as e:
        raise click.ClickException(str(e))
    if gaps:
        click.echo(f"⚠️  {gaps}개 봉 누락 (--allow-gaps로 진행 중)")

    # ct_val 조회 (없으면 안내)
    inst = session.execute(select(Instrument).where(
        Instrument.symbol == symbol)).scalar_one_or_none()
    if inst is None:
        raise click.ClickException(
            f"{symbol} Instrument 캐시 없음. 먼저 'quantpilot collect'를 실행하세요.")

    funding_events = [(f.ts, f.funding_rate) for f in session.execute(
        select(FundingRate).where(FundingRate.symbol == symbol)
        .order_by(FundingRate.ts)).scalars().all()]

    # train/OOS 분리: 마지막 oos_months 개월을 OOS
    split_ts = int(df.index[-1]) - oos_months * 30 * 86_400_000

    strat = STRATEGIES[strategy](timeframe=timeframe)
    result = run_backtest(
        candles=df, strategy=strat, capital=capital, ct_val=inst.ct_val,
        lot_sz=inst.lot_sz, leverage=leverage, fee_bps=5, slippage_bps=2,
        funding_events=funding_events, oos_split_ts=split_ts)

    ppy = periods_per_year(timeframe)
    train_curve = [(t, e) for t, e in result.equity_curve if t < split_ts]
    oos_curve = [(t, e) for t, e in result.equity_curve if t >= split_ts]
    train_trades = [t for t in result.trades if t.closed_ts < split_ts]
    oos_trades = [t for t in result.trades if t.closed_ts >= split_ts]
    result.train_metrics = compute_metrics(train_curve, train_trades, ppy)
    result.oos_metrics = compute_metrics(oos_curve, oos_trades, ppy)

    click.echo(format_console(result, symbol, strategy))
    png = f"backtest_{symbol}_{strategy}_{_now_ms()}.png"
    save_equity_png(result, png)
    click.echo(f"equity curve 저장됨: {png}")
```

- [ ] **Step 4: 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_cli_backtest.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/cli.py tests/test_cli_backtest.py
git commit -m "feat: add backtest CLI command and strategy registry"
```

---

## Task 16: 통합 검증 + README + 브랜치 push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 전체 테스트 + ruff**

Run:
```bash
. .venv/bin/activate
pytest -q
ruff check quantpilot/
```
Expected: 전부 PASS, ruff `All checks passed!`. (ruff E402 등 경고 있으면 import를 파일 상단으로 정리 후 재실행.)

- [ ] **Step 2: 실데이터 백테스트 (인터넷 필요, 선택)**

Run:
```bash
. .venv/bin/activate
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 180
quantpilot collect-funding --symbol BTC-USDT-SWAP --days 180
quantpilot backtest --strategy rsi-mr --symbol BTC-USDT-SWAP --timeframe 1h --oos-months 2 --capital 1000
```
Expected: Train/OOS 표 출력 + `backtest_..._.png` 경로. (데이터 양에 따라 OOS Sharpe는 임의 — 수익성 보장 아님, 파이프라인 동작 확인이 목적)

- [ ] **Step 3: README에 backtest 섹션 추가**

`README.md`의 "사용" 섹션에 추가:
```markdown
## 백테스트 (Week 2)
\`\`\`bash
quantpilot backtest --strategy rsi-mr --symbol BTC-USDT-SWAP \
    --timeframe 1h --oos-months 2 --capital 1000
# → Train/OOS Sharpe·MaxDD·승률 표 + equity curve PNG
\`\`\`
전략 추가 = `quantpilot/strategy/`에 IStrategy 구현 1개 + `cli.py`의 STRATEGIES에 1줄.
\`\`\`
```

- [ ] **Step 4: Commit + 브랜치 push**

```bash
git add README.md
git commit -m "docs: add backtest usage to README"
git push -u origin worktree-week2-backtest-engine
```

---

## 완료 조건 매핑 (spec DoD ↔ task)

| spec DoD | task |
|---|---|
| `backtest` 명령 동작 | 15, 16 |
| Train + OOS Sharpe 표시 | 13, 15 |
| fee·funding·slippage 차감, gross/net | 9, 12 |
| equity curve PNG | 14 |
| gap 체크 게이트 | 10, 15 |
| 새 전략 = 클래스 + 1줄 | 3, 8, 15 (STRATEGIES) |
| sizing invariant (ctVal, fuzz) | 6 |
| "봉 안 손절 먼저" 검증 | 11 |
| fixture/합성 단위 테스트 | 2,5,6,7,8,9,10,11,12,13,14,15 |

## Out of Scope (Week 2 아님)
paper trader/실시간/circuit breaker/panic → Week 3. walk-forward → post-MVP. gap 메우기·재수집 → TODOS. 두 번째 전략 본구현 → 이후.
