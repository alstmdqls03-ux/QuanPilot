# Week 1 Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OKX의 시장 데이터(가격 캔들 + funding rate)를 ccxt로 받아 로컬 SQLite에 idempotent하게 적재하는 CLI 토대를 만든다.

**Architecture:** ccxt unified API로 OKX public 엔드포인트만 호출(키 불필요). SQLAlchemy 3개 테이블(Candle/FundingRate/Instrument)에 int ms epoch 타임스탬프로 저장. collector는 "마지막 저장 ts 다음부터" 증분 수집하고 unique 제약 기반 upsert로 중복을 무시한다. click 기반 CLI로 collect/collect-funding/status 제공.

**Tech Stack:** Python 3.11, ccxt, SQLAlchemy 2.x (classic Column 스타일), pydantic-settings, click, pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-week1-data-foundation-design.md`

**프로젝트 컨벤션 (spec section 12 — 모든 task에 적용):**
- DB/스키마 코드에는 **항상 WHY 주석** (왜 이 타입/제약/구조인지).
- 타임스탬프는 전부 **int ms epoch (UTC)**.
- **YAGNI** — 쓰는 코드와 함께만 추가.
- 사용자는 트레이딩/봇 초보 → 주석·docstring으로 개념 설명 곁들임.

---

## File Structure

```
quantpilot/
├── __init__.py
├── config.py              # pydantic-settings: DB 경로, 거래소
├── timeframes.py          # "1h"/"15m" → ms 변환 (순수 함수)
├── exchange/
│   ├── __init__.py
│   ├── client.py          # ccxt.okx 래퍼: 심볼 변환 + fetch (거래소 통신만)
│   └── instruments.py     # ccxt market dict → Instrument 필드 파싱 (순수 함수)
├── data/
│   ├── __init__.py
│   ├── db.py              # SQLAlchemy Base, engine, session factory
│   ├── models.py          # Candle, FundingRate, Instrument
│   └── collector.py       # 증분 수집 + upsert 로직
└── cli.py                 # click: collect, collect-funding, status

tests/
├── __init__.py
├── conftest.py            # in-memory DB fixture, 가짜 client
├── fixtures/
│   ├── ohlcv_btc_1h.json  # 저장된 OKX OHLCV 응답
│   ├── funding_btc.json   # 저장된 funding 응답
│   └── market_btc.json    # 저장된 market(instrument) dict
├── test_models.py
├── test_timeframes.py
├── test_client.py
├── test_instruments.py
├── test_collector.py
└── test_live.py           # @pytest.mark.live (수동)

pyproject.toml
.env.example
README.md
```

**책임 분리 이유:** `client.py`가 거래소 통신만 담당하면 나중에 Binance 추가 시 거기만 교체. `collector.py`는 "무엇을/언제 받을지"만 결정하고 ccxt 세부는 client에 위임. `timeframes.py`/`instruments.py`는 순수 함수라 네트워크 없이 테스트 가능.

---

## Task 1: 프로젝트 스캐폴딩 & 툴링

**Files:**
- Create: `pyproject.toml`
- Create: `quantpilot/__init__.py`, `quantpilot/exchange/__init__.py`, `quantpilot/data/__init__.py`
- Create: `tests/__init__.py`
- Create: `.env.example`

- [ ] **Step 1: pyproject.toml 작성**

Create `pyproject.toml`:
```toml
[project]
name = "quantpilot"
version = "0.1.0"
description = "OKX edge lab — Week 1 data foundation"
requires-python = ">=3.11"
dependencies = [
    "ccxt>=4.2",
    "SQLAlchemy>=2.0",
    "pydantic-settings>=2.0",
    "click>=8.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
]

[project.scripts]
quantpilot = "quantpilot.cli:cli"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
markers = [
    "live: 실제 OKX API를 호출하는 테스트 (수동 실행: pytest -m live)",
]
# WHY: 기본 실행(pytest)에서 live 테스트를 자동 제외해 빠르고 결정적으로 유지.
addopts = "-m 'not live'"

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2: 패키지 디렉토리와 빈 __init__.py 생성**

```bash
mkdir -p quantpilot/exchange quantpilot/data tests/fixtures
touch quantpilot/__init__.py quantpilot/exchange/__init__.py quantpilot/data/__init__.py tests/__init__.py
```

- [ ] **Step 3: .env.example 작성**

Create `.env.example`:
```
# Week 1은 OKX public 데이터만 쓰므로 API 키가 필요 없음.
# 아래는 Week 3(실주문) 때 채울 자리 — 지금은 비워둬도 됨.
# OKX_API_KEY=
# OKX_API_SECRET=
# OKX_PASSPHRASE=

# 로컬 SQLite DB 경로 (기본값과 동일, 바꾸고 싶을 때만 설정)
QUANTPILOT_DB_PATH=data/quantpilot.db
```

- [ ] **Step 4: 가상환경 생성 + 설치**

Run:
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```
Expected: `Successfully installed ccxt ... SQLAlchemy ... click ... pytest ...`

- [ ] **Step 5: pytest가 도는지 확인 (아직 테스트 0개)**

Run: `. .venv/bin/activate && pytest`
Expected: `no tests ran` (collected 0 items). 에러 없이 종료되면 OK.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml quantpilot/ tests/ .env.example
git commit -m "chore: scaffold quantpilot package and tooling"
```

---

## Task 2: 데이터베이스 레이어 + 모델

