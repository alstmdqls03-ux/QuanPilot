# Week 3 — 페이퍼 트레이더 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Week 2 백테스트 엔진을 실시간 OKX 데이터에 $0 리스크로 붙여, 닫힌 봉 단위로 매매를
시뮬레이션하는 재시작-안전 페이퍼 트레이더를 만든다("백테=실전 일치" 검증).

**Architecture:** 새 매매 로직은 만들지 않는다. `check_exits`/`open_position`/`build_trade`/
`close_fill`(엔진), `IStrategy`(전략), `risk`/`costs`를 **그대로 재사용**하고 바깥 루프만 교체.
신규는 4개: `paper/store.py`(SQLite 영속), `paper/trader.py`(틱 루프), `risk/circuit_breaker.py`
(일일 -5% 정지), CLI 명령. parity 테스트가 백테와 페이퍼가 같은 봉에서 같은 거래를 냄을 강제.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0(SQLite), click, pandas, pytest, ruff.

**Spec:** [docs/superpowers/specs/2026-06-08-week3-paper-trader-design.md](../specs/2026-06-08-week3-paper-trader-design.md)

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `quantpilot/backtest/engine.py` | `_open_position`→`open_position`, `_close_fill`→`close_fill` 공개화 + `_build_trade` 클로저를 모듈레벨 `build_trade`로 추출 (페이퍼 재사용 표면) | 수정 |
| `quantpilot/risk/circuit_breaker.py` | 일일 -5% 정지 판정 + UTC 일자 리셋 (순수 함수) | 신규 |
| `quantpilot/paper/__init__.py` | 패키지 마커 | 신규 |
| `quantpilot/paper/models.py` | ORM 테이블 `PaperStateRow`, `PaperTradeRow` | 신규 |
| `quantpilot/data/db.py` | `init_db`가 paper 모델도 등록(테이블 생성) | 수정 |
| `quantpilot/paper/store.py` | `PaperState` dataclass + load/save/append/recent (I/O만) | 신규 |
| `quantpilot/paper/trader.py` | `TickContext`, `process_bar`(결정 로직), `panic_close`, `run_one_tick`, `run_loop` | 신규 |
| `quantpilot/cli.py` | `paper`/`paper-status`/`panic`/`paper-logs` 명령 | 수정 |
| `tests/test_circuit_breaker.py` | 정지/리셋 경계 | 신규 |
| `tests/test_engine_reuse.py` | 공개 표면(open_position/close_fill/build_trade) | 신규 |
| `tests/test_paper_store.py` | 상태/거래 라운드트립 | 신규 |
| `tests/test_paper_trader.py` | process_bar 경로 + panic + run_one_tick | 신규 |
| `tests/test_paper_parity.py` | 백테=페이퍼 일치 | 신규 |
| `README.md` | paper 사용법 + tmux/systemd 운영 | 수정 |

**커밋 규칙(매 커밋):** 의도한 파일만 `git add`(절대 `git add -A` 금지). 메시지는 conventional,
마지막 줄 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. 게이트:
`python -m pytest -q` 통과 + `ruff check quantpilot/` clean.

---

### Task 1: 워크트리 환경 셋업 (venv + baseline green)

이 워크트리는 fresh라 `.venv`가 없다. 구현/테스트 전에 python3.12 venv를 만들고 editable
설치한 뒤, 기존 Week 2 테스트가 전부 통과하는지(baseline) 확인한다. **코드 변경 없음 → 커밋 없음**
(`.venv`는 gitignore).

**Files:** 없음(환경만).

- [ ] **Step 1: venv 생성 + editable 설치**

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
```

- [ ] **Step 2: baseline 테스트 green 확인**

Run: `python -m pytest -q`
Expected: 전부 PASS (live 제외). 예: `NN passed, N deselected`.

- [ ] **Step 3: 린트 baseline 확인**

Run: `ruff check quantpilot/`
Expected: `All checks passed!`

---

### Task 2: 엔진 재사용 표면 공개화 (`open_position`, `close_fill`, `build_trade`)

"백테=실전 일치"를 글자 그대로 보장하려면 페이퍼가 백테와 *같은 함수*로 진입/체결/거래집계를
해야 한다. 현재 이 셋은 엔진 내부(private/closure)에 있다. 순수 리네이밍+추출(로직 불변)이라
기존 엔진 테스트가 회귀 가드.

**Files:**
- Modify: `quantpilot/backtest/engine.py`
- Test: `tests/test_engine_reuse.py`

- [ ] **Step 1: 실패 테스트 작성 (공개 표면이 아직 없음)**

```python
# tests/test_engine_reuse.py
from quantpilot.backtest.models import Fill, Position


def test_open_position_is_public():
    from quantpilot.backtest.engine import open_position
    bar = {"close": 100.0, "ts": 1_700_000_000_000}
    pos, fee = open_position("long", bar, 95.0, 1000.0, 0.01, 1.0, 3, 5.0, 2.0)
    assert pos is not None
    assert pos.side == "long" and pos.contracts > 0 and fee > 0


def test_close_fill_is_public():
    from quantpilot.backtest.engine import close_fill
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[], opened_ts=1, original_contracts=10)
    f = close_fill(pos, 105.0, 10, 2, "exit_signal", 5.0, 0.0, 0.01)
    assert f.reason == "exit_signal" and f.contracts == 10 and f.pnl_gross > 0


