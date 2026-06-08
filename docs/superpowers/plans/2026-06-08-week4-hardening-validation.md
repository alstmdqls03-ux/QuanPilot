# Week 4 — 하드닝 + 측정 + 7일 런 셋업 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 페이퍼 트레이더를 7일 무인 가동에 안전하게(킬스위치가 도는 루프를 멈춤, 파일 로깅)
만들고, 결과를 Week 2와 동일한 지표로 측정 가능하게(equity 곡선 + `paper-report`) 한 뒤 런 셋업.

**Architecture:** 새 매매 로직 없음. Week 2 `metrics`/`report`와 Week 3 `process_bar`/`persist_tick`을
재사용. `paper_equity` 테이블 1개 추가(봉마다 실현+미실현 equity 기록), `run_loop`이 매 틱 DB의
`halted`를 재확인해 외부 panic을 감지·정지, `paper-report`가 `compute_metrics`로 백테와 동일 지표 출력.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0(SQLite), click, pandas, logging(RotatingFileHandler), pytest, ruff.

**Spec:** [docs/superpowers/specs/2026-06-08-week4-hardening-validation-design.md](../specs/2026-06-08-week4-hardening-validation-design.md)

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `quantpilot/paper/models.py` | `PaperEquityRow` 테이블 추가(UNIQUE run_key,ts) | 수정 |
| `quantpilot/paper/store.py` | `persist_tick`에 `equity_points` 인자 + `load_equity_curve` + `read_halted` | 수정 |
| `quantpilot/paper/trader.py` | `run_one_tick` 봉마다 equity 기록; `run_loop` 외부 panic 감지+정지+로깅 | 수정 |
| `quantpilot/paper/logsetup.py` | `setup_paper_logger`(회전 파일 + 콘솔) | 신규 |
| `quantpilot/cli.py` | `paper-report` 명령 추가 | 수정 |
| `scripts/run-paper.sh` | 수집→`quantpilot paper` 런처 | 신규 |
| `README.md` | "7일 페이퍼런" 운영 절차 | 수정 |
| `tests/test_paper_equity.py` | equity 기록·곡선·report 지표 | 신규 |
| `tests/test_paper_killswitch.py` | read_halted 외부 변경 감지 | 신규 |
| `tests/test_cli_paper.py` | paper-report CLI | 수정(추가) |

**커밋 규칙:** 의도한 파일만 `git add`(절대 `git add -A` 금지). conventional 메시지, 마지막 줄
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. 게이트: `python -m pytest -q` + `ruff check quantpilot/`.

---

### Task 1: 워크트리 환경 셋업 (venv + baseline green)

이 워크트리는 fresh라 `.venv`가 없다. python3.12 venv 생성 + editable 설치 후 기존 테스트가 전부
통과하는지 확인한다. **코드 변경 없음 → 커밋 없음**(`.venv`는 gitignore).

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
Expected: 전부 PASS (예: `120 passed, 2 deselected`).

- [ ] **Step 3: 린트 baseline 확인**

Run: `ruff check quantpilot/`
Expected: `All checks passed!`

---

### Task 2: `PaperEquityRow` 테이블 (봉별 equity 곡선)

7일 런 성과를 백테와 같은 지표로 측정하려면 equity 시계열이 필요하다. 테이블 1개 추가
(`테이블 최소화` 원칙). `UNIQUE(run_key, ts)`로 재시작 재처리 시 중복 적재 방지(Week 1 캔들 패턴).

**Files:**
- Modify: `quantpilot/paper/models.py`
- Test: `tests/test_paper_equity.py`

`init_db`는 이미 `quantpilot.paper.models`를 import하므로 신규 테이블이 자동 등록된다(수정 불필요).

- [ ] **Step 1: 실패 테스트 작성** — create `tests/test_paper_equity.py`:
```python
from sqlalchemy import select


def test_paper_equity_table_created(session):
    from quantpilot.paper.models import PaperEquityRow
    assert session.execute(select(PaperEquityRow)).scalars().all() == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_equity.py -q`
