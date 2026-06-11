# Confluence 전략 (BOT-SPEC 모드 A 코어) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BOT-SPEC 모드 A 점수제(매물대+다이버전스+피보+RSI극단+4h보너스, 게이트 G2/V1, TP 50/40/10 + BE트레일)를 `confluence` 전략으로 구현하고 BTC/ETH 2년 데이터로 검증한다.

**Architecture:** ZigZag 확정 피벗(`pivots.py`)을 공통 기반으로 매물대(`zones.py`)·다이버전스(`divergence.py`)·피보(`fib.py`)를 순수 함수로 쌓고, `confluence.py`가 IStrategy로 조립한다. 엔진은 2가지만 확장(타깃 주입·BE트레일·risk_mult — 전부 기본값이 현행과 동일해 rsi-mr 거동 변화 0), 페이퍼는 같은 함수를 재사용해 자동 상속.

**Tech Stack:** Python 3.12, pandas/numpy(지표 직접 구현), SQLAlchemy 2.0, click, pytest.

**불변 규칙:** 모든 판정은 봉마감 기준 / 손절 먼저 / 룩어헤드 금지(확정 피벗만 노출, 각 시그널에 prefix-일치 테스트 필수) / `ruff check quantpilot/` clean / `git add -A` 금지 / 커밋 메시지 끝 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

**스펙:** `docs/superpowers/specs/2026-06-11-confluence-strategy-design.md` (점수표·게이트·파라미터 §4·§10)

**검증된 기존 시그니처 (이대로 사용, 추측 금지):**
- `Signal(side, confidence, suggested_stop, meta)` — side는 `"long"|"short"|"exit"|"hold"` (`strategy/base.py`)
- `IStrategy`: 클래스 속성 `name/timeframe/lookback`, `generate_signal(window, open_position) -> Signal`
- `open_position(side, bar, stop, capital, ct_val, lot_sz, leverage, fee_bps, slippage_bps) -> (Position|None, entry_fee)` — 내부에서 `calculate_position_size(capital, 0.05, ...)` 호출 (`backtest/engine.py:98`)
- `check_exits(pos, bar, fee_bps, slippage_bps, ct_val) -> (Position|None, list[Fill])` — 손절 먼저, `tp{i}` reason
- `build_targets(entry, stop, side, r_multiples=None, fractions=None) -> list[(price, frac)]`
- `run_backtest(candles, strategy, capital, ct_val, lot_sz, leverage, fee_bps, slippage_bps, funding_events, oos_split_ts)` — 봉 i마다 `window = candles.iloc[i-lookback+1:i+1]`, `signal.side/suggested_stop` 사용
- `trader.process_bar`도 같은 호출 패턴 (`signal = ctx.strategy.generate_signal(window, state.position)`)
- `load_candles_df(session, symbol, timeframe, start_ms=None, end_ms=None)` — index=ts, cols=OHLCV
- `detect_gaps(ts_list, timeframe_ms) -> (missing_count, [(start,end),...])` — **이미 존재** (`data_loader.py`)
- `collect_ohlcv(session, client, symbol, timeframe, days, now_ms, ...)`, `upsert_candles`, `drop_unclosed(rows, timeframe_ms, now_ms)`, `last_candle_ts` (`data/collector.py`)
- `Candle`엔 `inserted_at` NOT NULL — 테스트 시딩 시 필수
- `timeframes._MS`는 현재 `{"15m","1h"}`만 — **4h는 T1에서 추가**

---

### Task 1: timeframes에 4h 추가

**Files:** Modify: `quantpilot/timeframes.py` / Test: `tests/test_timeframes.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_timeframes.py`에 추가:

```python
def test_4h_supported():
    from quantpilot.timeframes import SUPPORTED_TIMEFRAMES, timeframe_to_ms
    assert "4h" in SUPPORTED_TIMEFRAMES
    assert timeframe_to_ms("4h") == 4 * 60 * 60 * 1000
```

- [ ] **Step 2:** `pytest tests/test_timeframes.py -q` → FAIL (`"4h" not in ...`)
- [ ] **Step 3: 구현** — `_MS`에 `"4h": 4 * 60 * 60 * 1000,` 추가. WHY 주석: `# confluence 전략 S6(상위 TF 보너스)·G4 컨텍스트용. 1d는 Phase 2(YAGNI).`
- [ ] **Step 4:** GREEN 확인 (전체 `pytest -q`도 통과 유지)
- [ ] **Step 5:** `git add quantpilot/timeframes.py tests/test_timeframes.py && git commit -m "feat(data): timeframe 4h 지원 — confluence S6 상위TF 보너스용"`

---

### Task 2: gap 메우기 (heal) — collector + CLI

**Files:** Modify: `quantpilot/data/collector.py`, `quantpilot/cli.py` / Test: `tests/test_collector_heal.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_collector_heal.py` 신규:

```python
"""gap 메우기: 기존 데이터의 누락 구간만 재요청해 채운다."""
from quantpilot.data.collector import heal_gaps, upsert_candles

HOUR = 3_600_000
T0 = 1_780_000_000_000


class FakeClient:
    """요청 구간의 캔들을 돌려주는 가짜 클라이언트(결정적)."""
    def __init__(self):
        self.calls = []

    def fetch_ohlcv(self, symbol, timeframe, since_ms, limit):
        self.calls.append(since_ms)
        # since부터 limit개 1h 봉 생성
        return [{"ts": since_ms + i * HOUR, "open": 1.0, "high": 2.0,
                 "low": 0.5, "close": 1.5, "volume": 3.0} for i in range(limit)]


def _seed(session, ts_list):
    rows = [{"ts": t, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
             "volume": 3.0} for t in ts_list]
    upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=T0 + 100 * HOUR)


def test_heal_fills_interior_gap(session):
    # 0..4 + 8..10 적재 → 5,6,7 누락
    _seed(session, [T0 + i * HOUR for i in [0, 1, 2, 3, 4, 8, 9, 10]])
    client = FakeClient()
    r = heal_gaps(session, client, "BTC-USDT-SWAP", "1h", now_ms=T0 + 100 * HOUR)
    assert r["gaps_found"] == 3
    assert r["inserted"] == 3
    from quantpilot.backtest.data_loader import load_candles_df, detect_gaps
    df = load_candles_df(session, "BTC-USDT-SWAP", "1h")
    missing, _ = detect_gaps(list(df.index), HOUR)
    assert missing == 0                      # 구멍 0
    assert client.calls and client.calls[0] == T0 + 5 * HOUR   # 누락 시작점부터 요청


def test_heal_noop_when_continuous(session):
    _seed(session, [T0 + i * HOUR for i in range(5)])
    r = heal_gaps(session, FakeClient(), "BTC-USDT-SWAP", "1h", now_ms=T0 + 100 * HOUR)
    assert r == {"gaps_found": 0, "inserted": 0}
```

- [ ] **Step 2:** `pytest tests/test_collector_heal.py -q` → FAIL (`ImportError: heal_gaps`)
- [ ] **Step 3: 구현** — `collector.py`에 추가 (upsert_candles의 실제 파라미터 순서는 같은 파일의 `collect_ohlcv` 본문이 쓰는 그대로 따라 맞출 것):