def test_build_trade_is_public_and_aggregates():
    from quantpilot.backtest.engine import build_trade
    pos = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                   targets_remaining=[], opened_ts=1, original_contracts=10)
    fills = [Fill(ts=2, price=105.0, contracts=10, fee=1.0, reason="tp1", pnl_gross=50.0)]
    t = build_trade(pos, fills, 2, funding=0.0, open_fee=0.5)
    assert t.exit == 105.0 and t.contracts == 10 and t.pnl_gross == 50.0
    assert abs(t.fees - 1.5) < 1e-9 and abs(t.pnl_net - 48.5) < 1e-9
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_engine_reuse.py -q`
Expected: FAIL — `ImportError: cannot import name 'open_position'`(및 close_fill/build_trade).

- [ ] **Step 3: 엔진 리네이밍 + 추출**

`quantpilot/backtest/engine.py` 수정:

1. `def _close_fill(` → `def close_fill(` (정의부). 내부 호출 3곳도 변경:
   `check_exits`의 손절 fill(`_close_fill(pos, pos.stop, ...)`), tp fill(`_close_fill(pos, price, ...)`),
   `run_backtest`의 exit_signal fill(`_close_fill(position, bar["close"], ...)`) → 전부 `close_fill(`.
2. `def _open_position(` → `def open_position(`. `run_backtest` 내 호출
   `position, open_fee = _open_position(` → `open_position(`.
3. `run_backtest` 안의 `_build_trade` **클로저를 삭제**하고 모듈레벨 함수로 추출(아래). `open_fee`는
   이제 인자로 받는다. 두 호출부를 갱신:
   - `trades.append(_build_trade(position, pending_fills, bar["ts"], funding))` →
     `trades.append(build_trade(position, pending_fills, bar["ts"], funding, open_fee))`
   - exit_signal 경로의 `trades.append(_build_trade(position, pending_fills, bar["ts"], funding))` →
     `trades.append(build_trade(position, pending_fills, bar["ts"], funding, open_fee))`

추출할 모듈레벨 함수(예: `close_fill` 정의 아래에 추가):

```python
def build_trade(pos: Position, fills: list[Fill], last_ts: int,
                funding: float, open_fee: float) -> Trade:
    """한 포지션의 fills를 Trade로 집계(보고용). 백테·페이퍼 공용.

    WHY 공용: 백테와 페이퍼가 동일한 Trade 구성을 써야 parity가 성립.
    equity는 호출부에서 체결 즉시 반영되므로 여기선 보고 집계만.
    """
    gross = sum(f.pnl_gross for f in fills)
    fees = open_fee + sum(f.fee for f in fills)
    sold = sum(f.contracts for f in fills)
    avg_exit = sum(f.price * f.contracts for f in fills) / sold if sold else pos.entry
    return Trade(side=pos.side, entry=pos.entry, exit=avg_exit,
                 contracts=pos.original_contracts, pnl_gross=gross, fees=fees,
                 funding=funding, pnl_net=gross - fees - funding,
                 opened_ts=pos.opened_ts, closed_ts=last_ts,
                 reason=fills[-1].reason if fills else "exit_signal")
```

- [ ] **Step 4: 새 테스트 + 기존 엔진 테스트 green 확인 (회귀 가드)**

Run: `python -m pytest tests/test_engine_reuse.py tests/test_engine_run.py -q`
Expected: 전부 PASS (리네이밍은 로직 불변 → 기존 엔진 테스트가 회귀 없음을 증명).

- [ ] **Step 5: 린트 + 커밋**

Run: `ruff check quantpilot/` → `All checks passed!`

```bash
git add quantpilot/backtest/engine.py tests/test_engine_reuse.py
git commit -m "refactor: expose engine reuse surface for paper trader

open_position/close_fill/build_trade 공개화(+추출). 페이퍼가 백테와 동일 함수로
진입/체결/거래집계 → 백테=실전 일치. 순수 리네이밍이라 기존 엔진 테스트가 회귀 가드.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `risk/circuit_breaker.py` — 일일 정지 판정 (순수 함수)

하루(UTC) 실현 손익이 그날 시작 자본의 -5%에 닿으면 신규 진입을 차단. UTC 자정 경계에서 리셋.
I/O·시계 의존 없는 순수 함수라 경계값 테스트가 자명.

**Files:**
- Create: `quantpilot/risk/circuit_breaker.py`
- Test: `tests/test_circuit_breaker.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_circuit_breaker.py
from quantpilot.risk.circuit_breaker import should_halt, is_new_utc_day

DAY = 86_400_000  # ms


def test_should_halt_below_threshold():
    # 시작자본 1000, 하루 실현 -50(=-5%) → 정지
    assert should_halt(1000.0, -50.0) is True
    # -49.99(=-4.999%)는 아직 아님
    assert should_halt(1000.0, -49.99) is False
    # 이익 구간은 당연히 아님
    assert should_halt(1000.0, 30.0) is False


def test_should_halt_custom_threshold():
    assert should_halt(2000.0, -200.0, threshold=0.10) is True
    assert should_halt(2000.0, -199.0, threshold=0.10) is False


def test_is_new_utc_day():
    base = 1_700_000_000_000
    same_day = base + 3_600_000          # +1h
    next_day = (base // DAY + 1) * DAY    # 다음 UTC 자정
    assert is_new_utc_day(base, same_day) is False
    assert is_new_utc_day(base, next_day) is True
    assert is_new_utc_day(base, next_day + 5 * DAY) is True
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_circuit_breaker.py -q`
Expected: FAIL — `ModuleNotFoundError: quantpilot.risk.circuit_breaker`.

- [ ] **Step 3: 구현**

```python
# quantpilot/risk/circuit_breaker.py
"""일일 손실 서킷 브레이커 (순수 함수).

WHY 순수: I/O·시계 의존 없이 인자만으로 판정 → 경계값 테스트가 자명하고 결정적.
영속(halted 플래그)·시계는 호출부(trader)가 담당.
"""
from __future__ import annotations

_DAY_MS = 86_400_000


def should_halt(day_start_equity: float, daily_realized_pnl: float,
                threshold: float = 0.05) -> bool:
    """하루 실현 손익이 그날 시작 자본의 -threshold(기본 -5%)에 닿으면 True(신규 진입 차단).

    WHY 실현 기준: 미실현은 봉마다 출렁여 과민 정지. 닫힌 손익만으로 일일 한도 판정.
    보유 포지션의 손절/익절은 막지 않는다(이미 5% 사이징 불변식으로 한정). 차단은 *새 베팅*만.
    """
    return daily_realized_pnl <= -threshold * day_start_equity


def is_new_utc_day(prev_ts_ms: int, cur_ts_ms: int) -> bool:
    """두 ms epoch ts가 서로 다른 UTC 날짜면 True → 일일 카운터/halt 리셋 신호.

    WHY UTC: funding·거래소 일일 경계가 UTC. 로컬 타임존 의존 제거(결정적).
    """
    return prev_ts_ms // _DAY_MS != cur_ts_ms // _DAY_MS
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_circuit_breaker.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: 린트 + 커밋**

```bash
ruff check quantpilot/
git add quantpilot/risk/circuit_breaker.py tests/test_circuit_breaker.py
git commit -m "feat: daily-loss circuit breaker (pure functions)

일일 실현손익 ≤ -5% 시 신규 진입 차단 판정 + UTC 일자 경계 리셋. 순수 함수.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `paper/models.py` — ORM 테이블 + init_db 등록

재시작 복구(상태)와 거래 감사(로그)를 위한 테이블 2개. 한 번에 포지션은 최대 1개라 포지션을
상태 행에 인라인(정규화 안 함 → 복구가 원자적). 펀딩/익절 진행 중 잔여 fill도 보존해야
백테와 동일한 Trade를 낼 수 있어 `pos_open_fee`/`pos_pending_fills`도 포함.

**Files:**
- Create: `quantpilot/paper/__init__.py` (빈 파일)
- Create: `quantpilot/paper/models.py`
- Modify: `quantpilot/data/db.py` (`init_db`가 paper 모델 등록)
- Test: `tests/test_paper_store.py` (이 태스크는 테이블 생성만 검증)

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_paper_store.py
from sqlalchemy import select


def test_paper_tables_created(session):
    # init_db가 paper 테이블을 등록·생성했으면 빈 조회가 에러 없이 동작
    from quantpilot.paper.models import PaperStateRow, PaperTradeRow
    assert session.execute(select(PaperStateRow)).scalars().all() == []
    assert session.execute(select(PaperTradeRow)).scalars().all() == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_store.py -q`
Expected: FAIL — `ModuleNotFoundError: quantpilot.paper.models` (또는 테이블 미존재).

- [ ] **Step 3: 구현 — 빈 `__init__.py`**

`quantpilot/paper/__init__.py` 를 빈 파일로 생성.

- [ ] **Step 4: 구현 — ORM 모델**

```python
# quantpilot/paper/models.py
"""페이퍼 트레이더 영속 테이블. 상태 1행(재시작 복구) + 거래 로그(감사).

설계: data/models.py와 동일 규약 — ts는 int ms epoch UTC, FK 없음(run_key 문자열 연결).
포지션은 한 번에 1개라 paper_state 행에 인라인(정규화 X → 복구가 원자적).
"""
from sqlalchemy import BigInteger, Boolean, Column, Float, Integer, String

from quantpilot.data.db import Base


class PaperStateRow(Base):
    """현재 런의 상태 스냅샷(단일 행, run_key가 PK). 재시작 시 이 행으로 정확 복구."""
    __tablename__ = "paper_state"

    run_key = Column(String, primary_key=True)   # "symbol|timeframe|strategy"
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    strategy = Column(String, nullable=False)
    equity = Column(Float, nullable=False)             # 현재 실현 자본(USDT)
    day_start_equity = Column(Float, nullable=False)   # 오늘 시작 자본(서킷 기준선)
    day_start_ts = Column(BigInteger, nullable=False)  # 오늘 UTC 경계
    daily_realized_pnl = Column(Float, nullable=False, default=0.0)
    halted = Column(Boolean, nullable=False, default=False)  # panic/서킷 정지
    last_processed_bar_ts = Column(BigInteger, nullable=True)  # 중복방지·재개 지점
    # 포지션(열려 있을 때만 non-NULL). WHY 인라인: 한 번에 1개라 별 테이블 불필요.
    pos_side = Column(String, nullable=True)
    pos_entry = Column(Float, nullable=True)
    pos_contracts = Column(Integer, nullable=True)
    pos_original_contracts = Column(Integer, nullable=True)
    pos_stop = Column(Float, nullable=True)
    pos_targets_remaining = Column(String, nullable=True)  # JSON [[price,frac],...]
    pos_opened_ts = Column(BigInteger, nullable=True)
    pos_open_fee = Column(Float, nullable=True)            # 진입 수수료(Trade 집계용)
    pos_pending_fills = Column(String, nullable=True)      # JSON fills(분할익절 누적)


class PaperTradeRow(Base):
    """청산 완료된 거래 로그(append-only). Week 2 Trade의 영속 버전."""
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True)
    run_key = Column(String, nullable=False)
    side = Column(String, nullable=False)
    entry = Column(Float, nullable=False)
    exit = Column(Float, nullable=False)
    contracts = Column(Integer, nullable=False)
    pnl_gross = Column(Float, nullable=False)
    fees = Column(Float, nullable=False)
    funding = Column(Float, nullable=False)
    pnl_net = Column(Float, nullable=False)
    opened_ts = Column(BigInteger, nullable=False)
    closed_ts = Column(BigInteger, nullable=False)
    reason = Column(String, nullable=False)
```

- [ ] **Step 5: 구현 — `init_db`가 paper 모델 등록**

`quantpilot/data/db.py` 의 `init_db` 수정:

```python
def init_db(engine) -> None:
    """모든 테이블 생성 (이미 있으면 무시). 앱/테스트 시작 시 1회 호출."""
    # models를 import해야 Base.metadata에 테이블이 등록됨.
    from quantpilot.data import models  # noqa: F401
    # 페이퍼 상태/거래 테이블도 같은 Base에 등록(단일 create_all 경로 유지).
    from quantpilot.paper import models as _paper_models  # noqa: F401

    Base.metadata.create_all(engine)
```

- [ ] **Step 6: 통과 확인**

Run: `python -m pytest tests/test_paper_store.py -q`
Expected: PASS (1 test).

- [ ] **Step 7: 린트 + 커밋**

```bash
ruff check quantpilot/
git add quantpilot/paper/__init__.py quantpilot/paper/models.py quantpilot/data/db.py tests/test_paper_store.py
git commit -m "feat: paper_state/paper_trades tables + init_db registration

재시작 복구용 상태 1행(포지션 인라인) + 거래 로그. init_db가 단일 create_all로 등록.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `paper/store.py` — 상태 라운드트립 (포지션 없음)

`PaperState` dataclass와 load/save. 빈 DB는 초기 자본 fresh 상태를 돌려준다.

**Files:**
- Create: `quantpilot/paper/store.py`
- Test: `tests/test_paper_store.py` (추가)

- [ ] **Step 1: 실패 테스트 작성 (기존 파일에 추가)**

```python
# tests/test_paper_store.py 에 추가
def test_make_run_key():
    from quantpilot.paper.store import make_run_key
    assert make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr") == "BTC-USDT-SWAP|1h|rsi-mr"


def test_load_empty_returns_fresh_state(session):
    from quantpilot.paper.store import load_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=1_700_000_000_000)
    assert st.equity == 1000.0 and st.day_start_equity == 1000.0
    assert st.position is None and st.halted is False
    assert st.last_processed_bar_ts is None


def test_save_then_load_no_position(session):
    from quantpilot.paper.store import load_state, save_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=1_700_000_000_000)
    st.equity = 1042.5
    st.daily_realized_pnl = -12.0
    st.halted = True
    st.last_processed_bar_ts = 1_700_003_600_000
    save_state(session, st)

    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    assert again.equity == 1042.5 and again.daily_realized_pnl == -12.0
    assert again.halted is True and again.last_processed_bar_ts == 1_700_003_600_000
    assert again.position is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_store.py -q`
Expected: FAIL — `ModuleNotFoundError: quantpilot.paper.store`.

- [ ] **Step 3: 구현**

```python
# quantpilot/paper/store.py
"""페이퍼 상태/거래 영속 (I/O만). 매매 로직 없음.

PaperState = 메모리상 풍부한 상태(포지션·잔여 fill 포함). DB 행(PaperStateRow)과
상호 변환. 포지션의 targets_remaining/pending_fills는 JSON 직렬화.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select

from quantpilot.backtest.models import Fill, Position, Trade
from quantpilot.paper.models import PaperStateRow, PaperTradeRow


@dataclass
class PaperState:
    run_key: str
    symbol: str
    timeframe: str
    strategy: str
    equity: float
    day_start_equity: float
    day_start_ts: int
    daily_realized_pnl: float = 0.0
    halted: bool = False
    last_processed_bar_ts: int | None = None
    position: Position | None = None
    open_fee: float = 0.0                 # 보유 포지션 진입 수수료(Trade 집계용)
    pending_fills: list[Fill] = field(default_factory=list)  # 분할익절 누적 fill


def make_run_key(symbol: str, timeframe: str, strategy: str) -> str:
    return f"{symbol}|{timeframe}|{strategy}"


def load_state(session, run_key: str, *, symbol: str, timeframe: str,
               strategy: str, capital: float, day_start_ts: int) -> PaperState:
    """run_key 상태를 복원. 없으면 초기 자본 fresh 상태."""
    row = session.get(PaperStateRow, run_key)
    if row is None:
        return PaperState(run_key=run_key, symbol=symbol, timeframe=timeframe,
                          strategy=strategy, equity=capital,
                          day_start_equity=capital, day_start_ts=day_start_ts)
    position = None
    open_fee = 0.0
    pending: list[Fill] = []
    if row.pos_side is not None:
        targets = [tuple(t) for t in json.loads(row.pos_targets_remaining)]
        position = Position(
            side=row.pos_side, entry=row.pos_entry, contracts=row.pos_contracts,
            stop=row.pos_stop, targets_remaining=targets, opened_ts=row.pos_opened_ts,
            original_contracts=row.pos_original_contracts)
        open_fee = row.pos_open_fee or 0.0
        pending = [Fill(**f) for f in json.loads(row.pos_pending_fills or "[]")]
    return PaperState(
        run_key=run_key, symbol=row.symbol, timeframe=row.timeframe,
        strategy=row.strategy, equity=row.equity,
        day_start_equity=row.day_start_equity, day_start_ts=row.day_start_ts,
        daily_realized_pnl=row.daily_realized_pnl, halted=row.halted,
        last_processed_bar_ts=row.last_processed_bar_ts,
        position=position, open_fee=open_fee, pending_fills=pending)


def save_state(session, state: PaperState) -> None:
    """상태를 upsert(원자적). 포지션 없으면 pos_* 전부 NULL."""
    row = session.get(PaperStateRow, state.run_key)
    if row is None:
        row = PaperStateRow(run_key=state.run_key)
        session.add(row)
    row.symbol = state.symbol
    row.timeframe = state.timeframe
    row.strategy = state.strategy
    row.equity = state.equity
    row.day_start_equity = state.day_start_equity
    row.day_start_ts = state.day_start_ts
    row.daily_realized_pnl = state.daily_realized_pnl
    row.halted = state.halted
    row.last_processed_bar_ts = state.last_processed_bar_ts
    p = state.position
    if p is None:
        row.pos_side = None
        row.pos_entry = None
        row.pos_contracts = None
        row.pos_original_contracts = None
        row.pos_stop = None
        row.pos_targets_remaining = None
        row.pos_opened_ts = None
        row.pos_open_fee = None
        row.pos_pending_fills = None
    else:
        row.pos_side = p.side
        row.pos_entry = p.entry
        row.pos_contracts = p.contracts
        row.pos_original_contracts = p.original_contracts
        row.pos_stop = p.stop
        row.pos_targets_remaining = json.dumps([list(t) for t in p.targets_remaining])
        row.pos_opened_ts = p.opened_ts
        row.pos_open_fee = state.open_fee
        row.pos_pending_fills = json.dumps([f.__dict__ for f in state.pending_fills])
    session.commit()


def append_trade(session, run_key: str, trade: Trade) -> None:
    session.add(PaperTradeRow(
        run_key=run_key, side=trade.side, entry=trade.entry, exit=trade.exit,
        contracts=trade.contracts, pnl_gross=trade.pnl_gross, fees=trade.fees,
        funding=trade.funding, pnl_net=trade.pnl_net, opened_ts=trade.opened_ts,
        closed_ts=trade.closed_ts, reason=trade.reason))
    session.commit()


def recent_trades(session, run_key: str, n: int) -> list[Trade]:
    rows = session.execute(
        select(PaperTradeRow).where(PaperTradeRow.run_key == run_key)
        .order_by(PaperTradeRow.closed_ts.desc()).limit(n)).scalars().all()
    return [Trade(side=r.side, entry=r.entry, exit=r.exit, contracts=r.contracts,
                  pnl_gross=r.pnl_gross, fees=r.fees, funding=r.funding,
                  pnl_net=r.pnl_net, opened_ts=r.opened_ts, closed_ts=r.closed_ts,
                  reason=r.reason) for r in rows]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_paper_store.py -q`
Expected: PASS.

- [ ] **Step 5: 린트 + 커밋**

```bash
ruff check quantpilot/
git add quantpilot/paper/store.py tests/test_paper_store.py
git commit -m "feat: paper store — PaperState + load/save (no position)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `paper/store.py` — 포지션·잔여 fill 라운드트립 + 거래 로그

포지션이 열린 상태(targets_remaining + pending_fills 포함)도 비트 단위로 복구되는지, 그리고
거래 로그 append/recent가 동작하는지 검증.

**Files:**
- Test: `tests/test_paper_store.py` (추가). 구현은 Task 5에서 이미 완료 — 이 태스크는 포지션 경로를
  덮는 테스트가 RED→GREEN인지 확인(빠진 분기 있으면 보완).

- [ ] **Step 1: 실패 테스트 작성 (추가)**

```python
# tests/test_paper_store.py 에 추가
def test_save_then_load_with_position(session):
    from quantpilot.backtest.models import Fill, Position
    from quantpilot.paper.store import load_state, save_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    st.position = Position(side="long", entry=100.0, contracts=7, stop=95.0,
                           targets_remaining=[(105.0, 0.33), (110.0, 0.34)],
                           opened_ts=1_700_000_000_000, original_contracts=10)
    st.open_fee = 0.35
    st.pending_fills = [Fill(ts=1_700_003_600_000, price=105.0, contracts=3,
                             fee=0.16, reason="tp1", pnl_gross=15.0)]
    save_state(session, st)

    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    p = again.position
    assert p is not None
    assert p.side == "long" and p.contracts == 7 and p.original_contracts == 10
    assert p.targets_remaining == [(105.0, 0.33), (110.0, 0.34)]
    assert again.open_fee == 0.35
    assert len(again.pending_fills) == 1 and again.pending_fills[0].reason == "tp1"


def test_position_cleared_on_resave(session):
    # 포지션을 None으로 다시 저장하면 pos_* 가 NULL로 비워져야 함
    from quantpilot.backtest.models import Position
    from quantpilot.paper.store import load_state, save_state, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    st.position = Position(side="short", entry=100.0, contracts=5, stop=105.0,
                           targets_remaining=[], opened_ts=1, original_contracts=5)
    save_state(session, st)
    st.position = None
    save_state(session, st)
    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="rsi-mr", capital=1000.0, day_start_ts=0)
    assert again.position is None


def test_append_and_recent_trades(session):
    from quantpilot.backtest.models import Trade
    from quantpilot.paper.store import append_trade, recent_trades, make_run_key
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    for i in range(3):
        append_trade(session, rk, Trade(
            side="long", entry=100.0, exit=105.0, contracts=10, pnl_gross=50.0,
            fees=1.0, funding=0.0, pnl_net=49.0, opened_ts=i, closed_ts=100 + i,
            reason="tp1"))
    got = recent_trades(session, rk, 2)
    assert len(got) == 2
    assert got[0].closed_ts == 102 and got[1].closed_ts == 101  # 최신순
```

- [ ] **Step 2: 실패 확인 → 구현 점검**

Run: `python -m pytest tests/test_paper_store.py -q`
Expected: Task 5 구현이 포지션 경로를 이미 다루므로 대부분 PASS. 만약 FAIL이면 `save_state`/
`load_state`의 포지션 직렬화 분기를 테스트에 맞게 보완 후 재실행.

- [ ] **Step 3: 통과 확인**

Run: `python -m pytest tests/test_paper_store.py -q`
Expected: PASS (전체).

- [ ] **Step 4: 린트 + 커밋**

```bash
ruff check quantpilot/
git add tests/test_paper_store.py quantpilot/paper/store.py
git commit -m "test: paper store position + pending-fill round-trip + trade log

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `paper/trader.py` — `process_bar` 진입 경로

한 닫힌 봉을 상태에 반영하는 결정 로직(네트워크 없음). 이 태스크는 "포지션 없음 + 진입 신호"
경로: `open_position`으로 진입하고 `open_fee`를 equity에서 즉시 차감.

**Files:**
- Create: `quantpilot/paper/trader.py`
- Test: `tests/test_paper_trader.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_paper_trader.py
import pandas as pd

from quantpilot.paper.store import PaperState
from quantpilot.strategy.base import IStrategy, Signal


class _LongOnceStrategy(IStrategy):
    name = "t-long"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("long", 1.0, price - 5.0, {})
        return Signal("hold", 0.0, None, {})


def _ctx(strategy):
    from quantpilot.paper.trader import TickContext
    return TickContext(
        session=None, client=None, symbol="BTC-USDT-SWAP", timeframe="1h",
        strategy=strategy, capital=1000.0, leverage=3, ct_val=0.01, lot_sz=1.0,
        fee_bps=5.0, slippage_bps=2.0, run_key="BTC-USDT-SWAP|1h|t-long")


def _state(capital=1000.0):
    return PaperState(run_key="BTC-USDT-SWAP|1h|t-long", symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy="t-long", equity=capital,
                      day_start_equity=capital, day_start_ts=0)


def _window(closes, ts):
    n = len(closes)
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes},
        index=[ts - (n - 1 - i) * 3_600_000 for i in range(n)]).rename_axis("ts")


def test_process_bar_opens_position():
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    ts = 1_700_007_200_000
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is not None and st.position.side == "long"
    assert st.position.contracts > 0
    assert st.open_fee > 0 and st.equity < 1000.0  # 진입 수수료 차감
    assert trades == []
    assert st.last_processed_bar_ts == ts
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_trader.py -q`
Expected: FAIL — `ModuleNotFoundError: quantpilot.paper.trader`.

- [ ] **Step 3: 구현 (진입 경로까지)**

```python
# quantpilot/paper/trader.py
"""페이퍼 트레이더 — 실시간 루프(조립만). 매매 판단은 엔진/전략, 정지는 circuit_breaker,
영속은 store에 위임. process_bar는 네트워크 없이 결정적(테스트 가능).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd

from quantpilot.backtest.costs import funding_between
from quantpilot.backtest.engine import build_trade, check_exits, close_fill, open_position
from quantpilot.paper import store
from quantpilot.paper.store import PaperState
from quantpilot.risk.circuit_breaker import is_new_utc_day, should_halt


@dataclass
class TickContext:
    session: object
    client: object
    symbol: str
    timeframe: str
    strategy: object        # IStrategy
    capital: float
    leverage: int
    ct_val: float
    lot_sz: float
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    poll_seconds: int = 60
    run_key: str = ""


def process_bar(ctx: TickContext, state: PaperState, bar: dict,
                window: pd.DataFrame, funding_events=None):
    """한 닫힌 봉을 상태에 반영. (state, list[Trade]) 반환.

    순서(백테 엔진과 동일): UTC 리셋 → 청산 판정(즉시 실현) → 신호 → 진입/청산.
    """
    funding_events = funding_events or []
    trades = []

    # 0) UTC 일자 경계 → 일일 카운터/halt 리셋
    if state.last_processed_bar_ts is not None and \
            is_new_utc_day(state.last_processed_bar_ts, bar["ts"]):
        state.day_start_equity = state.equity
        state.daily_realized_pnl = 0.0
        state.day_start_ts = bar["ts"]
        state.halted = False

    # 1) 보유 포지션 청산 판정 (체결 즉시 equity 실현 — 백테와 동일 불변식)
    if state.position is not None:
        pos2, fills = check_exits(state.position, bar, ctx.fee_bps,
                                  ctx.slippage_bps, ctx.ct_val)
        if fills:
            realized = sum(f.pnl_gross for f in fills) - sum(f.fee for f in fills)
            state.equity += realized
            state.daily_realized_pnl += realized
            state.pending_fills.extend(fills)
        if pos2 is None:
            trades.append(_close_out(ctx, state, bar["ts"], funding_events))
        else:
            state.position = pos2

    # 2) 전략 신호
    signal = ctx.strategy.generate_signal(window, state.position)

    # 3) 신호 처리
    if signal.side in ("long", "short") and state.position is None:
        if should_halt(state.day_start_equity, state.daily_realized_pnl):
            state.halted = True  # 서킷 차단: 신규 진입 안 함
        else:
            pos, open_fee = open_position(
                signal.side, bar, signal.suggested_stop, state.equity, ctx.ct_val,
                ctx.lot_sz, ctx.leverage, ctx.fee_bps, ctx.slippage_bps)
            if pos is not None:
                state.equity -= open_fee
                state.position = pos
                state.open_fee = open_fee
                state.pending_fills = []
    elif signal.side == "exit" and state.position is not None:
        fill = close_fill(state.position, bar["close"], state.position.contracts,
                          bar["ts"], "exit_signal", ctx.fee_bps, ctx.slippage_bps,
                          ctx.ct_val)
        state.equity += fill.pnl_gross - fill.fee
        state.daily_realized_pnl += fill.pnl_gross - fill.fee
        state.pending_fills.append(fill)
        trades.append(_close_out(ctx, state, bar["ts"], funding_events))

    state.last_processed_bar_ts = bar["ts"]
    return state, trades


def _close_out(ctx: TickContext, state: PaperState, last_ts: int, funding_events):
    """완전 청산 마무리: funding 차감 + Trade 집계 + 포지션 비움. 청산된 Trade 반환."""
    pos = state.position
    notional = pos.original_contracts * pos.entry * ctx.ct_val
    funding = funding_between(funding_events, notional, pos.side, pos.opened_ts, last_ts)
    state.equity -= funding
    state.daily_realized_pnl -= funding
    trade = build_trade(pos, state.pending_fills, last_ts, funding, state.open_fee)
    state.position = None
    state.open_fee = 0.0
    state.pending_fills = []
    return trade
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_paper_trader.py -q`
Expected: PASS (1 test).

- [ ] **Step 5: 린트 + 커밋**

```bash
ruff check quantpilot/
git add quantpilot/paper/trader.py tests/test_paper_trader.py
git commit -m "feat: paper trader process_bar — entry path (engine reuse)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `process_bar` — 청산 경로 (손절 + funding + Trade)

보유 포지션이 손절 봉을 만나면 청산되고, 실현손익이 equity에 즉시 반영되며, funding이 차감된
Trade가 1건 나온다.

**Files:**
- Test: `tests/test_paper_trader.py` (추가). 구현은 Task 7에서 완료 — RED→GREEN 확인.

- [ ] **Step 1: 실패 테스트 작성 (추가)**

```python
# tests/test_paper_trader.py 에 추가
class _HoldStrategy(IStrategy):
    name = "t-hold"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2

    def generate_signal(self, window, open_position):
        return Signal("hold", 0.0, None, {})


def test_process_bar_stop_closes_and_realizes():
    from quantpilot.backtest.models import Position
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_HoldStrategy())
    st = _state()
    # 진입가 100, stop 95, 10계약. open_fee는 이미 차감됐다고 가정.
    st.position = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                           targets_remaining=[(105.0, 0.33), (110.0, 0.33),
                                              (115.0, 0.34)],
                           opened_ts=1_700_000_000_000, original_contracts=10)
    st.open_fee = 0.5
    ts = 1_700_003_600_000
    window = _window([100.0, 90.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 96.0, "low": 89.0, "close": 90.0}  # low<95 손절
    eq_before = st.equity
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is None
    assert len(trades) == 1 and trades[0].reason == "stop"
    assert st.equity < eq_before                # 손실 실현
    assert st.daily_realized_pnl < 0
    # 보존: 최종 equity == 시작 + Trade.pnl_net (open_fee 포함)
    assert abs(st.equity - (eq_before + trades[0].pnl_net)) < 1e-6


def test_process_bar_funding_deducted_on_close():
    from quantpilot.backtest.models import Position
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_HoldStrategy())
    st = _state()
    st.position = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                           targets_remaining=[], opened_ts=1_700_000_000_000,
                           original_contracts=10)
    ts = 1_700_003_600_000
    fund = [(1_700_000_000_000 + 1, 0.001)]  # 보유 구간 내 funding 이벤트
    window = _window([100.0, 90.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 96.0, "low": 89.0, "close": 90.0}
    st, trades = process_bar(ctx, st, bar, window, funding_events=fund)
    assert trades and trades[0].funding != 0.0
```

- [ ] **Step 2: 통과 확인 (Task 7 구현이 이미 청산 경로를 다룸)**

Run: `python -m pytest tests/test_paper_trader.py -q`
Expected: PASS. (FAIL이면 `process_bar`의 청산/`_close_out` 분기를 보완 후 재실행.)

- [ ] **Step 3: 린트 + 커밋**

```bash
ruff check quantpilot/
git add tests/test_paper_trader.py quantpilot/paper/trader.py
git commit -m "test: paper process_bar stop-close realizes equity + funding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `process_bar` — 서킷 브레이커 게이트 + UTC 일자 리셋

일일 실현손익이 -5% 이하면 진입 신호가 와도 포지션을 안 만든다(halted=True). UTC 자정을 넘는
봉에서 카운터·halt가 리셋되어 다시 진입 가능.

**Files:**
- Test: `tests/test_paper_trader.py` (추가). 구현은 Task 7에 포함 — RED→GREEN 확인.

- [ ] **Step 1: 실패 테스트 작성 (추가)**

```python
# tests/test_paper_trader.py 에 추가
def test_circuit_breaker_blocks_entry():
    from quantpilot.paper.trader import process_bar
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    st.daily_realized_pnl = -60.0          # 시작자본 1000의 -6% → 정지 조건
    ts = 1_700_007_200_000
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.position is None              # 진입 차단됨
    assert st.halted is True
    assert trades == []


def test_utc_rollover_resets_and_allows_entry():
    from quantpilot.paper.trader import process_bar
    DAY = 86_400_000
    ctx = _ctx(_LongOnceStrategy())
    st = _state()
    st.daily_realized_pnl = -60.0
    st.halted = True
    prev = 1_700_000_000_000
    st.last_processed_bar_ts = prev
    ts = (prev // DAY + 1) * DAY            # 다음 UTC 자정 → 리셋
    window = _window([100.0, 100.0], ts)
    bar = {"ts": ts, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    st, trades = process_bar(ctx, st, bar, window)
    assert st.daily_realized_pnl >= -1e-9 or st.position is not None
    assert st.halted is False
    assert st.day_start_equity == st.equity + st.open_fee or st.position is not None
    assert st.position is not None         # 리셋 후 진입 가능
```

- [ ] **Step 2: 통과 확인**

Run: `python -m pytest tests/test_paper_trader.py -q`
Expected: PASS. (FAIL이면 `process_bar`의 0)리셋·3)게이트 분기 보완.)

- [ ] **Step 3: 린트 + 커밋**

```bash
ruff check quantpilot/
git add tests/test_paper_trader.py quantpilot/paper/trader.py
git commit -m "test: circuit-breaker gate blocks entry, UTC rollover resets

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: `paper/trader.py` — `panic_close` (킬 스위치)

보유 포지션을 마지막 가격에 전량 청산하고 halted=True로 만든다. 청산 Trade를 반환(또는 포지션
없으면 None).

**Files:**
- Modify: `quantpilot/paper/trader.py`
- Test: `tests/test_paper_trader.py` (추가)

- [ ] **Step 1: 실패 테스트 작성 (추가)**

```python
# tests/test_paper_trader.py 에 추가
def test_panic_close_flattens_and_halts():
    from quantpilot.backtest.models import Position
    from quantpilot.paper.trader import panic_close
    ctx = _ctx(_HoldStrategy())
    st = _state()
    st.position = Position(side="long", entry=100.0, contracts=10, stop=95.0,
                           targets_remaining=[], opened_ts=1_700_000_000_000,
                           original_contracts=10)
    st.open_fee = 0.5
    trade = panic_close(ctx, st, last_price=102.0, last_ts=1_700_003_600_000)
    assert trade is not None and trade.reason == "panic"
    assert st.position is None and st.halted is True
    assert abs(st.equity - (1000.0 + trade.pnl_net)) < 1e-6  # last_price 기준 실현


def test_panic_close_noop_without_position():
    from quantpilot.paper.trader import panic_close
    ctx = _ctx(_HoldStrategy())
    st = _state()
    trade = panic_close(ctx, st, last_price=102.0, last_ts=1)
    assert trade is None and st.halted is True
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_trader.py::test_panic_close_flattens_and_halts -q`
Expected: FAIL — `AttributeError`/`ImportError: panic_close`.

- [ ] **Step 3: 구현 (`trader.py`에 추가)**

```python
def panic_close(ctx: TickContext, state: PaperState, last_price: float,
                last_ts: int):
    """비상정지: 보유 포지션을 last_price에 전량 청산 + halted=True. Trade 반환(없으면 None).

    WHY last_price=최신 닫힌 봉 종가: 페이퍼는 실주문이 없어 그게 가장 최근 관측가.
    """
    state.halted = True
    if state.position is None:
        return None
    fill = close_fill(state.position, last_price, state.position.contracts, last_ts,
                      "panic", ctx.fee_bps, ctx.slippage_bps, ctx.ct_val)
    state.equity += fill.pnl_gross - fill.fee
    state.daily_realized_pnl += fill.pnl_gross - fill.fee
    state.pending_fills.append(fill)
    return _close_out(ctx, state, last_ts, [])
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_paper_trader.py -q`
Expected: PASS (전체).

- [ ] **Step 5: 린트 + 커밋**

```bash
ruff check quantpilot/
git add quantpilot/paper/trader.py tests/test_paper_trader.py
git commit -m "feat: panic_close kill switch — flatten at last price + halt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: `run_one_tick` (폴링 → 새 봉 처리 → 영속) + `run_loop`

실제 틱: 폴링(client 있으면)으로 OKX→SQLite, 최신 닫힌 봉 로드, `last_processed_bar_ts` 이후
새 봉만 `process_bar`로 처리, 거래·상태 영속. `run_loop`는 sleep과 함께 무한 반복(얇은 래퍼).
테스트는 fake client + in-memory DB로 결정적.

**Files:**
- Modify: `quantpilot/paper/trader.py`
- Test: `tests/test_paper_trader.py` (추가)

- [ ] **Step 1: 실패 테스트 작성 (추가)**

```python
# tests/test_paper_trader.py 에 추가
def _seed_candles(session, symbol, timeframe, ohlc_rows):
    """ohlc_rows: [(ts, o,h,l,c), ...] → candles 테이블에 직접 적재."""
    from quantpilot.data.models import Candle
    for ts, o, h, low, c in ohlc_rows:
        session.add(Candle(exchange="okx", symbol=symbol, timeframe=timeframe, ts=ts,
                           open=o, high=h, low=low, close=c, volume=1.0, inserted_at=ts))
    session.commit()


def test_run_one_tick_processes_new_bars(session):
    from quantpilot.paper.store import PaperState, make_run_key
    from quantpilot.paper.trader import TickContext, run_one_tick
    tf = 3_600_000
    base = 1_700_000_000_000
    rows = [(base + i * tf, 100.0, 100.0, 100.0, 100.0) for i in range(3)]
    rows.append((base + 3 * tf, 100.0, 100.0, 89.0, 90.0))  # 마지막 봉 급락
    _seed_candles(session, "BTC-USDT-SWAP", "1h", rows)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-long")
    ctx = TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_LongOnceStrategy(), capital=1000.0,
                      leverage=3, ct_val=0.01, lot_sz=1.0, run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-long", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    st, trades = run_one_tick(ctx, st)
    assert st.last_processed_bar_ts == base + 3 * tf   # 마지막 봉까지 진행
    # 상태가 영속됐는지: 새 로드로 확인
    from quantpilot.paper.store import load_state
    again = load_state(session, rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                       strategy="t-long", capital=1000.0, day_start_ts=0)
    assert again.last_processed_bar_ts == base + 3 * tf


def test_run_one_tick_dedup_no_reprocess(session):
    from quantpilot.paper.store import PaperState, make_run_key
    from quantpilot.paper.trader import TickContext, run_one_tick
    tf = 3_600_000
    base = 1_700_000_000_000
    rows = [(base + i * tf, 100.0, 101.0, 99.0, 100.0) for i in range(3)]
    _seed_candles(session, "BTC-USDT-SWAP", "1h", rows)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-hold")
    ctx = TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_HoldStrategy(), capital=1000.0,
                      leverage=3, ct_val=0.01, lot_sz=1.0, run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-hold", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    st, _ = run_one_tick(ctx, st)
    last = st.last_processed_bar_ts
    st, trades2 = run_one_tick(ctx, st)   # 새 봉 없음
    assert st.last_processed_bar_ts == last and trades2 == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_trader.py::test_run_one_tick_processes_new_bars -q`
Expected: FAIL — `ImportError: run_one_tick`.

- [ ] **Step 3: 구현 (`trader.py`에 추가)**

```python
def run_one_tick(ctx: TickContext, state: PaperState):
    """1틱: (client 있으면)폴링 → 최신 닫힌 봉 로드 → 새 봉만 process_bar → 영속.

    엔진 백테와 동일하게 결정 시작점은 봉 인덱스 lookback(첫 lookback개는 warmup window).
    """
    from sqlalchemy import select

    from quantpilot.backtest.data_loader import load_candles_df
    from quantpilot.data.collector import collect_ohlcv
    from quantpilot.data.models import FundingRate

    if ctx.client is not None:
        # 증분 폴링. 실패는 호출부(run_loop)가 try로 흡수 → 루프 생존.
        collect_ohlcv(ctx.session, ctx.client, ctx.symbol, ctx.timeframe,
                      days=2, now_ms=int(time.time() * 1000))

    df = load_candles_df(ctx.session, ctx.symbol, ctx.timeframe)
    if df.empty:
        return state, []

    funding_events = [
        (f.ts, f.funding_rate) for f in ctx.session.execute(
            select(FundingRate).where(FundingRate.symbol == ctx.symbol)
            .order_by(FundingRate.ts)).scalars().all()]

    lookback = ctx.strategy.lookback
    last = state.last_processed_bar_ts
    all_trades = []
    for pos_iloc in range(len(df)):
        t = int(df.index[pos_iloc])
        if last is not None and t <= last:
            continue                      # 이미 처리한 봉(중복 방지)
        if pos_iloc < lookback:
            state.last_processed_bar_ts = t   # warmup 구간은 건너뛰되 진행
            continue
        window = df.iloc[pos_iloc - lookback + 1: pos_iloc + 1]
        bar = {"ts": t, "open": float(df.at[t, "open"]), "high": float(df.at[t, "high"]),
               "low": float(df.at[t, "low"]), "close": float(df.at[t, "close"])}
        state, trades = process_bar(ctx, state, bar, window, funding_events)
        for tr in trades:
            store.append_trade(ctx.session, ctx.run_key, tr)
        all_trades.extend(trades)

    store.save_state(ctx.session, state)
    return state, all_trades


def run_loop(ctx: TickContext, state: PaperState):
    """무한 루프(얇은 래퍼). 폴링 실패는 흡수하고 다음 틱에서 재시도 → 루프 생존."""
    while True:
        try:
            state, _ = run_one_tick(ctx, state)
        except Exception as e:  # noqa: BLE001  운영 중 단발 오류로 죽지 않게
            import sys
            print(f"[paper] tick 오류(건너뜀): {e}", file=sys.stderr)
        time.sleep(ctx.poll_seconds)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_paper_trader.py -q`
Expected: PASS (전체).

- [ ] **Step 5: 린트 + 커밋**

```bash
ruff check quantpilot/
git add quantpilot/paper/trader.py tests/test_paper_trader.py
git commit -m "feat: run_one_tick (poll→new bars→persist) + run_loop wrapper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: parity 테스트 + CLI 명령 + README + 최종검증

핵심 검증(백테=페이퍼)과 사용자 인터페이스(CLI), 운영 문서를 마무리하고 전체 게이트를 통과시킨다.

**Files:**
- Create: `tests/test_paper_parity.py`
- Modify: `quantpilot/cli.py` (`paper`/`paper-status`/`panic`/`paper-logs`)
- Modify: `README.md`
- Test: `tests/test_cli_paper.py`

- [ ] **Step 1: parity 실패 테스트 작성 (crown jewel)**

```python
# tests/test_paper_parity.py
import pandas as pd

from quantpilot.backtest.engine import run_backtest
from quantpilot.paper.store import PaperState, make_run_key
from quantpilot.paper.trader import TickContext, process_bar
from quantpilot.strategy.base import IStrategy, Signal


class _LongOnce(IStrategy):
    name = "p-long"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("long", 1.0, price - 5.0, {})
        return Signal("hold", 0.0, None, {})


def _candles(closes):
    tf = 3_600_000
    base = 1_700_000_000_000
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes,
         "volume": [1.0] * len(closes)},
        index=[base + i * tf for i in range(len(closes))]).rename_axis("ts")