Expected: FAIL — `ImportError: cannot import name 'PaperEquityRow'`.

- [ ] **Step 3: 구현** — `quantpilot/paper/models.py`에 추가(파일 끝, 기존 import에 `UniqueConstraint` 추가):

먼저 상단 import 줄을 다음으로 교체:
```python
from sqlalchemy import BigInteger, Boolean, Column, Float, Integer, String, UniqueConstraint
```
그리고 파일 끝에 클래스 추가:
```python
class PaperEquityRow(Base):
    """봉별 equity 포인트(실현+미실현). paper-report가 Sharpe/MaxDD 계산에 사용.

    WHY UNIQUE(run_key, ts): 틱 재처리(재시작/오류 복구) 시 같은 봉 equity가 중복 적재되면
    곡선이 왜곡된다. (run_key, ts) 유니크 + on_conflict_do_nothing으로 idempotent(Week 1 캔들 패턴).
    """
    __tablename__ = "paper_equity"

    id = Column(Integer, primary_key=True)
    run_key = Column(String, nullable=False)
    ts = Column(BigInteger, nullable=False)        # 봉 ts (ms epoch UTC)
    equity = Column(Float, nullable=False)         # 실현 + 미실현(그 봉 종가 기준)

    __table_args__ = (UniqueConstraint("run_key", "ts"),)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_paper_equity.py -q`
Expected: PASS (1 test).

- [ ] **Step 5: 린트 + 커밋**
```bash
ruff check quantpilot/
git add quantpilot/paper/models.py tests/test_paper_equity.py
git commit -m "feat: paper_equity table for equity-curve recording

봉별 실현+미실현 equity. UNIQUE(run_key,ts)로 재처리 중복 방지. paper-report 입력.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: store — equity 영속(`persist_tick` 확장) + `load_equity_curve` + `read_halted`

equity 포인트를 거래·상태와 **같은 트랜잭션**으로 기록(Week 3 원자성 유지). 곡선 조회 + 외부
panic 감지를 위한 `halted` 신선 조회 추가.

**Files:**
- Modify: `quantpilot/paper/store.py`
- Test: `tests/test_paper_equity.py` (추가), `tests/test_paper_killswitch.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_paper_equity.py`에 추가:
```python
def test_persist_tick_records_equity_and_load_curve(session):
    from quantpilot.paper.store import (
        PaperState, load_equity_curve, make_run_key, persist_tick)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    persist_tick(session, rk, st, [], equity_points=[(100, 1000.0), (200, 1005.0)])
    curve = load_equity_curve(session, rk)
    assert curve == [(100, 1000.0), (200, 1005.0)]


def test_persist_tick_equity_dedup_on_reprocess(session):
    # 같은 ts를 다시 기록해도 중복되지 않음(재시작 재처리 idempotency)
    from quantpilot.paper.store import (
        PaperState, load_equity_curve, make_run_key, persist_tick)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    persist_tick(session, rk, st, [], equity_points=[(100, 1000.0)])
    persist_tick(session, rk, st, [], equity_points=[(100, 1000.0), (200, 1005.0)])
    assert load_equity_curve(session, rk) == [(100, 1000.0), (200, 1005.0)]
```

`tests/test_paper_killswitch.py` (신규):
```python
from quantpilot.data.db import init_db, make_engine, make_session_factory
from quantpilot.paper.store import (
    PaperState, make_run_key, read_halted, save_state)


def _file_sessions(tmp_path):
    # 두 세션이 같은 파일 DB를 공유(별 프로세스 흉내). :memory:는 연결 간 공유 안 됨.
    engine = make_engine(f"sqlite:///{tmp_path / 'qp.db'}")
    init_db(engine)
    SL = make_session_factory(engine)
    return SL(), SL()