```python
def heal_gaps(session, client, symbol: str, timeframe: str, now_ms: int,
              exchange: str = "okx", page_limit: int = 100) -> dict:
    """기존 적재 데이터의 누락 구간만 재수집해 메운다.

    WHY: 증분 수집은 max(ts) 워터마크 기반이라 중간 구멍을 다시 안 받는다(영구 hole).
    백테스트 gap 게이트·RSI 연속성 가정을 만족시키려면 구멍을 명시적으로 메워야 한다.
    detect_gaps(data_loader)를 재사용 — 구멍 정의를 한 곳(detect_gaps)만 소유.
    """
    from sqlalchemy import select
    from quantpilot.backtest.data_loader import detect_gaps
    from quantpilot.data.models import Candle

    tf_ms = timeframe_to_ms(timeframe)
    ts_list = [r[0] for r in session.execute(
        select(Candle.ts).where(
            Candle.exchange == exchange, Candle.symbol == symbol,
            Candle.timeframe == timeframe).order_by(Candle.ts)).all()]
    if len(ts_list) < 2:
        return {"gaps_found": 0, "inserted": 0}
    missing, ranges = detect_gaps(ts_list, tf_ms)
    if missing == 0:
        return {"gaps_found": 0, "inserted": 0}
    inserted = 0
    for start, end in ranges:
        cursor = start
        while cursor <= end:
            batch = client.fetch_ohlcv(symbol, timeframe, since_ms=cursor,
                                       limit=page_limit)
            if not batch:
                break               # 거래소 히스토리 한계 — 남은 구멍은 보고로 드러남
            rows = [b for b in batch if b["ts"] <= end]
            rows = drop_unclosed(rows, tf_ms, now_ms)
            if not rows:
                break
            inserted += upsert_candles(session, exchange, symbol, timeframe,
                                       rows, now_ms)
            cursor = rows[-1]["ts"] + tf_ms
    return {"gaps_found": missing, "inserted": inserted}
```

- [ ] **Step 4:** GREEN 확인
- [ ] **Step 5: CLI 노출** — `cli.py`의 `collect` 명령에 `@click.option("--heal", is_flag=True, default=False, help="기존 데이터의 누락 구간만 재수집")` 추가, 본문 마지막에:

```python
    if heal:
        from quantpilot.data.collector import heal_gaps
        r = heal_gaps(session, client, symbol, timeframe, now_ms=_now_ms())
        click.echo(f"gap 메우기: 누락 {r['gaps_found']}봉 중 {r['inserted']}봉 채움")
```

(함수 시그니처에 `heal` 파라미터 추가 잊지 말 것. 기존 수집 흐름 뒤에 실행 — 새로 받은 데이터의 구멍도 같이 메움.)
- [ ] **Step 6:** `pytest -q` 전체 + `ruff check quantpilot/` clean 확인
- [ ] **Step 7:** `git add quantpilot/data/collector.py quantpilot/cli.py tests/test_collector_heal.py && git commit -m "feat(data): gap 메우기(heal_gaps) + collect --heal — pre-live 연속성 blocker 해결"`

---

### Task 3: HTF 룩어헤드-프리 슬라이스 헬퍼

**Files:** Modify: `quantpilot/backtest/data_loader.py` / Test: `tests/test_data_loader.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_data_loader.py`에 추가:

```python
def test_closed_htf_slice_excludes_unclosed_4h():
    import pandas as pd
    from quantpilot.backtest.data_loader import closed_htf_slice
    H = 3_600_000
    # 4h 봉 시작 ts: 0, 4h, 8h
    htf = pd.DataFrame({"close": [1.0, 2.0, 3.0]},
                       index=[0, 4 * H, 8 * H])
    # 1h봉 ts=3h(03:00~04:00, 마감 04:00): 0~4h 4h봉(마감 04:00)까지 포함
    s = closed_htf_slice(htf, now_ts=3 * H, htf_ms=4 * H, ltf_ms=H)
    assert list(s.index) == [0]
    # 1h봉 ts=6h(마감 07:00): 4h~8h 봉은 08:00 마감이라 아직 미포함
    s = closed_htf_slice(htf, now_ts=6 * H, htf_ms=4 * H, ltf_ms=H)
    assert list(s.index) == [0]
    # 1h봉 ts=7h(마감 08:00): 4h~8h 봉 포함
    s = closed_htf_slice(htf, now_ts=7 * H, htf_ms=4 * H, ltf_ms=H)
    assert list(s.index) == [0, 4 * H]
```

- [ ] **Step 2:** RED 확인 (`ImportError`)
- [ ] **Step 3: 구현** — `data_loader.py`에 추가:

```python
def closed_htf_slice(htf_df: pd.DataFrame, now_ts: int, htf_ms: int,
                     ltf_ms: int) -> pd.DataFrame:
    """LTF 봉(ts=now_ts) 마감 시점에 '이미 마감된' HTF 봉만 반환.

    WHY: 캔들 ts는 봉 '시작' 시각. LTF 봉 마감 = now_ts+ltf_ms, HTF 봉 마감 =
    ts+htf_ms. 마감 안 된 HTF 봉을 보면 룩어헤드(미래 정보)가 된다.
    """
    return htf_df[htf_df.index + htf_ms <= now_ts + ltf_ms]
```

- [ ] **Step 4:** GREEN → **Step 5:** `git add quantpilot/backtest/data_loader.py tests/test_data_loader.py && git commit -m "feat(backtest): closed_htf_slice — 4h 컨텍스트 룩어헤드-프리 슬라이스"`

---

### Task 4: pivots.py — ZigZag 확정 피벗

**Files:** Create: `quantpilot/strategy/pivots.py` / Test: `tests/test_pivots.py`

- [ ] **Step 1: 합성 fixture + 실패 테스트** — `tests/test_pivots.py` 신규:

```python
"""ZigZag 확정 피벗 — 룩어헤드-프리가 핵심 검증."""
import pandas as pd
import pytest

from quantpilot.strategy.pivots import Pivot, confirmed_pivots

HOUR = 3_600_000
T0 = 1_780_000_000_000


def make_df(closes, spread=1.0):
    """종가 시퀀스로 결정적 OHLC 생성. high=close+spread, low=close-spread."""
    idx = [T0 + i * HOUR for i in range(len(closes))]
    return pd.DataFrame({
        "open": closes, "high": [c + spread for c in closes],
        "low": [c - spread for c in closes], "close": closes,
        "volume": [1.0] * len(closes)}, index=idx)


def wave_df():
    # 횡보(ATR 안정화) → 상승 100→130 → 하락 130→95 → 반등 95→115
    closes = ([100.0] * 20
              + [100 + 2 * i for i in range(1, 16)]      # ~130
              + [130 - 2.5 * i for i in range(1, 15)]    # ~95
              + [95 + 2 * i for i in range(1, 11)])      # ~115
    return make_df(closes)


def test_pivots_alternate_and_match_extremes():
    df = wave_df()
    pivots = confirmed_pivots(df, atr_k=3.0)
    assert len(pivots) >= 2
    kinds = [p.kind for p in pivots]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))   # H/L 교대
    # 첫 H 피벗 가격은 상승 구간 최고가(±spread) 근처
    first_h = next(p for p in pivots if p.kind == "H")
    assert first_h.price == pytest.approx(131.0, abs=1.5)   # high=close+1
    # 확정은 극점 '이후' 봉에서만
    assert all(p.confirmed_ts > p.ts for p in pivots)


def test_pivots_lookahead_free():
    """prefix 데이터로 계산한 피벗 == 전체 계산 후 confirmed_ts<=cutoff 필터."""
    df = wave_df()
    full = confirmed_pivots(df, atr_k=3.0)
    for i in range(20, len(df) + 1, 5):
        part = confirmed_pivots(df.iloc[:i], atr_k=3.0)
        cutoff = df.index[i - 1]
        expected = [p for p in full if p.confirmed_ts <= cutoff]
        assert part == expected, f"prefix {i}봉에서 룩어헤드/누락 발생"


def test_pivots_too_short_returns_empty():
    assert confirmed_pivots(make_df([100.0] * 5)) == []
```