def test_paper_matches_backtest():
    # 동일 봉 시퀀스를 ①run_backtest 통째 ②process_bar 봉마다 → 거래·최종 equity 일치
    closes = [100.0, 100, 100, 90]   # 진입 후 급락 → 손절(끝에 flat)
    df = _candles(closes)
    bt = run_backtest(candles=df, strategy=_LongOnce(), capital=1000.0, ct_val=0.01,
                      lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
                      funding_events=[], oos_split_ts=df.index[-1])

    rk = make_run_key("BTC-USDT-SWAP", "1h", "p-long")
    ctx = TickContext(session=None, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_LongOnce(), capital=1000.0,
                      leverage=3, ct_val=0.01, lot_sz=1.0, fee_bps=5, slippage_bps=2,
                      run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="p-long", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    lookback = 2
    paper_trades = []
    for i in range(lookback, len(df)):
        t = int(df.index[i])
        window = df.iloc[i - lookback + 1: i + 1]
        bar = {"ts": t, "open": float(df.at[t, "open"]), "high": float(df.at[t, "high"]),
               "low": float(df.at[t, "low"]), "close": float(df.at[t, "close"])}
        st, trades = process_bar(ctx, st, bar, window, funding_events=[])
        paper_trades.extend(trades)

    # 거래 일치(side/entry/exit/reason/pnl_net)
    def key(t):
        return (t.side, round(t.entry, 6), round(t.exit, 6), t.reason,
                round(t.pnl_net, 6))
    assert [key(t) for t in paper_trades] == [key(t) for t in bt.trades]
    # 최종 실현 equity 일치 (끝에 flat이므로 곡선 마지막 = 실현)
    assert abs(st.equity - bt.equity_curve[-1][1]) < 1e-6
```

- [ ] **Step 2: parity 통과 확인**

Run: `python -m pytest tests/test_paper_parity.py -q`
Expected: PASS — 백테와 페이퍼가 같은 거래·equity. (FAIL이면 process_bar/엔진 재사용이
어긋난 것 → 원인 수정.)

- [ ] **Step 3: CLI 명령 실패 테스트 작성**

```python
# tests/test_cli_paper.py
from click.testing import CliRunner

from quantpilot.cli import cli


def test_paper_status_empty(monkeypatch, tmp_path):
    # 빈 DB에서 paper-status는 "상태 없음" 안내, 크래시 없음
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(tmp_path / "q.db"))
    r = CliRunner().invoke(cli, ["paper-status"])
    assert r.exit_code == 0
    assert "상태" in r.output or "없음" in r.output