def test_read_halted_sees_external_commit(tmp_path):
    s1, s2 = _file_sessions(tmp_path)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    save_state(s1, st)                       # s1: halted=False 저장
    assert read_halted(s1, rk) is False
    # s2(별 프로세스 흉내)가 halted=True로 갱신
    st.halted = True
    save_state(s2, st)
    # s1은 캐시를 들고 있지만 read_halted가 expire로 외부 변경을 봐야 함
    assert read_halted(s1, rk) is True


def test_read_halted_missing_row_is_false(session):
    assert read_halted(session, make_run_key("X", "1h", "rsi-mr")) is False
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_equity.py tests/test_paper_killswitch.py -q`
Expected: FAIL — `load_equity_curve`/`read_halted`/`equity_points` 미존재.

- [ ] **Step 3: 구현** — `quantpilot/paper/store.py` 수정:

1. 상단 import에 sqlite insert 추가:
```python
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
```
그리고 `PaperEquityRow`를 paper.models import에 추가:
```python
from quantpilot.paper.models import PaperEquityRow, PaperStateRow, PaperTradeRow
```

2. `persist_tick` 시그니처에 `equity_points` 추가하고 equity insert 루프 삽입(거래 add 뒤,
   `_apply_state_to_row` 앞):
```python
def persist_tick(session, run_key: str, state: "PaperState", trades: "list[Trade]",
                 equity_points: "list[tuple[int, float]]" = ()) -> None:
    """한 틱의 청산 거래 + equity 포인트 + 상태를 단일 트랜잭션으로 영속(원자적).

    WHY 원자성: 거래·equity·진행위치(last_processed_bar_ts)를 같은 commit에 묶어야,
    틱 도중 강제 종료돼도 '일부만 적재된' 불일치가 안 생긴다. 재시작 시 같은 봉을 재처리해도
    equity는 UNIQUE(run_key,ts) on_conflict로 중복 안 됨.
    """
    for tr in trades:
        session.add(PaperTradeRow(
            run_key=run_key, side=tr.side, entry=tr.entry, exit=tr.exit,
            contracts=tr.contracts, pnl_gross=tr.pnl_gross, fees=tr.fees,
            funding=tr.funding, pnl_net=tr.pnl_net, opened_ts=tr.opened_ts,
            closed_ts=tr.closed_ts, reason=tr.reason))
    for ts, eq in equity_points:
        stmt = sqlite_insert(PaperEquityRow).values(
            run_key=run_key, ts=ts, equity=eq).on_conflict_do_nothing(
            index_elements=["run_key", "ts"])
        session.execute(stmt)
    _apply_state_to_row(session, state)
    session.commit()
```

3. 파일에 함수 2개 추가(예: `recent_trades` 아래):
```python
def load_equity_curve(session, run_key: str) -> list[tuple[int, float]]:
    """run_key의 equity 곡선을 ts 오름차순 [(ts, equity), ...]로. paper-report 입력."""
    rows = session.execute(
        select(PaperEquityRow).where(PaperEquityRow.run_key == run_key)
        .order_by(PaperEquityRow.ts)).scalars().all()
    return [(r.ts, r.equity) for r in rows]


def read_halted(session, run_key: str) -> bool:
    """DB의 halted를 신선하게 읽음(외부 프로세스 panic 반영). 행 없으면 False.

    WHY expire_all: 도는 루프의 세션은 상태 행을 캐시하고 있어, 별도 프로세스(panic)가
    커밋한 halted=True를 그냥 session.get으로는 못 본다. 캐시를 무효화해야 DB의 외부 변경을 본다.
    """
    session.expire_all()
    row = session.get(PaperStateRow, run_key)
    return bool(row.halted) if row is not None else False
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_paper_equity.py tests/test_paper_killswitch.py -q`
Expected: PASS (전체).

- [ ] **Step 5: 린트 + 커밋**
```bash
ruff check quantpilot/
git add quantpilot/paper/store.py tests/test_paper_equity.py tests/test_paper_killswitch.py
git commit -m "feat: store equity persistence (atomic) + load_equity_curve + read_halted