- [ ] **Step 2:** RED 확인 (`ModuleNotFoundError`)
- [ ] **Step 3: 구현** — `quantpilot/strategy/pivots.py` 신규:

```python
"""ZigZag 확정 피벗 — confluence 시그널(파동·매물대·다이버전스)의 공통 기반.

WHY '확정(confirmed)' 개념: 잠정 극점은 미래 봉이 갱신할 수 있어 그대로 쓰면
룩어헤드다. 극점에서 ATR×k 이상 반대 이동이 봉마감으로 확인된 시점(confirmed_ts)
이후에만 피벗을 노출한다 → i봉까지 데이터로 계산한 결과가 전체 데이터 계산의
prefix와 항상 일치(룩어헤드-프리 테스트로 강제).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantpilot.strategy.indicators import atr


@dataclass(frozen=True)
class Pivot:
    ts: int            # 극점이 발생한 봉 ts
    price: float       # 극점 가격 (H는 high, L은 low)
    kind: str          # "H" | "L"
    confirmed_ts: int  # 이 봉 마감에 확정됨 — 소비자는 confirmed_ts <= now만 사용


def confirmed_pivots(df: pd.DataFrame, atr_k: float = 3.0,
                     atr_period: int = 14) -> list[Pivot]:
    """ZigZag: 잠정 극점에서 종가가 ATR×k 이상 반대로 가면(봉마감) 극점 확정.

    WHY 종가 기준 확정: 장중 스파이크(휩소)로 피벗이 확정되는 것을 막는다(V4).
    WHY ATR warmup 전 확정 금지: 초기 ATR(Wilder ewm)은 불안정해 임계가 무의미.
    """
    if len(df) < atr_period + 1:
        return []
    a = atr(df["high"], df["low"], df["close"], atr_period)
    ts_arr = list(df.index)
    out: list[Pivot] = []
    hi_px, hi_ts = float(df["high"].iloc[0]), ts_arr[0]
    lo_px, lo_ts = float(df["low"].iloc[0]), ts_arr[0]
    direction: str | None = None   # None=미정, "up"=고점 추적 중, "down"=저점 추적 중
    for i in range(len(df)):
        ts = ts_arr[i]
        hi, lo = float(df["high"].iloc[i]), float(df["low"].iloc[i])
        close = float(df["close"].iloc[i])
        if direction in (None, "up") and hi >= hi_px:
            hi_px, hi_ts = hi, ts
        if direction in (None, "down") and lo <= lo_px:
            lo_px, lo_ts = lo, ts
        if i < atr_period:
            continue
        thr = float(a.iloc[i]) * atr_k
        if direction in (None, "up") and hi_px - close >= thr:
            out.append(Pivot(ts=hi_ts, price=hi_px, kind="H", confirmed_ts=ts))
            direction = "down"
            lo_px, lo_ts = lo, ts
        elif direction in (None, "down") and close - lo_px >= thr:
            out.append(Pivot(ts=lo_ts, price=lo_px, kind="L", confirmed_ts=ts))
            direction = "up"
            hi_px, hi_ts = hi, ts
    return out
```

- [ ] **Step 4:** GREEN. 특히 lookahead-free 테스트가 한 번에 통과 안 되면 후보 갱신/확정 순서를 의심할 것(상태가 i봉 이전 데이터에만 의존해야 함).
- [ ] **Step 5:** `git add quantpilot/strategy/pivots.py tests/test_pivots.py && git commit -m "feat(strategy): ZigZag 확정 피벗 — 룩어헤드-프리 보장"`

---

### Task 5: zones.py — 매물대 박스 (S1)

**Files:** Create: `quantpilot/strategy/zones.py` / Test: `tests/test_zones.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_zones.py` 신규:

```python
"""매물대: 피벗 군집 → 박스. 봉마감 이탈만 인정(휩소 무시), 이탈 후 역할 전환."""
import pandas as pd

from quantpilot.strategy.pivots import Pivot
from quantpilot.strategy.zones import (
    Zone, build_zones, first_zone_above, first_zone_below, touch_side)

HOUR = 3_600_000
T0 = 1_780_000_000_000


def _piv(i, price, kind):
    return Pivot(ts=T0 + i * HOUR, price=price, kind=kind,
                 confirmed_ts=T0 + (i + 2) * HOUR)


def test_build_zones_clusters_nearby_pivots():
    pivots = [_piv(0, 100.0, "L"), _piv(5, 101.0, "L"), _piv(9, 100.5, "L"),
              _piv(3, 130.0, "H")]
    zones = build_zones(pivots, atr_value=4.0, cluster_k=0.5, min_touches=2)
    assert len(zones) == 1                       # 100~101 군집만 (130은 1터치)
    z = zones[0]
    assert z.bottom == 100.0 and z.top == 101.0 and z.touches == 3


def test_zone_break_is_close_based_and_flips_role():
    pivots = [_piv(0, 100.0, "L"), _piv(5, 101.0, "L")]
    # 장중 low가 98(이탈처럼 보임)이지만 종가는 102 → 휩소, 이탈 아님
    closes = pd.Series([102.0, 99.5],
                       index=[T0 + 10 * HOUR, T0 + 11 * HOUR])
    lows = pd.Series([98.0, 99.0], index=closes.index)
    zones = build_zones(pivots, atr_value=4.0, cluster_k=0.5, min_touches=2,
                        closes=closes.iloc[:1])
    assert zones[0].broken_dir is None           # 휩소 → 유지
    zones = build_zones(pivots, atr_value=4.0, cluster_k=0.5, min_touches=2,
                        closes=closes)           # 둘째 봉 종가 99.5 < bottom 100
    assert zones[0].broken_dir == "down"         # 하향 이탈 → 이후 저항


def test_touch_and_first_zone_queries():
    z_support = Zone(top=101.0, bottom=100.0, created_ts=T0, touches=2,
                     broken_dir=None)
    z_broken = Zone(top=121.0, bottom=120.0, created_ts=T0, touches=2,
                    broken_dir="down")           # 하향 이탈됨 → 저항 역할
    zones = [z_support, z_broken]
    # 위에서 내려와 상단 근접 → 지지 터치 (proximity = atr×0.25 = 1.0)
    assert touch_side(zones, price=101.5, atr_value=4.0, side="long") is z_support
    # 이탈된 박스는 지지가 아님
    assert touch_side([z_broken], price=120.5, atr_value=4.0, side="long") is None
    # 아래에서 올라와 저항(이탈된 박스 하단) 근접 → 숏 터치
    assert touch_side([z_broken], price=119.5, atr_value=4.0, side="short") is z_broken
    # G2/TP1용: 현재가 위/아래 첫 박스 경계
    assert first_zone_above(zones, price=110.0) == 120.0
    assert first_zone_below(zones, price=110.0) == 101.0
```

- [ ] **Step 2:** RED → **Step 3: 구현** — `quantpilot/strategy/zones.py` 신규:

```python
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
    """
    if not pivots:
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
            for _, c in after.items():
                if c < bottom:
                    broken = "down"
                    break
                if c > top:
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
```

- [ ] **Step 4:** GREEN → **Step 5:** `git add quantpilot/strategy/zones.py tests/test_zones.py && git commit -m "feat(strategy): 매물대 박스(S1) — 피벗 군집 + 봉마감 플립 + 첫 박스 질의"`