**Files:**
- Create: `quantpilot/data/db.py`
- Create: `quantpilot/data/models.py`
- Create: `tests/conftest.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: db.py 작성 (Base, engine, session)**

Create `quantpilot/data/db.py`:
```python
"""SQLAlchemy 엔진/세션 팩토리.

WHY 분리: 모델(models.py)과 엔진 생성을 나눠 두면 테스트에서
in-memory SQLite로 쉽게 갈아끼울 수 있음.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 모든 모델이 상속하는 베이스. models.py가 이걸 import.
Base = declarative_base()


def make_engine(db_url: str):
    """db_url로 엔진 생성. 예: 'sqlite:///data/quantpilot.db'"""
    # WHY future=True: SQLAlchemy 2.x 스타일 동작 보장.
    return create_engine(db_url, future=True)


def make_session_factory(engine):
    """세션 팩토리 생성. 호출부에서 SessionLocal() 로 세션 획득."""
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db(engine) -> None:
    """모든 테이블 생성 (이미 있으면 무시). 앱/테스트 시작 시 1회 호출."""
    # models를 import해야 Base.metadata에 테이블이 등록됨.
    from quantpilot.data import models  # noqa: F401

    Base.metadata.create_all(engine)
```

- [ ] **Step 2: 실패하는 테스트 작성 (모델 + unique 제약)**

Create `tests/conftest.py`:
```python
import pytest

from quantpilot.data.db import make_engine, make_session_factory, init_db


@pytest.fixture
def session():
    """테스트용 in-memory SQLite 세션. 매 테스트마다 새 DB.

    WHY in-memory: 디스크 안 건드리고 빠르며, 테스트 간 격리됨.
    """
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = make_session_factory(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
```

Create `tests/test_models.py`:
```python
import pytest
from sqlalchemy.exc import IntegrityError

from quantpilot.data.models import Candle, FundingRate, Instrument


def test_insert_and_read_candle(session):
    session.add(Candle(
        exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
        ts=1_700_000_000_000, open=100.0, high=110.0, low=95.0,
        close=105.0, volume=1234.0, inserted_at=1_700_000_001_000,
    ))
    session.commit()
    row = session.query(Candle).one()
    assert row.symbol == "BTC-USDT-SWAP"
    assert row.close == 105.0


def test_candle_unique_constraint_blocks_duplicate(session):
    # 같은 (exchange, symbol, timeframe, ts)는 단 1행이어야 함 (idempotency 토대).
    kwargs = dict(
        exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
        ts=1_700_000_000_000, open=1, high=1, low=1, close=1,
        volume=1, inserted_at=1,
    )
    session.add(Candle(**kwargs))
    session.commit()
    session.add(Candle(**kwargs))
    with pytest.raises(IntegrityError):
        session.commit()


def test_funding_and_instrument_insert(session):
    session.rollback()  # 이전 테스트 잔여 상태 정리
    session.add(FundingRate(
        exchange="okx", symbol="BTC-USDT-SWAP",
        ts=1_700_000_000_000, funding_rate=0.0001, inserted_at=1,
    ))
    session.add(Instrument(
        exchange="okx", symbol="BTC-USDT-SWAP", ct_val=0.01,
        ct_val_ccy="BTC", lot_sz=1.0, min_sz=1.0, tick_sz=0.1,
        updated_at=1,
    ))
    session.commit()
    assert session.query(FundingRate).count() == 1
    assert session.query(Instrument).one().ct_val == 0.01
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError` 또는 `ImportError: cannot import name 'Candle'` (models.py 미작성).

- [ ] **Step 4: models.py 작성**

Create `quantpilot/data/models.py`:
```python
# data/models.py
#
# 설계 원칙 (이 파일 전체 적용):
# - 타임스탬프는 전부 int ms epoch (UTC). datetime 객체 안 씀.
#   WHY: SQLite는 네이티브 타임존 타입이 없어서 datetime 저장 시
#        로컬/UTC 혼동 버그가 남. 정수면 모호함 0.
# - 테이블 간 외래키(FK) 없음. symbol 문자열로만 논리적 연결.
#   WHY: 원시 시장 데이터는 append 위주라 참조무결성 강제가 득보다 실.
#        캔들을 instrument 캐시보다 먼저 받을 수도 있음.
from sqlalchemy import (
    BigInteger, Column, Float, Index, Integer, String, UniqueConstraint,
)

from quantpilot.data.db import Base


class Candle(Base):
    """OHLCV 캔들 1개. 거래소 raw 데이터를 그대로 보존."""
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True)
    exchange = Column(String, nullable=False, default="okx")
    symbol = Column(String, nullable=False)       # "BTC-USDT-SWAP"
    timeframe = Column(String, nullable=False)    # "1h" | "15m"
    # WHY String timeframe: ccxt가 문자열로 받음. enum 변환 한 단계 제거.
    ts = Column(BigInteger, nullable=False)       # 캔들 open time, ms epoch UTC
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)        # ccxt OHLCV[5], 계약 수량 기준
    # WHY 단일 volume: 통화환산 volume은 Week 1에서 안 씀(YAGNI).
    inserted_at = Column(BigInteger, nullable=False)  # 적재 시각 ms epoch
    # WHY inserted_at: "이 캔들 언제 받았지?" 디버깅이 의외로 잦음.

    __table_args__ = (
        # 이 unique 제약이 idempotency의 핵심.
        # WHY: 같은 (거래소,심볼,봉,시각)은 단 1행. upsert가 여기 걸려
        #      중복 없이 무시됨. 증분 수집의 토대.
        UniqueConstraint("exchange", "symbol", "timeframe", "ts"),
        Index("ix_candle_lookup", "symbol", "timeframe", "ts"),  # 범위 조회
    )


class FundingRate(Base):
    """선물 funding rate 1개. 8시간마다 1개."""
    __tablename__ = "funding_rates"

    id = Column(Integer, primary_key=True)
    exchange = Column(String, nullable=False, default="okx")
    symbol = Column(String, nullable=False)
    ts = Column(BigInteger, nullable=False)        # funding time, ms epoch UTC
    funding_rate = Column(Float, nullable=False)   # 0.0001 = 0.01%
    inserted_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        # idempotency: 같은 (거래소,심볼,funding시각)은 1행.
        UniqueConstraint("exchange", "symbol", "ts"),
    )


class Instrument(Base):
    """거래 명세 메타데이터. 심볼당 1행. Week 2 sizing이 ct_val을 읽음."""
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True)
    exchange = Column(String, nullable=False, default="okx")
    symbol = Column(String, nullable=False)
    ct_val = Column(Float, nullable=False)         # 계약 면값 (BTC-USDT-SWAP=0.01)
    # WHY 캐시: Week 2 position sizing이 매번 읽음. 미리 받아둠.
    ct_val_ccy = Column(String, nullable=False)    # "BTC"
    lot_sz = Column(Float, nullable=False)         # 최소 주문 증분(계약)
    min_sz = Column(Float, nullable=False)         # 최소 주문 수량
    tick_sz = Column(Float, nullable=False)        # 가격 최소 단위
    updated_at = Column(BigInteger, nullable=False)  # 갱신 시각 ms epoch

    __table_args__ = (UniqueConstraint("exchange", "symbol"),)
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_models.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 6: Commit**

```bash
git add quantpilot/data/db.py quantpilot/data/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: add SQLAlchemy db layer and 3 data models"
```

---

## Task 3: 설정 (config.py)

**Files:**
- Create: `quantpilot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_config.py`:
```python
from quantpilot.config import Settings


def test_default_db_path():
    s = Settings()
    assert s.db_path == "data/quantpilot.db"
    assert s.db_url == "sqlite:///data/quantpilot.db"


def test_env_override(monkeypatch):
    monkeypatch.setenv("QUANTPILOT_DB_PATH", "/tmp/custom.db")
    s = Settings()
    assert s.db_path == "/tmp/custom.db"
    assert s.db_url == "sqlite:////tmp/custom.db"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: quantpilot.config`.

- [ ] **Step 3: config.py 작성**

Create `quantpilot/config.py`:
```python
"""앱 설정. 환경변수(.env) → pydantic-settings로 로드."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUANTPILOT_", env_file=".env", extra="ignore")

    exchange: str = "okx"
    db_path: str = "data/quantpilot.db"

    @property
    def db_url(self) -> str:
        """SQLAlchemy용 URL.

        WHY 절대경로 처리: SQLite는 절대경로 앞에 슬래시가 하나 더 붙음.
        '/tmp/x.db' → 'sqlite:////tmp/x.db', 'data/x.db' → 'sqlite:///data/x.db'.
        """
        if self.db_path.startswith("/"):
            return f"sqlite:///{self.db_path}"
        return f"sqlite:///{self.db_path}"