persist_tick이 equity 포인트도 단일 commit에 기록(중복 dedup). read_halted는 expire로
외부 panic 커밋을 봄(킬스위치 토대).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: trader — `run_one_tick`이 봉마다 equity 기록

처리하는 결정 봉마다 equity(실현+미실현)를 모아 `persist_tick`에 넘긴다. 미실현은 엔진의 `_pnl`을
재사용(백테 equity 곡선과 동일 의미).

**Files:**
- Modify: `quantpilot/paper/trader.py`
- Test: `tests/test_paper_equity.py` (추가)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_paper_equity.py`에 추가:
```python
def test_run_one_tick_records_equity_per_bar(session):
    from quantpilot.data.models import Candle
    from quantpilot.paper.store import PaperState, load_equity_curve, make_run_key
    from quantpilot.paper.trader import TickContext, run_one_tick
    from quantpilot.strategy.base import IStrategy, Signal

    class _Hold(IStrategy):
        name = "t-hold"
        def __init__(self):
            self.timeframe = "1h"; self.lookback = 2
        def generate_signal(self, window, open_position):
            return Signal("hold", 0.0, None, {})

    tf = 3_600_000
    base = 1_700_000_000_000
    for i in range(4):
        c = 100.0 + i
        session.add(Candle(exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
                           ts=base + i * tf, open=c, high=c, low=c, close=c,
                           volume=1.0, inserted_at=base + i * tf))
    session.commit()
    rk = make_run_key("BTC-USDT-SWAP", "1h", "t-hold")
    ctx = TickContext(session=session, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_Hold(), capital=1000.0, leverage=3,
                      ct_val=0.01, lot_sz=1.0, run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="t-hold", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    st, trades = run_one_tick(ctx, st)
    curve = load_equity_curve(session, rk)
    # 결정 봉 = iloc 2,3 (lookback=2) → 2 포인트. 포지션 없으니 equity=1000 flat.
    assert len(curve) == 2
    assert curve[0] == (base + 2 * tf, 1000.0)
    assert curve[1] == (base + 3 * tf, 1000.0)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_equity.py::test_run_one_tick_records_equity_per_bar -q`
Expected: FAIL — equity 곡선이 비어 있음(아직 기록 안 함).

- [ ] **Step 3: 구현** — `quantpilot/paper/trader.py` `run_one_tick` 수정:

상단 import에 `_pnl` 추가(기존 engine import 줄에):
```python
from quantpilot.backtest.engine import _pnl, build_trade, check_exits, close_fill, open_position
```
루프를 equity 기록하도록 수정(기존 `all_trades = []` ~ `persist_tick` 구간):
```python
    lookback = ctx.strategy.lookback
    last = state.last_processed_bar_ts
    all_trades = []
    equity_points: list[tuple[int, float]] = []
    for pos_iloc in range(len(df)):
        t = int(df.index[pos_iloc])
        if last is not None and t <= last:
            continue                      # 이미 처리한 봉(중복 방지)
        if pos_iloc < lookback:
            state.last_processed_bar_ts = t   # warmup: 진행만(곡선 기록 X)
            continue
        window = df.iloc[pos_iloc - lookback + 1: pos_iloc + 1]
        bar = {"ts": t, "open": float(df.at[t, "open"]), "high": float(df.at[t, "high"]),
               "low": float(df.at[t, "low"]), "close": float(df.at[t, "close"])}
        state, trades = process_bar(ctx, state, bar, window, funding_events)
        all_trades.extend(trades)
        # equity 포인트 = 실현 + 미실현(그 봉 종가 기준). 백테 equity_curve와 동일 의미.
        # WHY 미실현 포함: 보유 중 drawdown이 곡선에 반영돼야 MaxDD/Sharpe가 백테와 같은 잣대.
        unreal = (_pnl(state.position.side, state.position.entry, bar["close"],
                       state.position.contracts, ctx.ct_val)
                  if state.position is not None else 0.0)
        equity_points.append((t, state.equity + unreal))

    store.persist_tick(ctx.session, ctx.run_key, state, all_trades, equity_points)
    return state, all_trades
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_paper_equity.py -q`
Expected: PASS. 또 회귀 확인: `python -m pytest tests/test_paper_trader.py tests/test_paper_parity.py -q` → 전부 PASS(equity 기록은 거래 로직 불변).

- [ ] **Step 5: 린트 + 커밋**
```bash
ruff check quantpilot/
git add quantpilot/paper/trader.py tests/test_paper_equity.py
git commit -m "feat: run_one_tick records per-bar equity (realized + unrealized)

봉마다 equity 포인트를 persist_tick에 함께 적재(원자적). 미실현은 엔진 _pnl 재사용 →
백테 equity_curve와 동일 의미. paper-report가 이 곡선으로 Sharpe/MaxDD 계산.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `logsetup.py` + `run_loop` 외부 panic 킬스위치 + 로깅

7일 무인 런 안전 핵심: 별도 `panic` 프로세스가 세운 정지를 도는 루프가 매 틱 감지해 정지.
+ 회전 파일 로그(사후 리뷰).

**Files:**
- Create: `quantpilot/paper/logsetup.py`
- Modify: `quantpilot/paper/trader.py` (`run_loop`)
- Test: `tests/test_paper_killswitch.py` (추가)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_paper_killswitch.py`에 추가:
```python
def test_setup_paper_logger_writes_to_file(tmp_path):
    from quantpilot.paper.logsetup import setup_paper_logger
    log_dir = tmp_path / "logs"
    logger = setup_paper_logger("BTC-USDT-SWAP|1h|rsi-mr", log_dir=str(log_dir))
    logger.info("hello-qa-line")
    for h in logger.handlers:
        h.flush()
    files = list(log_dir.glob("paper-*.log"))
    assert files, "로그 파일이 생성돼야 함"
    assert "hello-qa-line" in files[0].read_text()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_paper_killswitch.py::test_setup_paper_logger_writes_to_file -q`
Expected: FAIL — `ModuleNotFoundError: quantpilot.paper.logsetup`.

- [ ] **Step 3: 구현 — `quantpilot/paper/logsetup.py`**:
```python
"""페이퍼 런 로깅 설정. 7일 무인 가동은 사후 리뷰할 로그가 필수.

회전 파일(logs/paper-{run_key}.log) + 콘솔(tmux에 라이브 표시). logs/는 gitignore.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_paper_logger(run_key: str, log_dir: str = "logs",
                       max_bytes: int = 2_000_000, backups: int = 5) -> logging.Logger:
    """run_key별 로거 반환(회전 파일 + 콘솔). 재호출 시 핸들러 중복 추가 안 함."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", run_key)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"quantpilot.paper.{safe}")
    logger.setLevel(logging.INFO)
    if logger.handlers:   # 이미 구성됨(재호출/재시작) → 중복 핸들러 방지
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = RotatingFileHandler(str(Path(log_dir) / f"paper-{safe}.log"),
                             maxBytes=max_bytes, backupCount=backups)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False
    return logger