---

### Task 6: divergence.py — RSI 다이버전스 (S2)

**Files:** Create: `quantpilot/strategy/divergence.py` / Test: `tests/test_divergence.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_divergence.py` 신규:

```python
"""RSI 다이버전스: 확정 피벗 2개 비교 + 유효 구간(30/70) + 컨펌·폐기(F1)."""
import pandas as pd

from quantpilot.strategy.divergence import Divergence, detect_divergence
from quantpilot.strategy.pivots import Pivot

HOUR = 3_600_000
T0 = 1_780_000_000_000


def _l(i, price):
    return Pivot(ts=T0 + i * HOUR, price=price, kind="L",
                 confirmed_ts=T0 + (i + 2) * HOUR)


def _h(i, price):
    return Pivot(ts=T0 + i * HOUR, price=price, kind="H",
                 confirmed_ts=T0 + (i + 2) * HOUR)


def _rsi(pairs, n=40):
    """ts→rsi 매핑 시리즈. pairs=[(bar_idx, rsi값)], 나머지는 50."""
    idx = [T0 + i * HOUR for i in range(n)]
    s = pd.Series(50.0, index=idx)
    for i, v in pairs:
        s.iloc[i] = v
    return s


def _lows(pairs, n=40):
    idx = [T0 + i * HOUR for i in range(n)]
    s = pd.Series(1e9, index=idx)        # 기본은 재이탈 없음
    for i, v in pairs:
        s.iloc[i] = v
    return s


def test_bullish_divergence_confirmed():
    # 가격 LL(100→95) + RSI HL(25→28), 둘째 피벗 RSI 28 <= 30(유효 구간)
    pivots = [_l(5, 100.0), _h(10, 120.0), _l(20, 95.0)]
    rsi = _rsi([(5, 25.0), (20, 28.0)])
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 23 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert isinstance(d, Divergence) and d.confirmed
    assert d.anchor.price == 95.0


def test_divergence_discarded_on_reentry():  # F1: 컨펌 후 저점 재이탈 → 폐기
    pivots = [_l(5, 100.0), _h(10, 120.0), _l(20, 95.0)]
    rsi = _rsi([(5, 25.0), (20, 28.0)])
    lows = _lows([(24, 94.0)])           # 확정(22) 이후 24번 봉이 95 하향 재이탈
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 25 * HOUR,
                          lows=lows, highs=None, extreme=30.0)
    assert d is None


def test_divergence_requires_extreme_zone():
    # RSI 둘째 피벗 35 > 30 → 과매도 구간 밖 → 무효 (원문: 단독 과매도와 구분)
    pivots = [_l(5, 100.0), _l(20, 95.0)]
    rsi = _rsi([(5, 33.0), (20, 35.0)])
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 23 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert d is None


def test_double_divergence_flag():
    # 같은 방향 연속 2회: L 피벗 3개가 LL+RSI HL 두 쌍
    pivots = [_l(3, 105.0), _l(12, 100.0), _l(22, 95.0)]
    rsi = _rsi([(3, 22.0), (12, 25.0), (22, 28.0)])
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 25 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert d is not None and d.double


def test_not_confirmed_before_pivot_confirmation():
    # 둘째 피벗 confirmed_ts(22) 이전 시점에는 신호 없음 (봉마감 컨펌 절차)
    pivots = [_l(5, 100.0), _l(20, 95.0)]
    rsi = _rsi([(5, 25.0), (20, 28.0)])
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 21 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert d is None
```

- [ ] **Step 2:** RED → **Step 3: 구현** — `quantpilot/strategy/divergence.py` 신규:

```python
"""RSI 다이버전스(S2) — BOT-SPEC의 핵심 반전 시그널.

원문 규칙 매핑:
- 상승 다이버전스 = 가격 LL + RSI HL, 'RSI 과매도(<=30) 구간 발생만 유효' (숏은 거울)
- 컨펌 = 봉마감 대기 → 피벗 확정(ZigZag의 ATR×k 반대 이동이 '강한 반등' 역할)
- F1 폐기 = 컨펌 후 비교 저점(고점)을 종가가 아닌 저가/고가로라도 재이탈하면 무효
- 더블 = 같은 방향 연속 2쌍 → 신뢰 보너스
WHY 피벗 confirmed_ts 게이트: 미확정 극점으로 다이버전스를 만들면 룩어헤드.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantpilot.strategy.pivots import Pivot


@dataclass(frozen=True)
class Divergence:
    side: str          # "long" | "short"
    anchor: Pivot      # 둘째(최근) 피벗 — 손절 기준점으로도 사용
    prev: Pivot
    confirmed: bool
    double: bool


def detect_divergence(pivots: list[Pivot], rsi: pd.Series, side: str,
                      now_ts: int, lows: pd.Series | None,
                      highs: pd.Series | None,
                      extreme: float = 30.0) -> Divergence | None:
    """now_ts 시점에 유효한 최신 다이버전스를 반환(없으면 None).

    lows/highs: F1 재이탈 검사용 시계열(index=ts). 롱이면 lows, 숏이면 highs 필요.
    """
    kind = "L" if side == "long" else "H"
    sel = [p for p in pivots if p.kind == kind and p.confirmed_ts <= now_ts]
    if len(sel) < 2:
        return None
    prev, anchor = sel[-2], sel[-1]
    if anchor.ts not in rsi.index or prev.ts not in rsi.index:
        return None
    r_prev, r_anchor = float(rsi.loc[prev.ts]), float(rsi.loc[anchor.ts])
    if side == "long":
        price_div = anchor.price < prev.price          # LL
        rsi_div = r_anchor > r_prev                    # HL
        in_zone = r_anchor <= extreme                  # 과매도 구간 발생만 유효
        series, breach = lows, (lambda v: v < anchor.price)
    else:
        price_div = anchor.price > prev.price          # HH
        rsi_div = r_anchor < r_prev                    # LH
        in_zone = r_anchor >= extreme                  # extreme=70.0으로 호출
        series, breach = highs, (lambda v: v > anchor.price)
    if not (price_div and rsi_div and in_zone):
        return None
    # F1: 피벗 확정 이후 ~ now까지 비교점 재이탈 시 폐기
    if series is not None:
        window = series[(series.index > anchor.ts) & (series.index <= now_ts)]
        if any(breach(float(v)) for v in window):
            return None
    # 더블: 직전 쌍(prev2→prev)도 같은 방향 다이버전스였나
    double = False
    if len(sel) >= 3:
        p2 = sel[-3]
        if p2.ts in rsi.index:
            r2 = float(rsi.loc[p2.ts])
            if side == "long":
                double = prev.price < p2.price and r_prev > r2
            else:
                double = prev.price > p2.price and r_prev < r2
    return Divergence(side=side, anchor=anchor, prev=prev,
                      confirmed=True, double=double)
```

- [ ] **Step 4:** GREEN → **Step 5:** `git add quantpilot/strategy/divergence.py tests/test_divergence.py && git commit -m "feat(strategy): RSI 다이버전스(S2) — 유효구간·F1 폐기·더블 보너스"`

---

### Task 7: fib.py — 피보나치 되돌림 (S4)

**Files:** Create: `quantpilot/strategy/fib.py` / Test: `tests/test_fib.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_fib.py` 신규:

```python
from quantpilot.strategy.fib import fib_levels, in_entry_zone, last_wave
from quantpilot.strategy.pivots import Pivot

T0 = 1_780_000_000_000
H = 3_600_000


def test_fib_levels_down_wave():
    # 하락 파동 H(100) → L(50): 되돌림은 위로. 0.5=75, 0.618=80.9
    lv = fib_levels(start=100.0, end=50.0)
    assert lv[0.5] == 75.0
    assert round(lv[0.618], 1) == 80.9
    assert round(lv[0.382], 1) == 69.1


def test_fib_levels_up_wave():
    lv = fib_levels(start=50.0, end=100.0)     # 상승 파동 → 아래로 되돌림
    assert lv[0.5] == 75.0
    assert round(lv[0.618], 1) == 69.1


def test_last_wave_uses_last_two_confirmed():
    piv = [Pivot(T0, 100.0, "H", T0 + 2 * H), Pivot(T0 + 5 * H, 50.0, "L", T0 + 7 * H)]
    w = last_wave(piv, now_ts=T0 + 7 * H)
    assert w == (100.0, 50.0)
    assert last_wave(piv, now_ts=T0 + 6 * H) is None   # L 미확정 시점 → 파동 없음
    assert last_wave([piv[0]], now_ts=T0 + 9 * H) is None


def test_in_entry_zone():
    lv = fib_levels(100.0, 50.0)               # 0.5=75, 0.618=80.9
    assert in_entry_zone(76.0, lv)
    assert in_entry_zone(80.0, lv)
    assert not in_entry_zone(85.0, lv)
    assert not in_entry_zone(70.0, lv)
```

- [ ] **Step 2:** RED → **Step 3: 구현** — `quantpilot/strategy/fib.py` 신규:

```python
"""피보나치 되돌림(S4) — 직전 '확정' 파동 기준.

WHY 확정 파동만: 진행 중 파동에 걸면 끝점이 계속 변해 레벨이 흔들린다(룩어헤드).
원문 승계: 주시 레벨 0.382/0.5/0.618, 진입 존 = 0.5~0.618.
"""
from __future__ import annotations

from quantpilot.strategy.pivots import Pivot

LEVELS = (0.382, 0.5, 0.618)


def last_wave(pivots: list[Pivot], now_ts: int) -> tuple[float, float] | None:
    """now_ts 기준 확정된 마지막 파동 (시작가, 끝가). 피벗 2개 미만이면 None."""
    sel = [p for p in pivots if p.confirmed_ts <= now_ts]
    if len(sel) < 2:
        return None
    return (sel[-2].price, sel[-1].price)


def fib_levels(start: float, end: float) -> dict[float, float]:
    """파동(start→end)의 되돌림 레벨. 레벨 r = end + (start-end)*r."""
    return {r: end + (start - end) * r for r in LEVELS}


def in_entry_zone(price: float, levels: dict[float, float]) -> bool:
    """진입 존 = 0.5~0.618 레벨 사이(파동 방향 무관하게 min/max로 판정)."""
    lo, hi = sorted((levels[0.5], levels[0.618]))
    return lo <= price <= hi
```

- [ ] **Step 4:** GREEN → **Step 5:** `git add quantpilot/strategy/fib.py tests/test_fib.py && git commit -m "feat(strategy): 피보나치 되돌림(S4) — 확정 파동 기준 레벨/진입존"`

---

### Task 8: 엔진 — TP 타깃 주입 (rsi-mr 거동 불변)

**Files:** Modify: `quantpilot/backtest/engine.py` / Test: `tests/test_engine_targets.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_engine_targets.py` 신규:

```python
"""open_position의 명시적 타깃 주입 — 기본 경로(주입 없음)는 기존과 동일해야 함."""
from quantpilot.backtest.engine import open_position
from quantpilot.risk.take_profit import build_targets

BAR = {"ts": 1_780_000_000_000, "open": 100.0, "high": 101.0,
       "low": 99.0, "close": 100.0}


def test_default_targets_unchanged():           # 회귀: rsi-mr 경로
    pos, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0)
    assert pos is not None
    assert pos.targets_remaining == build_targets(pos.entry, 95.0, "long")


def test_explicit_targets_used():
    custom = [(103.0, 0.5), (108.0, 0.4)]       # 50/40, 잔여 10%는 러너
    pos, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                           targets=custom)
    assert pos.targets_remaining == custom
```

- [ ] **Step 2:** RED (`unexpected keyword 'targets'`)
- [ ] **Step 3: 구현** — `engine.py` `open_position` 시그니처에 `targets: list[tuple[float, float]] | None = None` 추가, 본문의 `targets = build_targets(entry, stop, side)` 를:

```python
    # WHY 주입 허용: confluence는 구조 기반 타깃(첫 매물대/피보)을 쓴다. None이면
    # 기존 R-배수 사다리 그대로 → 기존 전략(rsi-mr) 거동 변화 0.
    if targets is None:
        targets = build_targets(entry, stop, side)
```

`run_backtest`의 진입 분기와 `paper/trader.py` `process_bar`의 진입 분기에서 호출을 다음처럼 변경(두 곳 동일):

```python
            position, open_fee = open_position(
                signal.side, bar, signal.suggested_stop, equity, ct_val, lot_sz,
                leverage, fee_bps, slippage_bps,
                targets=signal.meta.get("targets"))
```

(trader 쪽 변수명은 기존 코드 그대로: `state.equity`, `ctx.ct_val` 등.)
- [ ] **Step 4:** GREEN + 기존 전체 `pytest -q` 통과(=rsi-mr 회귀 없음 증명)
- [ ] **Step 5:** `git add quantpilot/backtest/engine.py quantpilot/paper/trader.py tests/test_engine_targets.py && git commit -m "feat(engine): Signal.meta[targets] 주입 — 기본 경로 불변(rsi-mr 회귀 0)"`

---

### Task 9: 엔진 — TP1 후 본전(BE) 트레일링

**Files:** Modify: `quantpilot/backtest/engine.py`, `quantpilot/paper/trader.py` / Test: `tests/test_engine_be_trail.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_engine_be_trail.py` 신규:

```python
"""TP1 체결 후 손절을 본전(entry)으로 이동 — 옵션, 기본 off."""
from quantpilot.backtest.engine import check_exits
from quantpilot.backtest.models import Position


def _pos():
    return Position(side="long", entry=100.0, contracts=10, stop=95.0,
                    targets_remaining=[(105.0, 0.3), (110.0, 0.3), (115.0, 0.4)],
                    opened_ts=0, original_contracts=10)


def test_be_trail_moves_stop_after_tp1():
    pos = _pos()
    bar = {"ts": 1, "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01, be_trail_after_tp1=True)
    assert any(f.reason == "tp1" for f in fills)
    assert pos2 is not None and pos2.stop == 100.0          # 본전 이동


def test_be_trail_default_off_keeps_stop():
    pos = _pos()
    bar = {"ts": 1, "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01)
    assert any(f.reason == "tp1" for f in fills)
    assert pos2.stop == 95.0                                 # 기존 거동(불변)


def test_be_trail_never_lowers_short_stop():
    pos = Position(side="short", entry=100.0, contracts=10, stop=105.0,
                   targets_remaining=[(95.0, 0.3), (90.0, 0.7)],
                   opened_ts=0, original_contracts=10)
    bar = {"ts": 1, "open": 100.0, "high": 101.0, "low": 94.0, "close": 94.5}
    pos2, fills = check_exits(pos, bar, 5.0, 0.0, 0.01, be_trail_after_tp1=True)
    assert any(f.reason == "tp1" for f in fills)
    assert pos2.stop == 100.0                                # 숏도 본전으로 (아래로)
```

- [ ] **Step 2:** RED → **Step 3: 구현** — `check_exits` 시그니처에 `be_trail_after_tp1: bool = False` 추가, 함수 끝의 부분익절 처리 후(`pos.targets_remaining = remaining` 직전)에:

```python
    # WHY BE 트레일: BOT-SPEC §7.1 — 50% 익절(TP1) 후 손절을 본전으로 이동해
    # '이긴 거래를 진 거래로 만들지 않는다'. 같은 봉에서는 손절 먼저 검사가 이미
    # 끝났으므로 이동된 stop은 다음 봉부터 적용된다(보수 가정 유지).
    if be_trail_after_tp1 and any(f.reason == "tp1" for f in fills):
        pos.stop = pos.entry
```

호출부 2곳 변경 — `run_backtest`와 `process_bar`의 `check_exits(...)`에 `be_trail_after_tp1=getattr(strategy, "be_trail_after_tp1", False)` 전달 (trader는 `ctx.strategy`; **panic 경로의 `_close_out`/`panic_close`는 check_exits를 안 쓰므로 무관**).
- [ ] **Step 4:** GREEN + 전체 pytest (paper 쪽 기존 테스트가 `ctx.strategy=None`인 경우 `getattr(None, ...)` → False 폴백 확인: `getattr(ctx.strategy, "be_trail_after_tp1", False) if ctx.strategy else False` 형태로 방어)
- [ ] **Step 5:** `git add quantpilot/backtest/engine.py quantpilot/paper/trader.py tests/test_engine_be_trail.py && git commit -m "feat(engine): TP1 후 본전 트레일링(옵션, 기본 off) — 백테=페이퍼 공유"`

---

### Task 10: 엔진 — 점수 연동 사이징 (risk_mult)

**Files:** Modify: `quantpilot/backtest/engine.py`, `quantpilot/paper/trader.py` / Test: `tests/test_engine_risk_mult.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_engine_risk_mult.py` 신규:

```python
"""meta['risk_mult']로 per-trade 리스크 축소(0.5=2.5%). 기본 1.0 → 기존 불변."""
from quantpilot.backtest.engine import open_position

BAR = {"ts": 1_780_000_000_000, "open": 100.0, "high": 101.0,
       "low": 99.0, "close": 100.0}


def test_risk_mult_halves_contracts():
    full, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0)
    half, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                            risk_mult=0.5)
    assert full is not None and half is not None
    assert half.contracts <= full.contracts // 2 + 1   # 리스크 절반 → 계약수 ≈ 절반
    assert half.contracts < full.contracts


def test_risk_mult_default_is_identity():
    a, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0)
    b, _ = open_position("long", BAR, 95.0, 10_000.0, 0.01, 1.0, 3, 5.0, 0.0,
                         risk_mult=1.0)
    assert a.contracts == b.contracts
```

- [ ] **Step 2:** RED → **Step 3: 구현** — `open_position` 시그니처에 `risk_mult: float = 1.0` 추가, `calculate_position_size(capital, 0.05, ...)` → `calculate_position_size(capital, 0.05 * risk_mult, ...)`. WHY 주석:

```python
    # WHY risk_mult: BOT-SPEC §2.3 점수 연동 — 최소 진입(4~5점)=0.5배(2.5%),
    # 강진입(6점+)=1.0배(5%). 근거 강도에 비례한 베팅. 기본 1.0이라 기존 전략 불변.
    # 사이징 invariant(assert)는 calculate_position_size 안에서 축소된 예산으로 동일 강제.
```

호출부 2곳(run_backtest/process_bar): `risk_mult=float(signal.meta.get("risk_mult", 1.0))` 전달.
- [ ] **Step 4:** GREEN + 전체 pytest → **Step 5:** `git add quantpilot/backtest/engine.py quantpilot/paper/trader.py tests/test_engine_risk_mult.py && git commit -m "feat(engine): meta[risk_mult] 점수 연동 사이징(기본 1.0 불변)"`

---

### Task 11: confluence.py — 전략 조립 (점수+게이트)

**Files:** Create: `quantpilot/strategy/confluence.py` / Test: `tests/test_confluence.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_confluence.py` 신규 (합성 시나리오는 Task 4의 `wave_df` 패턴 재사용):

```python
"""confluence 전략: 점수 합산 + G2/V1 게이트 + risk_mult/targets meta."""
import pandas as pd
import pytest

from quantpilot.strategy.confluence import ConfluenceStrategy

HOUR = 3_600_000
T0 = 1_780_000_000_000


def make_df(closes, lows=None, highs=None):
    idx = [T0 + i * HOUR for i in range(len(closes))]
    lows = lows or [c - 1.0 for c in closes]
    highs = highs or [c + 1.0 for c in closes]
    return pd.DataFrame({"open": closes, "high": highs, "low": lows,
                         "close": closes, "volume": [1.0] * len(closes)},
                        index=idx)


def long_setup_df():
    """매물대 지지(이중 바닥) + 과매도 + LL/HL 다이버전스가 겹치는 합성 롱 셋업.

    구조: 100 횡보 → 1차 하락 저점 90 → 반등 110 → 2차 하락 저점 88(LL, 완만=RSI HL)
    → 강반등(피벗 확정 + 다이버전스 컨펌) → 마지막 봉이 지지 박스(88~90) 위 재터치.
    """
    closes = ([100.0] * 20
              + [100 - 1.0 * i for i in range(1, 11)]     # →90 (가파른 1차)
              + [90 + 2.0 * i for i in range(1, 11)]      # →110
              + [110 - 0.8 * i for i in range(1, 28)]     # →88.4 (완만한 2차: RSI HL)
              + [88.4 + 2.0 * i for i in range(1, 8)]     # 강반등 →102 (피벗 확정)
              + [102 - 1.5 * i for i in range(1, 9)])     # 90.0 — 지지 리테스트
    return make_df(closes)


def test_long_entry_with_score_and_meta():
    df = long_setup_df()
    strat = ConfluenceStrategy(timeframe="1h")
    sig = strat.generate_signal(df, None)
    assert sig.side == "long"
    m = sig.meta
    assert m["score"] >= 4 and m["families"] >= 2
    assert m["risk_mult"] in (0.5, 1.0)
    assert sig.suggested_stop is not None and sig.suggested_stop < df["close"].iloc[-1]
    # 타깃: [(TP1, 0.5), (TP2, 0.4)] — 잔여 10%는 러너
    assert [f for _, f in m["targets"]] == [0.5, 0.4]
    assert all(p > df["close"].iloc[-1] for p, _ in m["targets"])


def test_hold_when_position_open():
    df = long_setup_df()
    strat = ConfluenceStrategy(timeframe="1h")
    sig = strat.generate_signal(df, object())   # 포지션 보유 중 → 신규 신호 없음
    assert sig.side == "hold"


def test_g2_rr_gate_blocks_entry():
    df = long_setup_df()
    # 손익비를 강제로 무너뜨림: TP1을 진입가 코앞으로 (rr_min을 크게)
    strat = ConfluenceStrategy(timeframe="1h", rr_min=50.0)
    sig = strat.generate_signal(df, None)
    assert sig.side == "hold"
    assert sig.meta.get("blocked") == "G2"


def test_v1_one_way_filter_blocks():
    # 마지막 20봉을 전부 음봉(일방 하락)으로 → 역추세 롱 차단
    closes = [200.0 - 3.0 * i for i in range(60)]
    df = make_df(closes)
    strat = ConfluenceStrategy(timeframe="1h")
    sig = strat.generate_signal(df, None)
    assert sig.side == "hold"


def test_score_below_threshold_holds():
    df = make_df([100.0] * 60)                  # 시그널 없음
    strat = ConfluenceStrategy(timeframe="1h")
    assert strat.generate_signal(df, None).side == "hold"
```