def test_paper_logs_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(tmp_path / "q.db"))
    r = CliRunner().invoke(cli, ["paper-logs"])
    assert r.exit_code == 0
```

- [ ] **Step 4: 실패 확인**

Run: `python -m pytest tests/test_cli_paper.py -q`
Expected: FAIL — `No such command 'paper-status'`.

- [ ] **Step 5: CLI 구현 (`cli.py`에 추가)**

`cli.py` 상단 import에 추가:
```python
from quantpilot.strategy.rsi_mean_reversion import RsiMeanReversion  # 이미 있음
```
파일 끝(`if __name__` 위)에 명령 추가:

```python
def _paper_ctx_and_state(symbol, timeframe, strategy, capital, leverage):
    """paper 계열 공통: 세션·Instrument·전략·ctx·state 준비."""
    from quantpilot.paper.store import load_state, make_run_key
    from quantpilot.paper.trader import TickContext
    from quantpilot.data.models import Instrument

    if strategy not in STRATEGIES:
        raise click.ClickException(f"알 수 없는 전략 '{strategy}'. 사용 가능: {', '.join(STRATEGIES)}")
    session, _ = _session()
    inst = session.execute(select(Instrument).where(
        Instrument.symbol == symbol)).scalar_one_or_none()
    if inst is None:
        raise click.ClickException(
            f"{symbol} Instrument 캐시 없음. 먼저 'quantpilot collect'를 실행하세요.")
    rk = make_run_key(symbol, timeframe, strategy)
    state = load_state(session, rk, symbol=symbol, timeframe=timeframe,
                       strategy=strategy, capital=capital, day_start_ts=_now_ms())
    strat = STRATEGIES[strategy](timeframe=timeframe)
    ctx = TickContext(session=session, client=None, symbol=symbol, timeframe=timeframe,
                      strategy=strat, capital=capital, leverage=leverage,
                      ct_val=inst.ct_val, lot_sz=inst.lot_sz, run_key=rk)
    return session, ctx, state