```

- [ ] **Step 4: `run_loop` 수정** — `quantpilot/paper/trader.py`. 상단 import에 추가:
```python
from quantpilot.paper.logsetup import setup_paper_logger
```
`run_loop` 전체를 다음으로 교체:
```python
def run_loop(ctx: TickContext, state: PaperState):
    """무한 루프. (1) 매 틱 외부 panic(DB halted) 감지 시 정지, (2) 폴링 실패 흡수+상태 재로드,
    (3) 회전 파일 로그.

    WHY 외부 halt 체크: panic은 별도 프로세스로 SQLite만 갱신한다. 도는 루프는 in-memory
    state를 들고 있어 그 변경을 자동으로 못 본다 → 매 틱 DB halted를 재확인해야 킬스위치가
    *도는 루프*를 실제로 멈춘다(Week 3 /review 발견).
    WHY 오류 흡수+재로드: 네트워크 순단 등으로 한 틱이 실패하면 in-memory state가 더럽혀졌을 수
    있음(미커밋). rollback + load_state로 마지막 커밋 상태로 되돌려 다음 틱이 깨끗하게 재처리.
    """
    log = setup_paper_logger(ctx.run_key)
    log.info("페이퍼 루프 시작: %s equity=%.2f poll=%ds", ctx.run_key, state.equity,
             ctx.poll_seconds)
    while True:
        # (1) 외부 panic 킬스위치: DB는 halted인데 in-memory는 아직 아님 → panic 발생
        if store.read_halted(ctx.session, ctx.run_key) and not state.halted:
            log.warning("외부 panic 감지 — 상태 재로드 후 정지")
            state = store.load_state(ctx.session, ctx.run_key, symbol=ctx.symbol,
                                     timeframe=ctx.timeframe, strategy=state.strategy,
                                     capital=state.equity, day_start_ts=state.day_start_ts)
            break
        try:
            state, trades = run_one_tick(ctx, state)
            for tr in trades:
                log.info("청산: %s %dct %.2f->%.2f net %+.2f [%s]", tr.side, tr.contracts,
                         tr.entry, tr.exit, tr.pnl_net, tr.reason)
        except Exception as e:  # noqa: BLE001  운영 중 단발 오류로 죽지 않게
            log.warning("tick 오류(건너뜀, 상태 재로드): %s", e)
            try:
                ctx.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            state = store.load_state(ctx.session, ctx.run_key, symbol=ctx.symbol,
                                     timeframe=ctx.timeframe, strategy=state.strategy,
                                     capital=state.day_start_equity,
                                     day_start_ts=state.day_start_ts)
        time.sleep(ctx.poll_seconds)
    log.info("페이퍼 루프 정지.")