- [ ] **Step 2:** RED → **Step 3: 구현** — `quantpilot/strategy/confluence.py` 신규:

```python
"""confluence(BOT-SPEC 모드 A 코어) — 근거 겹침 점수제 진입.

점수표(스펙 §4.5): S1 매물대 ±2 / S2 다이버전스 ±2(+더블1) / S4 피보존 +1 /
S5 RSI극단 +1 / S6 4h 동발 +1(캡2). 진입: ≥4점·2계열(risk 0.5배) / ≥6점·3계열(1.0배).
게이트: G2 손익비≥rr_min(TP1=첫 매물대), V1 원웨이 차단. 모든 판정 봉마감 기준.
청산은 엔진 소유: TP 사다리 50/40/10(meta.targets) + TP1 후 본전 트레일 + 손절.
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
    be_trail_after_tp1 = True      # 엔진이 getattr로 읽음 (Task 9)

    def __init__(self, timeframe: str = "1h", htf_df: pd.DataFrame | None = None,
                 rsi_period: int = 14, atr_period: int = 14,
                 zigzag_atr_k: float = 3.0, oversold: float = 30.0,
                 overbought: float = 70.0,
                 entry_min: int = 4, entry_families: int = 2,
                 strong_min: int = 6, strong_families: int = 3,
                 rr_min: float = 1.5,
                 one_way_lookback: int = 20, one_way_ratio: float = 0.8,
                 htf_ms: int = 4 * HOUR_MS, ltf_ms: int = HOUR_MS):
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
        # WHY 200: 피벗·매물대는 수십 봉의 구조가 필요. RSI/ATR warmup 포함 여유.
        self.lookback = 200

    def set_htf(self, df: pd.DataFrame) -> None:
        self.htf_df = df

    # ---- 내부 ----
    def _one_way(self, window: pd.DataFrame, side: str) -> bool:
        """V1: 직전 N봉 동일방향 비율 > x → 역추세 진입 금지."""
        tail = window.iloc[-self.one_way_lookback:]
        if len(tail) < self.one_way_lookback:
            return False
        down = (tail["close"] < tail["open"]).mean()
        up = (tail["close"] > tail["open"]).mean()
        if side == "long":
            return down > self.one_way_ratio       # 일방 하락 중 롱 금지
        return up > self.one_way_ratio

    def _score_side(self, side: str, window, pivots, zones, rsi_s, atr_v,
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
        wave = last_wave(pivots, now_ts)
        levels = fib_levels(*wave) if wave else None
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
        # S6: 핵심 시그널(S1/S2)이 4h에서도 성립 — +1씩, 캡 +2
        if self.htf_df is not None and len(self.htf_df):
            htf = closed_htf_slice(self.htf_df, now_ts, self.htf_ms, self.ltf_ms)
            if len(htf) >= self.rsi_period + 2:
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
                score += min(bonus, 2)
                if bonus:
                    detail["S6"] = min(bonus, 2)
        return score, families, {**detail, "stop_anchor": div.anchor.price if div else None}

    def generate_signal(self, window: pd.DataFrame, open_position) -> Signal:
        if open_position is not None:
            # 청산은 엔진의 TP 사다리/BE 트레일/손절이 담당 — 전략 exit 신호 없음.
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

        # 손절: 직전 확정 피벗(다이버전스 anchor 우선) 바깥 + 0.1 ATR 버퍼
        anchor = detail.get("stop_anchor")
        if anchor is None:
            sel = [p for p in pivots if p.confirmed_ts <= now_ts
                   and p.kind == ("L" if side == "long" else "H")]
            if not sel:
                return Signal("hold", 0.0, None, {"blocked": "no_pivot"})
            anchor = sel[-1].price
        stop = anchor - 0.1 * atr_v if side == "long" else anchor + 0.1 * atr_v
        risk = abs(close - stop)
        if risk <= 0:
            return Signal("hold", 0.0, None, {"blocked": "zero_risk"})

        # TP1 = 경로상 첫 매물대 경계(없으면 1.5R 폴백) / TP2 = 피보 0.618 목표(없으면 2.5R)
        if side == "long":
            tp1 = first_zone_above(zones, close) or close + 1.5 * risk
            tp2 = max(tp1 + 0.5 * risk, close + 2.5 * risk)
            wave = last_wave(pivots, now_ts)
            if wave:
                lv = fib_levels(*wave)
                cand = max(lv.values())
                if cand > tp1:
                    tp2 = cand
            rr = (tp1 - close) / risk
        else:
            tp1 = first_zone_below(zones, close) or close - 1.5 * risk
            tp2 = min(tp1 - 0.5 * risk, close - 2.5 * risk)
            wave = last_wave(pivots, now_ts)
            if wave:
                lv = fib_levels(*wave)
                cand = min(lv.values())
                if cand < tp1:
                    tp2 = cand
            rr = (close - tp1) / risk
        if rr < self.rr_min:
            # G2: 손익비 미달 → 진입 금지 (V6 목표 경로 차단 내장: TP1=첫 벽)
            return Signal("hold", 0.0, None, {"blocked": "G2", "rr": rr,
                                              "score": score})

        strong = score >= self.strong_min and len(families) >= self.strong_families
        meta = {"score": score, "families": len(families),
                "family_set": sorted(families), "risk_mult": 1.0 if strong else 0.5,
                "targets": [(tp1, 0.5), (tp2, 0.4)],   # 잔여 10% = 러너(BE트레일 보호)
                "rr_tp1": rr, "detail": detail}
        return Signal(side, 1.0 if strong else 0.5, stop, meta)
```

- [ ] **Step 4:** GREEN까지 반복. 합성 fixture가 의도한 시그널을 안 만들면 **fixture를 조정**(전략 로직을 테스트에 끼워 맞추지 말 것). 각 테스트가 검증하는 규칙(점수·게이트)이 본질.
- [ ] **Step 5: 룩어헤드-프리 통합 테스트** — `tests/test_confluence.py`에 추가:

```python
def test_confluence_lookahead_free():
    """i봉까지의 window로 낸 신호가 미래 봉 추가로 바뀌지 않는다(과거 신호 불변)."""
    df = long_setup_df()
    strat = ConfluenceStrategy(timeframe="1h")
    n = len(df)
    sig_at = {}
    for i in range(strat.lookback, n + 1):
        sig_at[i] = strat.generate_signal(df.iloc[:i], None).side
    # 전체 데이터에서 같은 prefix를 다시 잘라 계산해도 동일해야 함
    for i in range(strat.lookback, n + 1, 3):
        again = ConfluenceStrategy(timeframe="1h").generate_signal(df.iloc[:i], None)
        assert again.side == sig_at[i]
```

- [ ] **Step 6:** GREEN + `ruff check quantpilot/`
- [ ] **Step 7:** `git add quantpilot/strategy/confluence.py tests/test_confluence.py && git commit -m "feat(strategy): confluence 점수제 전략 — S1/S2/S4/S5/S6 + G2/V1 게이트"`

---

### Task 12: CLI 등록 + --htf + 페이퍼 parity

**Files:** Modify: `quantpilot/cli.py` / Test: `tests/test_cli_backtest.py`, `tests/test_paper_parity.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_cli_backtest.py`에 추가:

```python
def test_confluence_registered():
    from quantpilot.cli import STRATEGIES
    from quantpilot.strategy.confluence import ConfluenceStrategy
    assert STRATEGIES["confluence"] is ConfluenceStrategy
```