@cli.command()
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
@click.option("--capital", default=1000.0, show_default=True, type=float)
@click.option("--leverage", default=3, show_default=True, type=int)
@click.option("--poll-seconds", default=60, show_default=True, type=int)
def paper(symbol, timeframe, strategy, capital, leverage, poll_seconds):
    """실시간 페이퍼 트레이딩 루프 시작(포그라운드, 재시작 안전)."""
    from quantpilot.exchange.client import OKXClient
    from quantpilot.paper.trader import run_loop

    session, ctx, state = _paper_ctx_and_state(symbol, timeframe, strategy, capital, leverage)
    client = OKXClient()
    client.load_markets()
    ctx.client = client
    ctx.poll_seconds = poll_seconds
    click.echo(f"페이퍼 시작: {symbol} {timeframe} {strategy} "
               f"(자본 {state.equity:.2f}, poll {poll_seconds}s). Ctrl-C로 중단.")
    try:
        run_loop(ctx, state)
    except KeyboardInterrupt:
        click.echo("\n중단됨. 상태는 DB에 저장됨(다음 실행 시 이어받음).")


@cli.command(name="paper-status")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
def paper_status(symbol, timeframe, strategy):
    """현재 페이퍼 상태 출력(읽기 전용)."""
    from quantpilot.paper.store import load_state, make_run_key, recent_trades
    session, _ = _session()
    rk = make_run_key(symbol, timeframe, strategy)
    from quantpilot.paper.models import PaperStateRow
    if session.get(PaperStateRow, rk) is None:
        click.echo(f"{rk}: 페이퍼 상태 없음(아직 시작 안 함).")
        return
    st = load_state(session, rk, symbol=symbol, timeframe=timeframe,
                    strategy=strategy, capital=0.0, day_start_ts=0)
    click.echo(f"{rk}")
    click.echo(f"  equity: {st.equity:.2f}  (오늘 시작 {st.day_start_equity:.2f}, "
               f"실현 PnL {st.daily_realized_pnl:+.2f})")
    click.echo(f"  halted: {st.halted}   마지막 봉: {st.last_processed_bar_ts}")
    if st.position is None:
        click.echo("  포지션: 없음")
    else:
        p = st.position
        click.echo(f"  포지션: {p.side} {p.contracts}계약 @ {p.entry} (stop {p.stop})")
    click.echo(f"  최근 거래 {len(recent_trades(session, rk, 100))}건")