```
(기존 `import sys`가 더 이상 안 쓰이면 제거. ruff가 미사용으로 잡으면 삭제.)

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_paper_killswitch.py -q`
Expected: PASS. 회귀: `python -m pytest -q` → 전부 PASS.

- [ ] **Step 6: 린트 + 커밋**
```bash
ruff check quantpilot/
git add quantpilot/paper/logsetup.py quantpilot/paper/trader.py tests/test_paper_killswitch.py
git commit -m "feat: kill-switch on running loop (external panic) + file logging

run_loop이 매 틱 DB halted를 재확인해 별도 panic 프로세스의 정지를 감지·정지(도는 루프도
멈춤). 회전 파일 로그로 7일 무인 런 사후 리뷰 가능.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `paper-report` CLI (백테와 동일 지표)

equity 곡선 + 거래 로그로 Sharpe/MaxDD/총수익/승률/PF 출력. **Week 2 `compute_metrics`를 그대로
재사용** → 페이퍼 성과를 백테와 같은 잣대로 본다.

**Files:**
- Modify: `quantpilot/cli.py`
- Test: `tests/test_cli_paper.py` (추가)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_cli_paper.py`에 추가:
```python
def test_paper_report_empty(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from quantpilot.cli import cli
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(tmp_path / "q.db"))
    r = CliRunner().invoke(cli, ["paper-report"])
    assert r.exit_code == 0
    assert "곡선" in r.output or "런" in r.output


def test_paper_report_with_curve(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from quantpilot.cli import cli
    from quantpilot.config import Settings
    from quantpilot.data.db import init_db, make_engine, make_session_factory
    from quantpilot.paper.store import PaperState, make_run_key, persist_tick
    db = str(tmp_path / "q.db")
    monkeypatch.setenv("QUANTPILOT_DB_PATH", db)
    engine = make_engine(Settings().db_url)
    init_db(engine)
    s = make_session_factory(engine)()
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", equity=1010.0, day_start_equity=1000.0,
                    day_start_ts=0)
    persist_tick(s, rk, st, [], equity_points=[(100, 1000.0), (200, 1010.0)])
    s.close()
    r = CliRunner().invoke(cli, ["paper-report"])
    assert r.exit_code == 0
    assert "sharpe" in r.output.lower() and "max_drawdown" in r.output.lower()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_cli_paper.py::test_paper_report_empty -q`