- [ ] **Step 2:** RED → **Step 3: 구현** — `cli.py`:
  - import 추가 + `STRATEGIES = {"rsi-mr": RsiMeanReversion, "confluence": ConfluenceStrategy}`
  - `backtest` 명령에 `@click.option("--htf", default=None, help="상위 TF 컨텍스트(예: 4h) — confluence S6 보너스")` 추가. 본문에서 전략 생성 직후:

```python
    if htf:
        if htf not in SUPPORTED_TIMEFRAMES:
            raise click.ClickException(f"지원하지 않는 htf '{htf}'")
        htf_df = load_candles_df(session, symbol, htf)
        if hasattr(strat, "set_htf"):
            strat.set_htf(htf_df)
        from quantpilot.timeframes import timeframe_to_ms as _tfms
        if hasattr(strat, "htf_ms"):
            strat.htf_ms = _tfms(htf)
            strat.ltf_ms = _tfms(timeframe)
```

  - `paper` 명령(`_paper_ctx_and_state`)에도 동일한 htf 주입 옵션 추가 — `--htf` 옵션 + 전략 생성 후 `set_htf` (페이퍼는 매 틱 최신 4h를 다시 로드해야 하므로, **`run_one_tick`이 `hasattr(ctx.strategy,'set_htf')`일 때 캔들 적재 후 `load_candles_df(session, symbol, htf)`를 호출해 갱신**하는 작은 수정 포함. htf 문자열은 `ctx.htf = htf`로 TickContext에 옵션 필드 추가.)
- [ ] **Step 4: parity 테스트** — `tests/test_paper_parity.py`에 confluence 케이스 추가 (기존 parity 테스트 함수를 복제해 strategy만 교체, BE트레일·부분익절 경로 포함되도록 Task 11의 `long_setup_df` 데이터 사용; 백테 `run_backtest` 결과의 trades/equity와 페이퍼 `process_bar` 루프 결과가 동일함을 단언 — 기존 테스트의 비교 패턴 그대로):

```python
def test_paper_matches_backtest_confluence():
    # 기존 test_paper_matches_backtest와 동일 구조, strategy=ConfluenceStrategy.
    # 핵심: targets 주입·risk_mult·BE트레일이 백테/페이퍼 양쪽에서 같은 결과.
    ...  # 기존 함수 본문을 복제하되 전략·fixture만 교체 (파일 내 기존 헬퍼 재사용)
```

(실제 작성 시 기존 함수 본문을 열어 그대로 복제·수정할 것 — 이 파일의 기존 헬퍼/시딩 함수를 재사용.)
- [ ] **Step 5:** 전체 `pytest -q` GREEN + ruff
- [ ] **Step 6:** `git add quantpilot/cli.py quantpilot/paper/trader.py tests/test_cli_backtest.py tests/test_paper_parity.py && git commit -m "feat(cli): confluence 등록 + --htf 컨텍스트 + 백테=페이퍼 parity 검증"`

---

### Task 13: 데이터 수집 + 검증 실행 (런북)

**Files:** Modify: `quantpilot/cli.py` (--start/--end 옵션) / Create: `docs/validation/confluence-v1.md`

- [ ] **Step 1: backtest 구간 옵션** — walk-forward용. `backtest`에 `@click.option("--start-ms", default=None, type=int)`·`@click.option("--end-ms", default=None, type=int)` 추가, `load_with_gap_check` 호출을 `load_candles_df(session, symbol, timeframe, start_ms, end_ms)` + 기존 gap 검사 조합으로 교체(옵션 없으면 기존 동작). 테스트: `tests/test_cli_backtest.py`에 구간 지정 시 곡선 첫/끝 ts가 범위 안인지 단언.
- [ ] **Step 2: 수집 실행** (실명령 — 휴먼/에이전트가 순서대로):

```bash
for SYM in BTC-USDT-SWAP ETH-USDT-SWAP; do
  for TF in 15m 1h 4h; do
    .venv/bin/quantpilot collect --symbol $SYM --timeframe $TF --days 730 --heal
  done
  .venv/bin/quantpilot collect-funding --symbol $SYM --days 730
done
.venv/bin/quantpilot status   # 봉 수·연속성 확인 (⚠ 표시 0이어야 함)
```

  주의: OKX 히스토리 한계로 730일이 다 안 올 수 있음(15m은 특히). `status` 결과를 검증 문서에 기록하고, 실제 받은 구간으로 검증 기간을 정의한다.
- [ ] **Step 3: 검증 실행 + 문서** — `docs/validation/confluence-v1.md` 생성, 아래 표를 채움:

```markdown
# confluence v1 검증 (스펙 §7 — 합격: 모든 OOS PF>1 & MaxDD rsi-mr 대비 악화 없음)
## V-1 BTC 1h train/OOS      → backtest --strategy confluence --htf 4h --oos-months 4
## V-2 walk-forward 3분할    → --start-ms/--end-ms로 [T0,T1),[T1,T2),[T2,T3) 각각 OOS 평가
## V-3 ETH 교차              → 같은 파라미터로 --symbol ETH-USDT-SWAP
## V-4 민감도: zigzag_atr_k {2.5,3.0,3.5} × entry_min {4,5} (전략 생성자 인자 노출 확인)
## V-5 rsi-mr 베이스라인     → 동일 기간 backtest --strategy rsi-mr
| 단계 | 기간 | trades | PF | Sharpe | MaxDD | 판정 |
```

- [ ] **Step 4:** 결과 기록 후 commit: `git add quantpilot/cli.py tests/test_cli_backtest.py docs/validation/confluence-v1.md && git commit -m "feat(backtest): 구간 옵션(--start/--end) + confluence v1 검증 리포트"`
  (검증 **불합격**이면: 결과 그대로 기록 + TODOS에 보정/기각 결정 항목 추가 — 합격처럼 꾸미지 말 것.)

---

### Task 14: 문서 + 최종 검증

**Files:** Modify: `README.md`, `TODOS.md`

- [ ] **Step 1:** README에 confluence 섹션(전략 개요·점수표 요약·사용법 `backtest --strategy confluence --htf 4h`·검증 문서 링크). TODOS에 Phase 2 defer 추가: S3 추세선/채널, 모드 B(삼각수렴·웻지), 15m 진입 타이밍, 예측 진입 모드, 페이퍼 htf 자동 수집(`run_one_tick`에서 4h collect).
- [ ] **Step 2: 최종 게이트** — `.venv/bin/python -m pytest -q` 전체 GREEN + `.venv/bin/ruff check quantpilot/` clean + `git log --oneline` 커밋 정리 확인.
- [ ] **Step 3:** `git add README.md TODOS.md && git commit -m "docs: confluence 전략 사용법 + Phase 2 defer 항목"`

---

## Self-Review 체크 (plan 작성자 확인 완료)

- 스펙 §2 결정 매핑: ①코어 슬라이스→T4~T11 ②ZigZag→T4 ③데이터 BTC+ETH/3TF/2년→T1·T2·T13 ④1h+4h컨텍스트→T3·T11(S6)·T12(--htf) ⑤5%+점수연동→T10·T11(risk_mult)
- 룩어헤드-프리 테스트: T4(피벗)·T11 Step5(전략 통합) 필수, T3은 마감 경계 단위 테스트
- rsi-mr 거동 불변 증명: T8/T9/T10 각각 기본값 회귀 테스트 + 전체 스위트 유지
- placeholder: T12 parity의 `...` 1곳은 "기존 함수 복제" 지시가 명시된 의도적 위임(파일 내 기존 코드 참조)