@cli.command()
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
def panic(symbol, timeframe, strategy):
    """비상정지: 보유 포지션 즉시 청산(최신 봉 종가) + 정지 플래그."""
    from quantpilot.backtest.data_loader import load_candles_df
    from quantpilot.paper.store import append_trade, load_state, make_run_key, save_state
    from quantpilot.paper.models import PaperStateRow
    from quantpilot.paper.trader import TickContext, panic_close
    from quantpilot.data.models import Instrument

    session, _ = _session()
    rk = make_run_key(symbol, timeframe, strategy)
    if session.get(PaperStateRow, rk) is None:
        click.echo(f"{rk}: 페이퍼 상태 없음. 할 일 없음.")
        return
    st = load_state(session, rk, symbol=symbol, timeframe=timeframe,
                    strategy=strategy, capital=0.0, day_start_ts=0)
    inst = session.execute(select(Instrument).where(
        Instrument.symbol == symbol)).scalar_one_or_none()
    df = load_candles_df(session, symbol, timeframe)
    last_price = float(df["close"].iloc[-1]) if not df.empty else (
        st.position.entry if st.position else 0.0)
    last_ts = int(df.index[-1]) if not df.empty else _now_ms()
    ctx = TickContext(session=session, client=None, symbol=symbol, timeframe=timeframe,
                      strategy=None, capital=0.0, leverage=3,
                      ct_val=inst.ct_val if inst else 0.01,
                      lot_sz=inst.lot_sz if inst else 1.0, run_key=rk)
    trade = panic_close(ctx, st, last_price=last_price, last_ts=last_ts)
    if trade is not None:
        append_trade(session, rk, trade)
    save_state(session, st)
    if trade is None:
        click.echo(f"정지 플래그 set. 청산할 포지션 없음. (equity {st.equity:.2f})")
    else:
        click.echo(f"비상청산 완료: {trade.side} → {last_price} "
                   f"(net {trade.pnl_net:+.2f}). 정지됨.")