```

> 참고: 상대/절대 둘 다 `sqlite:///` + 경로로 동작한다 (절대경로는 경로 자체가 `/`로 시작하므로 결과적으로 슬래시 4개가 됨). 분기는 가독성을 위해 남겨둔다.

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_config.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/config.py tests/test_config.py
git commit -m "feat: add pydantic settings with db path config"
```

---

## Task 4: Timeframe 변환 (순수 함수)

**Files:**
- Create: `quantpilot/timeframes.py`
- Test: `tests/test_timeframes.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_timeframes.py`:
```python
import pytest

from quantpilot.timeframes import timeframe_to_ms, SUPPORTED_TIMEFRAMES


def test_known_timeframes():
    assert timeframe_to_ms("1h") == 3_600_000
    assert timeframe_to_ms("15m") == 900_000


def test_supported_set():
    assert "1h" in SUPPORTED_TIMEFRAMES
    assert "15m" in SUPPORTED_TIMEFRAMES


def test_unknown_timeframe_raises():
    with pytest.raises(ValueError) as e:
        timeframe_to_ms("7m")
    assert "7m" in str(e.value)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_timeframes.py -v`
Expected: FAIL — `ModuleNotFoundError: quantpilot.timeframes`.

- [ ] **Step 3: timeframes.py 작성**

Create `quantpilot/timeframes.py`:
```python
"""Timeframe 문자열 ↔ 밀리초 변환.

WHY 별도 모듈: collector·status·테스트 여러 곳에서 쓰는 순수 로직.
한 곳에 모아 두면 봉 길이 계산 버그를 한 군데서만 잡으면 됨.
"""

# Week 1이 지원하는 timeframe만. YAGNI — 5m/1m은 계획 없으니 제외.
_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
}
SUPPORTED_TIMEFRAMES = frozenset(_MS.keys())


def timeframe_to_ms(timeframe: str) -> int:
    """'1h' → 3_600_000. 지원 안 하는 값이면 ValueError(사람 실수, 즉시 중단)."""
    try:
        return _MS[timeframe]
    except KeyError:
        raise ValueError(
            f"지원하지 않는 timeframe '{timeframe}'. "
            f"사용 가능: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}"
        )
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_timeframes.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/timeframes.py tests/test_timeframes.py
git commit -m "feat: add timeframe-to-ms conversion"
```

---

## Task 5: Instrument 파싱 (순수 함수)

**Files:**
- Create: `quantpilot/exchange/instruments.py`
- Create: `tests/fixtures/market_btc.json`
- Test: `tests/test_instruments.py`

- [ ] **Step 1: fixture 작성 (ccxt market dict 형태)**

Create `tests/fixtures/market_btc.json`:
```json
{
  "id": "BTC-USDT-SWAP",
  "symbol": "BTC/USDT:USDT",
  "base": "BTC",
  "quote": "USDT",
  "contractSize": 0.01,
  "precision": { "price": 0.1, "amount": 1 },
  "limits": { "amount": { "min": 1 } },
  "info": {
    "ctVal": "0.01",
    "ctValCcy": "BTC",
    "lotSz": "1",
    "minSz": "1",
    "tickSz": "0.1"
  }
}
```

> WHY fixture: 실제 ccxt market dict의 핵심 필드만 추린 형태. 파싱 로직을 네트워크 없이 결정적으로 검증.

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/test_instruments.py`:
```python
import json
from pathlib import Path

from quantpilot.exchange.instruments import parse_instrument

FIX = Path(__file__).parent / "fixtures"


def test_parse_instrument_from_market():
    market = json.loads((FIX / "market_btc.json").read_text())
    inst = parse_instrument(market, exchange="okx")
    assert inst["exchange"] == "okx"
    assert inst["symbol"] == "BTC-USDT-SWAP"   # OKX 네이티브 id를 저장
    assert inst["ct_val"] == 0.01
    assert inst["ct_val_ccy"] == "BTC"
    assert inst["lot_sz"] == 1.0
    assert inst["min_sz"] == 1.0
    assert inst["tick_sz"] == 0.1
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_instruments.py -v`
Expected: FAIL — `ModuleNotFoundError: quantpilot.exchange.instruments`.

- [ ] **Step 4: instruments.py 작성**

Create `quantpilot/exchange/instruments.py`:
```python
"""ccxt market dict → 우리 Instrument 필드로 파싱 (순수 함수)."""


def parse_instrument(market: dict, exchange: str = "okx") -> dict:
    """ccxt market dict에서 거래 명세를 추출.

    WHY market['id']를 symbol로 저장: ccxt의 'symbol'은 통합표기
    ('BTC/USDT:USDT')지만, 우리 DB·CLI는 OKX 네이티브 id
    ('BTC-USDT-SWAP')로 통일한다 (spec 일관성).

    WHY info[...]에서 읽기: ctVal/lotSz 등은 거래소 고유값이라
    ccxt의 표준 필드가 아니라 market['info'](raw 응답)에 들어있음.
    문자열로 오므로 float 변환 필요.
    """
    info = market["info"]
    return {
        "exchange": exchange,
        "symbol": market["id"],
        "ct_val": float(info["ctVal"]),
        "ct_val_ccy": info["ctValCcy"],
        "lot_sz": float(info["lotSz"]),
        "min_sz": float(info["minSz"]),
        "tick_sz": float(info["tickSz"]),
    }
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_instruments.py -v`
Expected: PASS — 1 passed.

- [ ] **Step 6: Commit**

```bash
git add quantpilot/exchange/instruments.py tests/fixtures/market_btc.json tests/test_instruments.py
git commit -m "feat: add instrument parsing from ccxt market dict"
```

---

## Task 6: Exchange client (ccxt 래퍼)

**Files:**
- Create: `quantpilot/exchange/client.py`
- Create: `tests/fixtures/ohlcv_btc_1h.json`
- Create: `tests/fixtures/funding_btc.json`
- Test: `tests/test_client.py`

client는 ccxt 인스턴스를 주입받아(테스트는 가짜 객체 주입) 응답을 우리 표준 dict로 정규화한다. OKX 네이티브 심볼('BTC-USDT-SWAP')을 ccxt 통합 심볼('BTC/USDT:USDT')로 변환하는 책임도 여기 있다.

- [ ] **Step 1: fixture 작성 (ccxt fetch_ohlcv / funding 반환 형태)**

Create `tests/fixtures/ohlcv_btc_1h.json`:
```json
[
  [1700000000000, 100.0, 110.0, 95.0, 105.0, 1234.0],
  [1700003600000, 105.0, 112.0, 104.0, 108.0, 999.0]
]
```
> ccxt fetch_ohlcv 반환 형태: `[timestamp_ms, open, high, low, close, volume]`의 리스트.