Expected: FAIL — `No such command 'paper-report'`.

- [ ] **Step 3: 구현** — `quantpilot/cli.py` 끝(`if __name__` 위)에 추가:
```python
@cli.command(name="paper-report")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
def paper_report(symbol, timeframe, strategy):
    """페이퍼 런 성과 지표(백테와 동일 지표) 출력."""
    from quantpilot.backtest.metrics import compute_metrics, periods_per_year
    from quantpilot.paper.store import load_equity_curve, make_run_key, recent_trades

    session, _ = _session()
    rk = make_run_key(symbol, timeframe, strategy)
    curve = load_equity_curve(session, rk)
    if len(curve) < 2:
        click.echo(f"{rk}: equity 곡선 부족(아직 런 안 했거나 결정 봉 < 2). "
                   f"'quantpilot paper'로 런을 시작하세요.")
        return
    trades = recent_trades(session, rk, 1_000_000)
    m = compute_metrics(curve, trades, periods_per_year(timeframe))
    click.echo(f"{rk}  ({len(curve)}봉, {curve[0][0]}~{curve[-1][0]})")
    click.echo(f"  total_return: {m['total_return']}")
    click.echo(f"  sharpe:       {m['sharpe']}")
    click.echo(f"  max_drawdown: {m['max_drawdown']}")
    click.echo(f"  n_trades:     {m['n_trades']}  win_rate {m['win_rate']}  "
               f"profit_factor {m['profit_factor']}")
    click.echo(f"  equity(곡선 마지막): {curve[-1][1]:.2f}")
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_cli_paper.py -q`
Expected: PASS (전체).

- [ ] **Step 5: 린트 + 커밋**
```bash
ruff check quantpilot/
git add quantpilot/cli.py tests/test_cli_paper.py
git commit -m "feat: paper-report CLI — Sharpe/MaxDD/win-rate via Week 2 metrics

페이퍼 equity 곡선 + 거래로 백테와 동일 지표 출력(compute_metrics 재사용). 측정 레벨까지
백테=페이퍼 일치.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `scripts/run-paper.sh` + README + 최종검증

7일 런 런처 스크립트 + 운영 문서 + 전체 게이트.

**Files:**
- Create: `scripts/run-paper.sh`
- Modify: `README.md`
- (gitignore에 `logs/` 추가)

- [ ] **Step 1: 런처 스크립트** — `scripts/run-paper.sh` 생성:
```bash
#!/usr/bin/env bash
# 7일 페이퍼런 런처: 데이터 시드 후 페이퍼 루프 시작.
# 사용: tmux new -s paper → ./scripts/run-paper.sh → Ctrl-b d (detach)
set -euo pipefail

SYMBOL="${SYMBOL:-BTC-USDT-SWAP}"
TIMEFRAME="${TIMEFRAME:-1h}"
STRATEGY="${STRATEGY:-rsi-mr}"
POLL="${POLL:-60}"

# venv 활성화(워크트리/루트 어디서 실행하든)
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi

echo "[run-paper] 데이터 시드: $SYMBOL $TIMEFRAME"
quantpilot collect --symbol "$SYMBOL" --timeframe "$TIMEFRAME" --days 30
quantpilot collect-funding --symbol "$SYMBOL" --days 30