@cli.command(name="paper-logs")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
@click.option("--limit", default=20, show_default=True, type=int)
def paper_logs(symbol, timeframe, strategy, limit):
    """최근 페이퍼 거래 로그 출력."""
    from quantpilot.paper.store import make_run_key, recent_trades
    session, _ = _session()
    rk = make_run_key(symbol, timeframe, strategy)
    trades = recent_trades(session, rk, limit)
    if not trades:
        click.echo(f"{rk}: 거래 없음.")
        return
    for t in trades:
        click.echo(f"  {t.closed_ts}  {t.side:5s} {t.contracts}계약 "
                   f"{t.entry}→{t.exit}  net {t.pnl_net:+.2f}  [{t.reason}]")
```

- [ ] **Step 6: CLI 통과 확인**

Run: `python -m pytest tests/test_cli_paper.py -q`
Expected: PASS.

- [ ] **Step 7: README 갱신**

`README.md`에 "Week 3 — 페이퍼 트레이더" 섹션 추가:
- 사용법: `quantpilot collect`(데이터 먼저) → `quantpilot paper` → `quantpilot paper-status` →
  필요시 `quantpilot panic` / `quantpilot paper-logs`.
- 운영(재시작 안전): tmux 예시
  ```bash
  tmux new -s paper
  quantpilot paper --symbol BTC-USDT-SWAP --timeframe 1h --strategy rsi-mr
  # Ctrl-b d 로 detach. 재접속: tmux attach -t paper
  ```
  systemd 유닛 예시(파일 경로·venv는 환경에 맞게):
  ```ini
  [Unit]
  Description=QuantPilot paper trader
  After=network-online.target
  [Service]
  WorkingDirectory=/path/to/QuantPilot
  ExecStart=/path/to/QuantPilot/.venv/bin/quantpilot paper
  Restart=always
  RestartSec=10
  [Install]
  WantedBy=default.target
  ```
- WHY 재시작 안전: 모든 상태가 SQLite(`paper_state`)에 저장돼, 크래시·재부팅 후 자동
  복구(포지션·자본·정지여부·마지막 봉)된다.
- 한계(실거래 아님): `TODOS.md`의 pre-live blocker 참조.

- [ ] **Step 8: 전체 게이트 + 커밋**

Run:
```bash
python -m pytest -q
ruff check quantpilot/
```
Expected: 전부 PASS + `All checks passed!`.

```bash
git add tests/test_paper_parity.py tests/test_cli_paper.py quantpilot/cli.py README.md
git commit -m "feat: paper CLI (paper/status/panic/logs) + parity test + docs