Create `tests/fixtures/funding_btc.json`:
```json
[
  {"timestamp": 1700000000000, "fundingRate": 0.0001, "symbol": "BTC/USDT:USDT"},
  {"timestamp": 1700028800000, "fundingRate": -0.00005, "symbol": "BTC/USDT:USDT"}
]
```

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/test_client.py`:
```python
import json
from pathlib import Path

import ccxt
import pytest

from quantpilot.exchange.client import OKXClient

FIX = Path(__file__).parent / "fixtures"


class FakeCcxt:
    """ccxt.okx 흉내. 네트워크 없이 fixture를 돌려줌."""
    def __init__(self):
        self.markets = {
            "BTC/USDT:USDT": json.loads((FIX / "market_btc.json").read_text())
        }
        self.last_ohlcv_call = None

    def load_markets(self):
        return self.markets

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.last_ohlcv_call = (symbol, timeframe, since, limit)
        return json.loads((FIX / "ohlcv_btc_1h.json").read_text())

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        return json.loads((FIX / "funding_btc.json").read_text())


class FlakyCcxt(FakeCcxt):
    """N번 NetworkError를 던진 뒤 성공. 재시도 로직 검증용."""
    def __init__(self, fail_times):
        super().__init__()
        self._fail = fail_times

    def fetch_ohlcv(self, *a, **k):
        if self._fail > 0:
            self._fail -= 1
            raise ccxt.NetworkError("temporary")
        return super().fetch_ohlcv(*a, **k)


def test_resolve_symbol_translates_native_to_unified():
    c = OKXClient(ccxt_client=FakeCcxt())
    c.load_markets()
    assert c.resolve_symbol("BTC-USDT-SWAP") == "BTC/USDT:USDT"


def test_fetch_ohlcv_normalizes_rows():
    c = OKXClient(ccxt_client=FakeCcxt())
    c.load_markets()
    rows = c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=1700000000000, limit=100)
    assert rows[0] == {
        "ts": 1700000000000, "open": 100.0, "high": 110.0,
        "low": 95.0, "close": 105.0, "volume": 1234.0,
    }
    assert len(rows) == 2


def test_fetch_ohlcv_passes_unified_symbol_to_ccxt():
    fake = FakeCcxt()
    c = OKXClient(ccxt_client=fake)
    c.load_markets()
    c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=123, limit=100)
    # ccxt에는 통합 심볼이 전달돼야 함
    assert fake.last_ohlcv_call[0] == "BTC/USDT:USDT"


def test_fetch_funding_normalizes_rows():
    c = OKXClient(ccxt_client=FakeCcxt())
    c.load_markets()
    rows = c.fetch_funding("BTC-USDT-SWAP", since_ms=1700000000000, limit=100)
    assert rows[0] == {"ts": 1700000000000, "funding_rate": 0.0001}
    assert len(rows) == 2


def test_markets_list_for_instruments():
    c = OKXClient(ccxt_client=FakeCcxt())
    markets = c.load_markets()
    assert "BTC/USDT:USDT" in markets


def test_fetch_ohlcv_retries_on_network_error(monkeypatch):
    # 일시적 NetworkError는 backoff 후 재시도되어 결국 성공해야 함.
    monkeypatch.setattr("quantpilot.exchange.client.time.sleep", lambda *_: None)
    c = OKXClient(ccxt_client=FlakyCcxt(fail_times=2))
    c.load_markets()
    rows = c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=0, limit=100)
    assert len(rows) == 2  # 2번 실패 후 3번째 성공


def test_fetch_ohlcv_gives_up_after_max_attempts(monkeypatch):
    # 계속 실패하면 마지막엔 예외를 올려서 호출부가 알 수 있게 함.
    monkeypatch.setattr("quantpilot.exchange.client.time.sleep", lambda *_: None)
    c = OKXClient(ccxt_client=FlakyCcxt(fail_times=99))
    c.load_markets()
    with pytest.raises(ccxt.NetworkError):
        c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=0, limit=100)
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: quantpilot.exchange.client`.

- [ ] **Step 4: client.py 작성**

Create `quantpilot/exchange/client.py`:
```python
"""OKX ccxt 래퍼. 거래소 통신과 응답 정규화만 담당 (DB 모름).

WHY 래퍼: ccxt 호출을 한 군데로 모으면 (1) OKX 네이티브 심볼↔통합 심볼
변환, (2) 일시적 네트워크 오류 재시도, (3) 거래소 교체를 여기 한 곳에서 처리.
"""
from __future__ import annotations

import time

import ccxt

# 일시적이라 재시도하면 풀리는 오류들 (spec section 8: 종류 A).
# WHY 이 둘만: NetworkError는 타임아웃/일시 단절, RateLimitExceeded는 429.
# 나머지(BadSymbol 등)는 사람이 고쳐야 하므로 재시도 안 함.
_RETRYABLE = (ccxt.NetworkError, ccxt.RateLimitExceeded)


class OKXClient:
    def __init__(self, ccxt_client=None):
        """ccxt_client 주입 가능(테스트는 가짜 주입). 없으면 실제 ccxt 생성."""
        if ccxt_client is None:
            # WHY enableRateLimit: ccxt가 요청 간격을 자동 조절. Week 1엔 직접
            # 토큰버킷 불필요. public 엔드포인트라 API 키도 불필요.
            ccxt_client = ccxt.okx({"enableRateLimit": True})
        self._ccxt = ccxt_client
        self._markets: dict | None = None
        self._id_to_unified: dict[str, str] = {}

    def _retry(self, fn, attempts: int = 4, base_delay: float = 1.0):
        """fn()을 호출하되 일시적 오류면 backoff 후 재시도.

        WHY backoff(1s→2s→4s): 빠르게 다시 때리면 거래소가 더 오래 막음.
        attempts번 모두 실패하면 마지막 예외를 올려 호출부가 알게 함
        (증분 설계라 재실행하면 마지막 저장 ts부터 자동 재개).
        """
        for i in range(attempts):
            try:
                return fn()
            except _RETRYABLE:
                if i == attempts - 1:
                    raise
                time.sleep(base_delay * (2 ** i))

    def load_markets(self) -> dict:
        """마켓 로드 + OKX id → 통합 심볼 매핑 구축."""
        self._markets = self._retry(self._ccxt.load_markets)
        # WHY 매핑: 우리는 'BTC-USDT-SWAP'(네이티브 id)로 다루지만
        # ccxt 호출엔 'BTC/USDT:USDT'(통합 심볼)가 필요.
        self._id_to_unified = {
            m["id"]: unified for unified, m in self._markets.items()
        }
        return self._markets

    def resolve_symbol(self, okx_symbol: str) -> str:
        """'BTC-USDT-SWAP'(네이티브) → 'BTC/USDT:USDT'(ccxt 통합)."""
        if not self._id_to_unified:
            raise RuntimeError("load_markets()를 먼저 호출해야 함")
        try:
            return self._id_to_unified[okx_symbol]
        except KeyError:
            raise ValueError(
                f"심볼 '{okx_symbol}'를 OKX에서 못 찾음. "
                f"네이티브 id 예: BTC-USDT-SWAP"
            )

    def fetch_ohlcv(self, okx_symbol: str, timeframe: str,
                    since_ms: int, limit: int = 100) -> list[dict]:
        """OHLCV 1배치를 정규화된 dict 리스트로 반환."""
        unified = self.resolve_symbol(okx_symbol)
        raw = self._retry(
            lambda: self._ccxt.fetch_ohlcv(unified, timeframe, since=since_ms, limit=limit)
        )
        # ccxt 반환: [ts, open, high, low, close, volume]
        return [
            {"ts": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]}
            for r in raw
        ]

    def fetch_funding(self, okx_symbol: str, since_ms: int,
                      limit: int = 100) -> list[dict]:
        """funding rate 이력 1배치를 정규화된 dict 리스트로 반환."""
        unified = self.resolve_symbol(okx_symbol)
        raw = self._retry(
            lambda: self._ccxt.fetch_funding_rate_history(unified, since=since_ms, limit=limit)
        )
        return [{"ts": r["timestamp"], "funding_rate": r["fundingRate"]} for r in raw]
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_client.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 6: Commit**