echo "[run-paper] 페이퍼 루프 시작 (poll ${POLL}s). 중단: 이 창에서 Ctrl-C, 비상정지: 다른 셸에서 'quantpilot panic'."
exec quantpilot paper --symbol "$SYMBOL" --timeframe "$TIMEFRAME" --strategy "$STRATEGY" --poll-seconds "$POLL"
```
실행권한:
```bash
chmod +x scripts/run-paper.sh
```

- [ ] **Step 2: gitignore에 logs/ 추가** — `.gitignore`에 한 줄 추가(아무 데나 적절한 섹션):
```
# 페이퍼 런 로그 (런타임 산출물)
logs/
```

- [ ] **Step 3: README "7일 페이퍼런" 섹션 추가** — `README.md`의 Week 3 섹션 뒤에:
- 빌드된 것: 측정(`paper-report`)·안전(킬스위치가 도는 루프를 멈춤)·로깅.
- 런 시작:
  ```bash
  tmux new -s paper
  ./scripts/run-paper.sh
  # Ctrl-b d 로 detach. 재접속: tmux attach -t paper
  ```
- 점검: `quantpilot paper-status`, `quantpilot paper-logs`, `quantpilot paper-report`.
- 비상정지(도는 루프도 멈춤): 다른 셸에서 `quantpilot panic` → 루프가 다음 틱에 감지·정지.
- 7일 후: `quantpilot paper-report`로 Sharpe/MaxDD/승률 → Week 5(실거래) 게이트 판단.
- 한계: `TODOS.md` pre-live 항목(confirm 필드, panic funding, JSON 방어)은 Week 5 전 처리.

- [ ] **Step 4: 전체 게이트 + 커밋**

Run:
```bash
python -m pytest -q
ruff check quantpilot/
bash -n scripts/run-paper.sh   # 스크립트 문법 체크
```
Expected: 전부 PASS + `All checks passed!` + 스크립트 문법 OK.
```bash
git add scripts/run-paper.sh README.md .gitignore
git commit -m "feat: 7-day paper run launcher + ops docs (run-paper.sh, README)

수집→paper 루프 런처 + tmux/panic 운영 절차. logs/ gitignore.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (작성자 체크)

**Spec coverage (spec §별 → 태스크):**
- §2(1)/§4a 킬스위치 on 루프 → Task 5 (`read_halted`는 Task 3) ✅
- §2(2)/§4b 파일 로깅 → Task 5 (`logsetup.py`) ✅
- §2(3)/§4c equity 곡선 → Task 2(테이블)+Task 3(영속/조회)+Task 4(봉별 기록) ✅
- §2(3)/§4d `paper-report` → Task 6 (Week 2 `compute_metrics` 재사용) ✅
- §2(4)/§4e 런 셋업 → Task 7 (`run-paper.sh`+README) ✅
- §4c dedup(UNIQUE run_key,ts) → Task 2 제약 + Task 3 on_conflict_do_nothing ✅
- §1 측정=백테 동일 지표 → Task 6이 `compute_metrics`/`periods_per_year` 그대로 사용 ✅
- §2 out-of-scope(JSON 방어/panic funding/confirm) → 구현 안 함(의도, TODOS 유지) ✅

**Placeholder scan:** 모든 코드 스텝에 실제 코드. "TBD"/"적절히" 없음.

**Type consistency:** `persist_tick(session, run_key, state, trades, equity_points=())`가 Task 3
정의와 Task 4/6 호출에서 일치. `load_equity_curve`/`read_halted` 시그니처가 Task 3 정의와
Task 4/5/6 사용에서 일치. `PaperEquityRow`(run_key/ts/equity)가 Task 2 정의와 Task 3 insert·조회에서
일치. `_pnl` 시그니처(side, entry, exit_price, contracts, ct_val) Task 4 사용 일치. `compute_metrics`
반환 키(sharpe/max_drawdown/total_return/n_trades/win_rate/profit_factor)가 Task 6 출력과 일치.

**런타임 주의:** 7일 런 자체는 실시간(운영). 이 플랜은 빌드(하드닝+측정+런처)까지. parity·리스크
불변식은 Week 3 그대로(이번 변경은 측정·안전·로깅 레이어, 매매 판단 불변).