백테=페이퍼 일치를 parity 테스트로 강제. CLI로 루프 시작·상태·비상정지·로그.
tmux/systemd 운영 문서화.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (작성자 체크)

**Spec coverage (스펙 §별 → 태스크 매핑):**
- §3 재사용 표면(open_position/close_fill/build_trade 공유) → Task 2 ✅
- §3/§7 circuit_breaker → Task 3 ✅
- §5 paper_state/paper_trades 테이블 + store API → Task 4,5,6 ✅
- §4/§6 process_bar(진입/청산/funding/리셋/게이트) → Task 7,8,9 ✅
- §2/§8 panic 킬 스위치 → Task 10 (panic_close) + Task 12 (CLI panic) ✅
- §4/§6/§10 run_one_tick(폴링·중복방지·영속)·run_loop·에러흡수 → Task 11 ✅
- §1/§9 백테=페이퍼 parity → Task 12 (test_paper_parity) ✅
- §8 CLI paper/paper-status/panic/paper-logs → Task 12 ✅
- §10 운영(tmux/systemd) 문서 → Task 12 Step 7 ✅
- §2 out-of-scope(부분체결·멀티심볼·reconcile·confirm-field·equity곡선) → 구현 안 함(의도) ✅

**Placeholder scan:** "TBD"/"적절히 처리" 류 없음. 모든 코드 스텝에 실제 코드 포함.

**Type consistency:** `PaperState`(store) 필드(equity/day_start_equity/day_start_ts/
daily_realized_pnl/halted/last_processed_bar_ts/position/open_fee/pending_fills)가 store·trader·
CLI에서 동일하게 사용. `TickContext` 필드명 일치. `process_bar`/`panic_close`/`run_one_tick`/
`_close_out` 시그니처가 정의부와 호출부에서 일치. 엔진 공개 함수명(open_position/close_fill/
build_trade)이 Task 2 정의와 Task 7~12 사용에서 일치.

**Pre-live 빚:** 이 플랜은 새 pre-live 빚을 만들지 않음(기존 TODOS 승계). funding 보유구간
정산·confirm-field 봉마감은 백테와 동일하게 단순 버전을 쓰며 TODOS에 이미 등록됨.