```bash
git add quantpilot/exchange/client.py tests/fixtures/ohlcv_btc_1h.json tests/fixtures/funding_btc.json tests/test_client.py
git commit -m "feat: add OKX ccxt client with symbol resolution and normalization"
```

---

## Task 7: Collector — 미완성 봉 제거 (순수 함수)

**Files:**
- Create: `quantpilot/data/collector.py` (drop_unclosed만 먼저)
- Test: `tests/test_collector.py` (drop_unclosed 부분)

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_collector.py`:
```python
from quantpilot.data.collector import drop_unclosed


def test_drop_unclosed_removes_forming_candle():
    tf_ms = 3_600_000  # 1h
    now = 1_700_007_200_000  # 두 번째 봉이 막 열린 시점(아직 안 닫힘)
    rows = [
        {"ts": 1_700_000_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": 1_700_003_600_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": 1_700_007_200_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ]
    kept = drop_unclosed(rows, tf_ms, now)
    # 마지막 봉(ts=...7_200_000)은 ts+tf(...10_800_000) > now 라서 미완성 → 제거.
    # 첫 두 봉은 닫혔으므로 유지.
    assert [r["ts"] for r in kept] == [1_700_000_000_000, 1_700_003_600_000]


def test_drop_unclosed_keeps_all_when_old():
    tf_ms = 3_600_000
    now = 1_800_000_000_000  # 충분히 미래 → 전부 닫힘
    rows = [{"ts": 1_700_000_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    assert len(drop_unclosed(rows, tf_ms, now)) == 1
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_collector.py -v`
Expected: FAIL — `ModuleNotFoundError` 또는 `ImportError: cannot import name 'drop_unclosed'`.

- [ ] **Step 3: collector.py에 drop_unclosed 작성**

Create `quantpilot/data/collector.py`:
```python
"""증분 시장 데이터 수집 + idempotent upsert.

WHY: collector는 "무엇을/언제 받을지"를 결정하고, 거래소 통신 세부는
OKXClient에 위임한다. DB 쓰기는 unique 제약 기반 upsert로 중복을 무시.
"""
from __future__ import annotations


def drop_unclosed(rows: list[dict], timeframe_ms: int, now_ms: int) -> list[dict]:
    """아직 닫히지 않은(형성 중) 캔들을 제거.

    WHY: 형성 중인 봉은 OHLC가 계속 변함. 저장하면 재실행 때 같은 ts인데
    값이 달라져 idempotency가 깨지고 백테스트가 오염됨(lookahead bias).
    봉이 완전히 닫힌 것(ts + 봉길이 <= 현재)만 남긴다.
    """
    return [r for r in rows if r["ts"] + timeframe_ms <= now_ms]
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_collector.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/data/collector.py tests/test_collector.py
git commit -m "feat: add drop_unclosed to filter forming candles"
```

---

## Task 8: Collector — 시작점 조회 + idempotent upsert

**Files:**
- Modify: `quantpilot/data/collector.py` (함수 추가)
- Modify: `tests/test_collector.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 추가**

Append to `tests/test_collector.py`:
```python
from quantpilot.data.collector import (
    last_candle_ts, upsert_candles, last_funding_ts, upsert_funding,
)


def _candle(ts, close=100.0):
    return {"ts": ts, "open": 1, "high": 1, "low": 1, "close": close, "volume": 1}


def test_last_candle_ts_none_when_empty(session):
    assert last_candle_ts(session, "okx", "BTC-USDT-SWAP", "1h") is None


def test_upsert_candles_inserts_and_is_idempotent(session):
    rows = [_candle(1_700_000_000_000), _candle(1_700_003_600_000)]
    new1 = upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=1)
    assert new1 == 2
    # 같은 데이터 재삽입 → 신규 0, 중복 없음
    new2 = upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=1)
    assert new2 == 0
    from quantpilot.data.models import Candle
    assert session.query(Candle).count() == 2


def test_last_candle_ts_returns_max(session):
    rows = [_candle(1_700_000_000_000), _candle(1_700_003_600_000)]
    upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=1)
    assert last_candle_ts(session, "okx", "BTC-USDT-SWAP", "1h") == 1_700_003_600_000


def test_upsert_funding_idempotent(session):
    rows = [{"ts": 1_700_000_000_000, "funding_rate": 0.0001}]
    assert upsert_funding(session, "okx", "BTC-USDT-SWAP", rows, now_ms=1) == 1
    assert upsert_funding(session, "okx", "BTC-USDT-SWAP", rows, now_ms=1) == 0
    assert last_funding_ts(session, "okx", "BTC-USDT-SWAP") == 1_700_000_000_000
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_collector.py -v`
Expected: FAIL — `ImportError: cannot import name 'last_candle_ts'`.

- [ ] **Step 3: collector.py에 함수 추가**

Append to `quantpilot/data/collector.py`:
```python
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from quantpilot.data.models import Candle, FundingRate


def last_candle_ts(session, exchange: str, symbol: str, timeframe: str) -> int | None:
    """이 (거래소,심볼,봉)의 마지막 캔들 ts. 없으면 None.

    WHY: 증분 수집의 시작점. 다음 수집은 여기 다음 봉부터.
    """
    stmt = select(func.max(Candle.ts)).where(
        Candle.exchange == exchange,
        Candle.symbol == symbol,
        Candle.timeframe == timeframe,
    )
    return session.execute(stmt).scalar_one()


def upsert_candles(session, exchange: str, symbol: str, timeframe: str,
                   rows: list[dict], now_ms: int) -> int:
    """캔들 배치를 upsert. 신규 삽입 개수를 반환.

    WHY on_conflict_do_nothing: unique 제약(거래소,심볼,봉,ts)에 걸리는
    중복은 조용히 무시 → 재실행해도 안전(idempotent).
    신규 개수는 삽입 전후 카운트 차이로 계산(executemany rowcount는 비신뢰).
    """
    if not rows:
        return 0

    def _count() -> int:
        stmt = select(func.count()).select_from(Candle).where(
            Candle.exchange == exchange,
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
        return session.execute(stmt).scalar_one()

    before = _count()
    payload = [
        {
            "exchange": exchange, "symbol": symbol, "timeframe": timeframe,
            "ts": r["ts"], "open": r["open"], "high": r["high"],
            "low": r["low"], "close": r["close"], "volume": r["volume"],
            "inserted_at": now_ms,
        }
        for r in rows
    ]
    stmt = sqlite_insert(Candle).values(payload).on_conflict_do_nothing(
        index_elements=["exchange", "symbol", "timeframe", "ts"]
    )
    session.execute(stmt)
    session.commit()
    return _count() - before


def last_funding_ts(session, exchange: str, symbol: str) -> int | None:
    stmt = select(func.max(FundingRate.ts)).where(
        FundingRate.exchange == exchange,
        FundingRate.symbol == symbol,
    )
    return session.execute(stmt).scalar_one()


def upsert_funding(session, exchange: str, symbol: str,
                   rows: list[dict], now_ms: int) -> int:
    """funding 배치를 upsert. 신규 삽입 개수 반환."""
    if not rows:
        return 0

    def _count() -> int:
        stmt = select(func.count()).select_from(FundingRate).where(
            FundingRate.exchange == exchange,
            FundingRate.symbol == symbol,
        )
        return session.execute(stmt).scalar_one()

    before = _count()
    payload = [
        {"exchange": exchange, "symbol": symbol, "ts": r["ts"],
         "funding_rate": r["funding_rate"], "inserted_at": now_ms}
        for r in rows
    ]
    stmt = sqlite_insert(FundingRate).values(payload).on_conflict_do_nothing(
        index_elements=["exchange", "symbol", "ts"]
    )
    session.execute(stmt)
    session.commit()
    return _count() - before
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_collector.py -v`
Expected: PASS — 모든 collector 테스트 통과.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/data/collector.py tests/test_collector.py
git commit -m "feat: add incremental ts lookup and idempotent upsert"
```

---

## Task 9: Collector — 수집 오케스트레이션

**Files:**
- Modify: `quantpilot/data/collector.py` (collect_ohlcv, collect_funding, upsert_instruments)
- Modify: `tests/test_collector.py`

`collect_ohlcv`는 시작점 결정 → 페이지네이션 루프 → drop_unclosed → upsert → 요약을 묶는다. 가짜 client와 in-memory db로 테스트한다.

- [ ] **Step 1: 실패하는 테스트 추가**

Append to `tests/test_collector.py`:
```python
from quantpilot.data.collector import collect_ohlcv, collect_funding, upsert_instruments


class FakeClientForCollect:
    """페이지네이션을 흉내내는 가짜 client.

    since_ms 이후의 봉을 limit개씩 잘라서 돌려줌. 끝나면 빈 리스트.
    """
    def __init__(self, all_rows, kind="ohlcv"):
        self._all = sorted(all_rows, key=lambda r: r["ts"])
        self._kind = kind

    def _page(self, since_ms, limit):
        nxt = [r for r in self._all if r["ts"] >= since_ms][:limit]
        return nxt

    def fetch_ohlcv(self, okx_symbol, timeframe, since_ms, limit=100):
        return self._page(since_ms, limit)

    def fetch_funding(self, okx_symbol, since_ms, limit=100):
        return self._page(since_ms, limit)


def test_collect_ohlcv_backfills_and_drops_unclosed(session):
    tf_ms = 3_600_000
    base = 1_700_000_000_000
    # 5개 봉: 마지막 1개는 미완성이 되도록 now를 설정
    rows = [_candle(base + i * tf_ms) for i in range(5)]
    now = base + 4 * tf_ms + 100  # 5번째 봉(index4)은 아직 안 닫힘
    client = FakeClientForCollect(rows, kind="ohlcv")

    summary = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h",
                            days=1, now_ms=now, page_limit=2)
    from quantpilot.data.models import Candle
    # 미완성 1개 제외 → 4개 저장
    assert session.query(Candle).count() == 4
    assert summary["inserted"] == 4


def test_collect_ohlcv_is_incremental_on_rerun(session):
    tf_ms = 3_600_000
    base = 1_700_000_000_000
    rows = [_candle(base + i * tf_ms) for i in range(4)]
    now = base + 10 * tf_ms  # 전부 닫힘
    client = FakeClientForCollect(rows)

    s1 = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h", days=1, now_ms=now, page_limit=2)
    assert s1["inserted"] == 4
    # 재실행: 신규 0
    s2 = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h", days=1, now_ms=now, page_limit=2)
    assert s2["inserted"] == 0


def test_collect_funding_backfills(session):
    base = 1_700_000_000_000
    eight_h = 8 * 3_600_000
    rows = [{"ts": base + i * eight_h, "funding_rate": 0.0001} for i in range(3)]
    now = base + 100 * eight_h
    client = FakeClientForCollect(rows, kind="funding")
    summary = collect_funding(session, client, "BTC-USDT-SWAP", days=30, now_ms=now, page_limit=2)
    from quantpilot.data.models import FundingRate
    assert session.query(FundingRate).count() == 3
    assert summary["inserted"] == 3


def test_upsert_instruments_writes_row(session):
    import json
    from pathlib import Path

    class FakeClientMarkets:
        def load_markets(self):
            m = json.loads((Path(__file__).parent / "fixtures" / "market_btc.json").read_text())
            return {m["symbol"]: m}

    n = upsert_instruments(session, FakeClientMarkets(), now_ms=1)
    from quantpilot.data.models import Instrument
    assert session.query(Instrument).filter_by(symbol="BTC-USDT-SWAP").one().ct_val == 0.01
    assert n == 1
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_collector.py -v`
Expected: FAIL — `ImportError: cannot import name 'collect_ohlcv'`.

- [ ] **Step 3: collector.py에 오케스트레이션 추가**

Append to `quantpilot/data/collector.py`:
```python
from quantpilot.data.models import Instrument
from quantpilot.exchange.instruments import parse_instrument
from quantpilot.timeframes import timeframe_to_ms

DAY_MS = 86_400_000


def collect_ohlcv(session, client, symbol: str, timeframe: str, days: int,
                  now_ms: int, exchange: str = "okx", page_limit: int = 100) -> dict:
    """OHLCV 증분 수집.

    흐름: 시작점 결정 → 페이지네이션 → 미완성 봉 제거 → upsert → 요약.
    WHY now_ms 주입: 테스트에서 시간을 고정해 결정적으로 만들기 위함.
    """
    tf_ms = timeframe_to_ms(timeframe)

    last = last_candle_ts(session, exchange, symbol, timeframe)
    # WHY: 있으면 다음 봉부터(증분), 없으면 days일 전부터(최초 백필).
    since = (last + tf_ms) if last is not None else (now_ms - days * DAY_MS)

    total_inserted = 0
    cursor = since
    while cursor < now_ms:
        batch = client.fetch_ohlcv(symbol, timeframe, since_ms=cursor, limit=page_limit)
        if not batch:
            break
        # 이미 가진 마지막 ts 이하인 행이 섞여 와도 upsert가 걸러줌.
        closed = drop_unclosed(batch, tf_ms, now_ms)
        total_inserted += upsert_candles(session, exchange, symbol, timeframe, closed, now_ms)
        # 다음 커서: 받은 마지막 봉의 다음 봉.
        cursor = batch[-1]["ts"] + tf_ms
        # WHY batch[-1] 기준: drop_unclosed로 closed가 비어도 커서는 전진해야
        # 무한 루프를 피함(미완성 봉만 남은 마지막 페이지).
        if len(batch) < page_limit:
            break

    return {"symbol": symbol, "timeframe": timeframe, "inserted": total_inserted}


def collect_funding(session, client, symbol: str, days: int, now_ms: int,
                    exchange: str = "okx", page_limit: int = 100) -> dict:
    """funding rate 증분 수집 (8시간 주기). OHLCV와 동일한 증분 패턴."""
    eight_h = 8 * 3_600_000
    last = last_funding_ts(session, exchange, symbol)
    since = (last + eight_h) if last is not None else (now_ms - days * DAY_MS)

    total_inserted = 0
    cursor = since
    while cursor < now_ms:
        batch = client.fetch_funding(symbol, since_ms=cursor, limit=page_limit)
        if not batch:
            break
        total_inserted += upsert_funding(session, exchange, symbol, batch, now_ms)
        cursor = batch[-1]["ts"] + eight_h
        if len(batch) < page_limit:
            break

    return {"symbol": symbol, "inserted": total_inserted}


def upsert_instruments(session, client, now_ms: int, exchange: str = "okx") -> int:
    """거래소 마켓 전체를 받아 Instrument 캐시 upsert. 처리한 행 수 반환.

    WHY: Week 2 sizing이 ct_val을 읽으므로 수집 단계에서 미리 캐시.
    파싱 실패하는 마켓(필드 누락)은 건너뜀.
    """
    markets = client.load_markets()
    count = 0
    for market in markets.values():
        try:
            inst = parse_instrument(market, exchange=exchange)
        except (KeyError, TypeError, ValueError):
            continue  # ctVal 등이 없는 마켓(현물 등)은 스킵
        stmt = sqlite_insert(Instrument).values(
            **inst, updated_at=now_ms
        ).on_conflict_do_update(
            index_elements=["exchange", "symbol"],
            set_={
                "ct_val": inst["ct_val"], "ct_val_ccy": inst["ct_val_ccy"],
                "lot_sz": inst["lot_sz"], "min_sz": inst["min_sz"],
                "tick_sz": inst["tick_sz"], "updated_at": now_ms,
            },
        )
        # WHY on_conflict_do_update: 명세는 바뀔 수 있으니(틱사이즈 등)
        # 캔들과 달리 최신값으로 갱신.
        session.execute(stmt)
        count += 1
    session.commit()
    return count
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_collector.py -v`
Expected: PASS — collector 전체 통과.

- [ ] **Step 5: 전체 테스트 실행**

Run: `. .venv/bin/activate && pytest -v`
Expected: PASS — 지금까지의 모든 테스트 통과.

- [ ] **Step 6: Commit**

```bash
git add quantpilot/data/collector.py tests/test_collector.py
git commit -m "feat: add collect_ohlcv/collect_funding/upsert_instruments orchestration"
```

---

## Task 10: CLI (collect / collect-funding / status)

**Files:**
- Create: `quantpilot/cli.py`
- Test: `tests/test_cli.py`

CLI는 click 기반. 실제 OKXClient 대신 collector 함수를 호출하고, 테스트는 click의 CliRunner + 가짜 client/in-memory db로 검증한다.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_cli.py`:
```python
from click.testing import CliRunner

from quantpilot.cli import cli
from quantpilot.data.db import make_engine, make_session_factory, init_db


def test_status_empty_db(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "BTC-USDT-SWAP" in result.output or "비어" in result.output


def test_collect_rejects_bad_timeframe(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    runner = CliRunner()
    result = runner.invoke(cli, ["collect", "--symbol", "BTC-USDT-SWAP",
                                 "--timeframe", "7m", "--days", "1"])
    assert result.exit_code != 0
    assert "7m" in result.output
```

> WHY CliRunner: 실제 터미널 없이 명령을 호출하고 종료코드·출력을 검사. 네트워크는 안 탐(잘못된 timeframe은 client 호출 전에 거부됨).

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `. .venv/bin/activate && pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: quantpilot.cli`.

- [ ] **Step 3: cli.py 작성**

Create `quantpilot/cli.py`:
```python
"""QuantPilot CLI. Week 1: collect, collect-funding, status.

WHY click: 옵션 파싱·--help·검증을 데코레이터로 공짜 제공.
"""
from __future__ import annotations

import time

import click

from quantpilot.config import Settings
from quantpilot.data.db import init_db, make_engine, make_session_factory
from quantpilot.data.collector import (
    collect_funding, collect_ohlcv, upsert_instruments,
)
from quantpilot.data.models import Candle, FundingRate, Instrument
from quantpilot.timeframes import SUPPORTED_TIMEFRAMES, timeframe_to_ms
from sqlalchemy import func, select


def _session():
    settings = Settings()
    engine = make_engine(settings.db_url)
    init_db(engine)
    return make_session_factory(engine)(), settings


def _now_ms() -> int:
    return int(time.time() * 1000)


@click.group()
def cli():
    """QuantPilot — OKX edge lab (Week 1: 데이터 수집)."""


@cli.command()
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--days", default=365, show_default=True, type=int)
def collect(symbol: str, timeframe: str, days: int):
    """OHLCV 캔들 증분 수집."""
    # 사람 실수(잘못된 timeframe)는 네트워크 타기 전에 즉시 거부.
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise click.ClickException(
            f"지원하지 않는 timeframe '{timeframe}'. "
            f"사용 가능: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}"
        )
    session, _ = _session()
    from quantpilot.exchange.client import OKXClient
    client = OKXClient()
    client.load_markets()
    upsert_instruments(session, client, now_ms=_now_ms())
    summary = collect_ohlcv(session, client, symbol, timeframe, days=days, now_ms=_now_ms())
    click.echo(f"{symbol} {timeframe}: 신규 {summary['inserted']}개 적재")


@cli.command(name="collect-funding")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--days", default=365, show_default=True, type=int)
def collect_funding_cmd(symbol: str, days: int):
    """funding rate 증분 수집."""
    session, _ = _session()
    from quantpilot.exchange.client import OKXClient
    client = OKXClient()
    client.load_markets()
    summary = collect_funding(session, client, symbol, days=days, now_ms=_now_ms())
    click.echo(f"{symbol} funding: 신규 {summary['inserted']}개 적재")


@cli.command()
def status():
    """DB에 적재된 내용 요약 (보고만, 수정 안 함)."""
    session, _ = _session()
    # 심볼별로 그룹 (Week 1은 보통 BTC-USDT-SWAP 1개)
    symbols = [r[0] for r in session.execute(
        select(Candle.symbol).distinct()
    ).all()]
    if not symbols:
        click.echo("DB가 비어 있음. 먼저 'quantpilot collect'를 실행하세요.")
        return
    for sym in symbols:
        click.echo(sym)
        for tf in sorted(SUPPORTED_TIMEFRAMES):
            cnt = session.execute(
                select(func.count()).select_from(Candle).where(
                    Candle.symbol == sym, Candle.timeframe == tf)
            ).scalar_one()
            if cnt == 0:
                continue
            lo = session.execute(select(func.min(Candle.ts)).where(
                Candle.symbol == sym, Candle.timeframe == tf)).scalar_one()
            hi = session.execute(select(func.max(Candle.ts)).where(
                Candle.symbol == sym, Candle.timeframe == tf)).scalar_one()
            # 예상 봉 수 = (범위 / 봉길이) + 1. 실제와 단순 비교(보고용).
            expected = (hi - lo) // timeframe_to_ms(tf) + 1
            mark = "✓" if cnt >= expected else f"⚠ 예상 {expected}"
            click.echo(f"  {tf}: {cnt}봉  ({mark})")
        fcnt = session.execute(
            select(func.count()).select_from(FundingRate).where(
                FundingRate.symbol == sym)
        ).scalar_one()
        click.echo(f"  funding: {fcnt}개")
    icnt = session.execute(select(func.count()).select_from(Instrument)).scalar_one()
    click.echo(f"Instrument 캐시: {icnt}개 심볼")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `. .venv/bin/activate && pytest tests/test_cli.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quantpilot/cli.py tests/test_cli.py
git commit -m "feat: add CLI commands collect, collect-funding, status"
```

---

## Task 11: Live smoke 테스트 (수동)

**Files:**
- Create: `tests/test_live.py`

- [ ] **Step 1: live 테스트 작성**

Create `tests/test_live.py`:
```python
"""실제 OKX 연결 확인. 기본 실행에선 제외됨(pyproject addopts).
수동 실행: pytest -m live -v
"""
import pytest

from quantpilot.exchange.client import OKXClient


@pytest.mark.live
def test_okx_public_ohlcv_reachable():
    """진짜 OKX public 엔드포인트가 응답하고 정규화가 동작하는지."""
    c = OKXClient()  # 실제 ccxt.okx
    c.load_markets()
    rows = c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=0, limit=5)
    assert len(rows) > 0
    first = rows[0]
    assert set(first) == {"ts", "open", "high", "low", "close", "volume"}
    assert first["high"] >= first["low"]


@pytest.mark.live
def test_okx_funding_reachable():
    c = OKXClient()
    c.load_markets()
    rows = c.fetch_funding("BTC-USDT-SWAP", since_ms=0, limit=5)
    assert len(rows) > 0
    assert "funding_rate" in rows[0]
```

- [ ] **Step 2: 기본 실행에서 제외되는지 확인**

Run: `. .venv/bin/activate && pytest -v`
Expected: live 테스트는 `deselected`로 표시되고 나머지는 PASS.

- [ ] **Step 3: (선택, 인터넷 필요) live 수동 실행**

Run: `. .venv/bin/activate && pytest -m live -v`
Expected: 인터넷 연결 시 2 passed. (CI나 오프라인에선 건너뜀)

- [ ] **Step 4: Commit**

```bash
git add tests/test_live.py
git commit -m "test: add optional live OKX smoke tests"
```

---

## Task 12: README + 최종 검증 + 브랜치 push

**Files:**
- Create: `README.md`

- [ ] **Step 1: README.md 작성**

Create `README.md`:
```markdown
# QuantPilot — Week 1: 데이터 수집

OKX 시장 데이터(가격 캔들 + funding rate)를 로컬 SQLite에 적재하는 CLI.
Week 1은 public 데이터만 쓰므로 **API 키가 필요 없습니다**.

## 설치
\`\`\`bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
\`\`\`

## 사용
\`\`\`bash
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 365
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 15m --days 365
quantpilot collect-funding --symbol BTC-USDT-SWAP --days 365
quantpilot status
\`\`\`

수집은 idempotent 증분입니다 — 다시 실행하면 새 데이터만 이어붙고 중복은 무시됩니다.

## 테스트
\`\`\`bash
pytest             # 빠른 단위 테스트 (fixture 기반)
pytest -m live     # 실제 OKX 연결 확인 (인터넷 필요, 수동)
\`\`\`

## 설계
- Spec: \`docs/superpowers/specs/2026-06-07-week1-data-foundation-design.md\`
- Plan: \`docs/superpowers/plans/2026-06-07-week1-data-foundation.md\`
\`\`\`
```

- [ ] **Step 2: 전체 테스트 최종 실행**

Run: `. .venv/bin/activate && pytest -v`
Expected: 모든 단위 테스트 PASS, live는 deselected.

- [ ] **Step 3: ruff 린트**

Run: `. .venv/bin/activate && ruff check quantpilot/`
Expected: `All checks passed!` (경고 있으면 수정 후 재실행)

- [ ] **Step 4: 실제 수집 1회 동작 확인 (인터넷 필요, 선택)**

Run:
```bash
. .venv/bin/activate
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 7
quantpilot status
```
Expected: "신규 N개 적재" 출력, status에 1h 봉 개수 표시. (7일 1h ≈ 168봉)

- [ ] **Step 5: Commit + 브랜치 push**

```bash
git add README.md
git commit -m "docs: add README with setup and usage"
git push -u origin week1-data-foundation
```

---

## 완료 조건 매핑 (spec section 2 ↔ task)

| spec 완료 조건 | 구현 task |
|---|---|
| `collect ... 1h` 8,760봉 | Task 9, 10, 12 |
| `collect ... 15m` 35,040봉 | Task 9, 10, 12 |
| `collect-funding` 1,095개 | Task 9, 10 |
| 재실행 중복 없음 (idempotent 증분) | Task 8, 9 |
| `status` 요약 출력 | Task 10 |
| 미완성 캔들 저장 안 됨 | Task 7, 9 |
| 에러 처리 (일시적 재시도 / 사람실수 즉시중단) | Task 6 (retry), Task 4·10 (timeframe 거부) |
| fixture 단위 테스트 통과 | Task 2, 4, 5, 6, 7, 8, 9, 10 |
| 선택적 live smoke | Task 11 |

## Out of Scope 재확인 (Week 1 아님)
strategy/backtest/paper/risk 모듈, Trade/Position 테이블, API 키/주문, 5m/1m, gap 자동 재수집 — 전부 Week 2 이후.
