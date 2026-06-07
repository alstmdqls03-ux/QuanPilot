# Week 3 — 페이퍼 트레이더 설계 (Paper Trader)

작성일: 2026-06-08
상태: 설계 승인됨 → 구현 대기 (worktree + plan 단계로 진행)

---

## 1. 목적 / 배경

Week 2에서 만든 백테스트 엔진을 **실시간 OKX 데이터에 그대로 붙여서 $0 리스크로 검증**하는 단계.
실거래(Week 5+)로 넘어가기 전에 "엔진이 라이브에서도 백테스트와 똑같이 동작하는가"를
증명하는 다리(bridge)다.

핵심 원칙은 CLAUDE.md의 **"백테=실전 일치"**:
페이퍼 트레이더는 새 매매 로직을 만들지 않는다. Week 2의 per-bar step 함수
(`check_exits`, `IStrategy.generate_signal`, 사이징/청산/익절)를 **글자 그대로 재사용**하고,
바깥 루프(과거 봉 재생 → 실시간 봉 폴링)만 교체한다. 그래서 페이퍼에서 잡히는 거래는
백테스트가 같은 봉에서 냈을 거래와 동일해야 한다(검증 테스트로 강제 — §9 parity test).

부수 효과: 페이퍼 루프가 매 틱 OKX를 폴링해 SQLite에 적재하므로, **라이브 데이터가
공짜로 쌓인다**(Week 1 수집기 재사용). 별도 수집 작업 없이 7일 페이퍼런(Week 4) 데이터 확보.

리스크 게이트(불변): **진짜 돈은 절대 없다.** data → backtest → **paper(여기)** → validate를
전부 $0로 통과한 뒤에만 실거래.

---

## 2. 스코프

### In scope (이번 Week에 만든다)
- **단일 심볼 / 단일 타임프레임 / 단일 전략**: 기본 `BTC-USDT-SWAP` `1h` `rsi-mr`.
  (CLI 옵션으로 바꿀 수 있지만 한 프로세스는 하나만 돈다.)
- **닫힌 봉 단위 의사결정 (closed-bar model)**: 새로 닫힌 봉이 생길 때만 판단.
  봉 내부 틱 단위 판단 안 함 → Week 2 엔진을 그대로 재사용하기 위한 핵심 결정.
- **가상 주문 체결**: 실제 거래소 주문 없음. Week 2 `costs`(수수료/슬리피지/funding)로
  체결을 시뮬레이션. 진입은 그 봉 종가 기준, 청산은 `check_exits`가 판정.
- **서킷 브레이커 (일일 -5% 정지)**: 하루(UTC) 실현 손익이 그날 시작 자본의 -5%에 닿으면
  **신규 진입을 차단**(킬 스위치의 자동 버전). 보유 포지션의 손절·익절은 유지.
- **panic 킬 스위치**: 즉시 전 포지션 청산(마지막 가격) + 정지 플래그. 수동 비상정지.
- **재시작 안전 상태(restart-safe)**: 모든 상태를 SQLite에 영속화. 프로세스가 죽어도
  tmux/systemd가 재시작하면 포지션·자본·정지여부·마지막 처리 봉을 그대로 복구.
- **CLI**: `paper`(루프 시작), `paper-status`(현재 상태), `panic`(비상정지), `paper-logs`(거래 로그).

### Out of scope (이번엔 안 한다 — YAGNI / 실거래 전 숙제)
- **부분 체결 시뮬레이션 (partial-fill)**: CUT. 백테스트처럼 시뮬 가격에 **전량 체결**로 가정.
  소액·저빈도 전략에 부분체결 모델은 과한 복잡도. (실거래 때 실제 체결로 대체됨.)
- **다중 심볼 / 다중 전략 동시 운용**: 한 프로세스 = 한 전략. 멀티는 post-MVP.
- **실제 거래소 주문 / 주문 정합성 대조(reconcile)**: 페이퍼엔 실주문이 없으므로 대조할
  대상이 없음 → CUT. (실거래 때 도입.)
- **커스텀 프로세스 슈퍼바이저**: 안 만든다. tmux / systemd 사용법만 문서화.
- **봉 마감 정밀도(confirm 필드)·funding 보유구간 정산·equity 곡선 funding 반영·gap 자동
  재수집**: 모두 `TODOS.md`의 **pre-live blocker**로 이미 등록됨. 페이퍼는 $0라 영향이 작아
  Week 3에서 고치지 않고, 실거래 전에 처리. (이 스펙이 새로 만드는 빚은 없음 — 기존 빚 승계.)
- **equity 곡선 테이블 / Sharpe·MaxDD 산출**: Week 4 validate 단계로 미룸. Week 3는 거래
  로그(`paper_trades`) + 상태의 현재 equity만 영속화(테이블 최소화 원칙).

---

## 3. 아키텍처 개요

```
┌─────────────────────────── paper/trader.py (새 루프) ───────────────────────────┐
│  매 틱:                                                                          │
│   1) collect_ohlcv(...)        ← Week 1 수집기 재사용 (OKX 폴링 → SQLite upsert)   │
│   2) load_candles_df(...)      ← Week 2 data_loader 재사용 (최신 닫힌 봉 읽기)     │
│   3) check_exits(pos, bar,...) ← Week 2 엔진 재사용 (손절/분할익절, 손절먼저)      │
│   4) generate_signal(window,…) ← Week 2 전략 재사용 (RsiMeanReversion/IStrategy)  │
│   5) should_halt(...) 게이트    ← 새 circuit_breaker (일일 -5% 차단)              │
│   6) open_position(...)        ← Week 2 엔진 재사용 (사이징/청산가드/익절타겟)     │
│   7) costs(fee/slippage/funding)← Week 2 costs 재사용                            │
│   8) store.save_state / append_trade ← 새 store (SQLite 영속)                    │
│   9) sleep → 반복                                                                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 재사용 (새 로직 없음 — 그대로 import)
| 재사용 대상 | 모듈 | 페이퍼에서의 역할 |
|---|---|---|
| `check_exits(pos, bar, fee_bps, slippage_bps, ct_val)` | `backtest.engine` | 봉마다 손절/분할익절 판정 — **백테와 동일** |
| `open_position(side, bar, stop, capital, ...)` | `backtest.engine` | 진입 합성(사이징→청산가드→익절타겟→Position) — **백테와 동일** |
| `IStrategy` / `RsiMeanReversion.generate_signal(window, open_position)` | `strategy.*` | 신호 생성 |
| `calculate_position_size` / `assert_stop_within_liquidation` / `build_targets` | `risk.*` | 진입 안전·사이징(5% 불변식, 슬리피지 포함) |
| `apply_slippage` / `fee_for` / `funding_between` | `backtest.costs` | 체결가·수수료·funding |
| `Position` / `Fill` / `Trade` | `backtest.models` | 포지션·체결·거래 표현 |
| `collect_ohlcv` (+`upsert_instruments`) | `data.collector` | 실시간 OKX 폴링 → SQLite |
| `load_candles_df` | `backtest.data_loader` | 최신 닫힌 봉 윈도우 읽기 |
| `Settings` / `_session()` 패턴 | `config` / `cli` | DB 세션·설정 |

> **엔진 진입 함수 공유 (작은 수술):** 현재 진입 합성은 `engine._open_position`(private,
> 배치 루프에 결합)에 있다. "백테=실전 일치"를 **글자 그대로** 보장하려면 백테와 페이퍼가
> *같은 함수*를 호출해야 한다. 따라서 `_open_position`을 공개 `open_position`으로 승격
> (시그니처 동일, 선행 언더스코어만 제거)하고 `run_backtest`의 호출부 1곳을 갱신한다.
> Week 2 로직은 변하지 않으며(순수 리네이밍), 기존 엔진 테스트가 회귀 가드. 페이퍼는 이걸
> import해서 동일하게 호출 → 진입 사이징/슬리피지/익절타겟이 백테와 비트 단위로 같다.

### 새로 만드는 컴포넌트 (4개)
1. **`paper/store.py`** — SQLite 영속(상태 + 거래 로그). 테이블 2개. (§5)
2. **`paper/trader.py`** — 틱 루프(폴링 → 봉 → 엔진 → 게이트 → 영속). (§4, §6)
3. **`risk/circuit_breaker.py`** — 순수 함수(일일 -5% 정지 판정 + UTC 일자 리셋). (§7)
4. **CLI 명령** (`cli.py`에 추가) — `paper` / `paper-status` / `panic` / `paper-logs`. (§8)

각 컴포넌트는 한 가지 책임만 갖고 인터페이스가 명확해 독립 테스트 가능(설계 원칙).
`store`는 I/O만, `circuit_breaker`는 순수 판정만, `trader`는 조립(orchestration)만,
엔진/리스크/costs는 손대지 않는다(엔진 진입 함수 리네이밍 1건 제외).

---

## 4. 한 틱(tick)의 데이터 흐름

매 틱은 다음을 순서대로 수행한다. **체결분은 즉시 equity에 실현**한다(Week 2에서 고친 그 불변식 —
부분익절 실현손익을 미루면 곡선이 가짜로 흔들림).

1. **폴링**: `collect_ohlcv(session, client, symbol, timeframe, days=N, now_ms=…)`
   — OKX에서 최신 봉을 받아 SQLite에 upsert. 수집은 워터마크(증분)라 정상 운영 땐 `days`가
   작아도(예: 2) 마지막 적재분 이후만 받는다. **단, 첫 실행(빈 DB)에서는 전략 `lookback`
   윈도우를 채울 만큼 충분한 `days`가 필요** → `paper` 명령은 시작 시 DB에 닫힌 봉이
   `lookback` 미만이면 한 번 더 넓게 수집하거나 안내한다. Week 1 `drop_unclosed`가 아직 안 닫힌
   봉을 버려 **닫힌 봉만** 들어온다(봉 마감 추정은 벽시계 기준 — 정밀도는 pre-live TODO).
2. **최신 닫힌 봉 읽기**: `load_candles_df(...)`로 최근 윈도우(전략 `lookback`+여유)를 읽는다.
3. **중복 방지**: 최신 닫힌 봉 ts == `last_processed_bar_ts`면 새 봉 없음 → 바로 sleep.
   (재시작·중복 폴링에도 한 봉을 두 번 처리하지 않음.)
4. **새로 닫힌 봉 처리**(보통 1개. 다운타임이 있었으면 여러 개를 순서대로 backfill):
   각 봉 `bar`에 대해 —
   a. **UTC 일자 경계 확인**: 이전 처리 봉과 다른 UTC 날짜로 넘어갔으면 일일 카운터 리셋
      (`day_start_equity = 현재 equity`, `daily_realized_pnl = 0`, `halted` 해제). (§7)
   b. **보유 포지션 청산 판정**: `position`이 있으면 `check_exits(position, bar, fee_bps,
      slippage_bps, ct_val)`. 체결(fills)이 나오면 즉시
      `equity += Σpnl_gross − Σfee`, `daily_realized_pnl`에도 누적. 완전 청산되면
      `funding_between(...)`로 funding 차감 → `paper_trades`에 거래 기록 → 포지션 비움.
   c. **신호 생성**: `window`(=`candles.iloc[i-lookback+1 : i+1]`)로
      `strategy.generate_signal(window, position)`.
   d. **신호 처리**:
      - `long`/`short` & 포지션 없음 → **서킷 브레이커 게이트**(`should_halt`).
        차단 상태면 진입 스킵(사유 로그). 아니면 `open_position(...)`로 진입,
        `equity -= open_fee`, 상태 저장.
      - `exit` & 포지션 있음 → 그 봉 종가에 전량 청산(시뮬), 즉시 실현 + funding + 거래 기록.
   e. **상태 갱신**: `last_processed_bar_ts = bar.ts`, `store.save_state(...)`.
5. **sleep**: 다음 봉 경계까지(또는 `--poll-seconds` 간격) 대기 → 1로 반복.

**look-ahead 아님:** 신호는 *닫힌* 봉의 OHLC로 계산되고 진입은 그 봉 종가에 체결된다(미래
데이터 미사용). 이는 Week 2 엔진의 market-on-close 모델과 동일하다.

---

## 5. 영속 상태 / 스키마 (테이블 2개 — 최소화)

새 테이블·관계는 꼭 필요한 것만(CLAUDE.md). 재시작 복구와 거래 감사에 필요한 최소 집합.

### `paper_state` — 단일 행(현재 런의 상태 스냅샷)
재시작 시 이 한 행으로 정확히 복구된다. (WHY: 프로세스가 죽어도 포지션/자본/정지/진행위치를
잃지 않아야 페이퍼가 "끊김 없이" 도는 것처럼 보인다.)

| 컬럼 | 의미 |
|---|---|
| `id` | 단일 행 키(예: `run_key` = symbol+timeframe+strategy) |
| `symbol`,`timeframe`,`strategy` | 이 런의 대상 |
| `equity` | 현재 실현 자본(USDT) |
| `day_start_equity` | 오늘(UTC) 시작 시점 자본 — 서킷 브레이커 기준선 |
| `day_start_ts` | 오늘 UTC 자정 경계(리셋 판정용) |
| `daily_realized_pnl` | 오늘 실현 손익 누적(서킷 브레이커 입력) |
| `halted` | 정지 플래그(panic 또는 서킷 브레이커가 set) |
| `last_processed_bar_ts` | 마지막으로 처리한 닫힌 봉 ts(중복 방지·재개 지점) |
| **포지션 필드**(열려 있을 때) | `pos_side`, `pos_entry`, `pos_contracts`, `pos_original_contracts`, `pos_stop`, `pos_targets_remaining`(JSON: `[[price,frac],...]`), `pos_opened_ts`, `pos_open_fee`. 포지션 없으면 NULL. |

> 포지션을 별도 테이블로 정규화하지 않는 이유: 한 번에 **포지션은 최대 1개**(단일 심볼/전략)
> 라서 상태 행에 인라인하는 게 가장 단순하고 복구도 원자적. `targets_remaining`만 JSON 직렬화.

### `paper_trades` — 청산된 거래 로그(append-only)
Week 2 `Trade`의 영속 버전. `paper-status`/`paper-logs` 보고와 Week 4 validate(지표) 입력.

| 컬럼 | 의미 |
|---|---|
| `id` | PK |
| `side`,`entry`,`exit`,`contracts` | 거래 요약 |
| `pnl_gross`,`fees`,`funding`,`pnl_net` | 손익 분해 |
| `opened_ts`,`closed_ts`,`reason` | 시점·청산 사유(stop/tp_n/exit_signal/panic) |

### store API (I/O만, 순수 영속)
- `load_state(session, run_key) -> PaperState`  (없으면 자본=초기값인 fresh 상태)
- `save_state(session, state) -> None`  (upsert, 원자적)
- `append_trade(session, run_key, trade: Trade) -> None`
- `recent_trades(session, run_key, n) -> list[Trade]`

---

## 6. `paper/trader.py` — 루프 조립

- 입력: `symbol, timeframe, strategy, capital, leverage, poll_seconds`, OKX client, session factory.
- 책임: **조립만**. 매매 판단은 엔진/전략, 정지 판단은 circuit_breaker, 영속은 store에 위임.
- 공개 함수(테스트 가능하게 잘게):
  - `run_one_tick(ctx) -> TickResult` — §4의 1틱. **순수에 가깝게**: 봉을 인자로 주입할 수
    있어 결정적 테스트 가능(폴링/슬립과 분리).
  - `run_loop(ctx)` — `run_one_tick`을 sleep과 함께 무한 반복(얇은 래퍼, 직접 테스트 X).
  - `panic_close(ctx, last_price) -> Trade | None` — 보유 포지션을 last_price에 전량 청산 +
    `halted=True` 저장. CLI `panic`이 호출. (§8)
- ct_val/lot_sz는 Week 2처럼 `Instrument` 캐시에서 조회(없으면 안내 에러).

---

## 7. `risk/circuit_breaker.py` — 순수 함수

WHY 순수 함수: I/O·시계 의존 없이 인자만으로 판정 → 경계값 테스트가 자명하고 결정적.

- `should_halt(day_start_equity: float, daily_realized_pnl: float, threshold: float = 0.05) -> bool`
  - `daily_realized_pnl <= -threshold * day_start_equity` 면 `True`.
  - 의미: **하루 실현 손익이 그날 시작 자본의 -5%에 닿으면 신규 진입 차단.**
  - 보유 포지션의 손절/익절은 막지 않는다(이미 5% 불변식으로 리스크 한정). 차단은 *새 베팅*만.
- `is_new_utc_day(prev_ts_ms: int, cur_ts_ms: int) -> bool`
  - 두 ts가 서로 다른 UTC 날짜면 `True` → trader가 일일 카운터·halt 리셋.
  - WHY UTC: funding·거래소 일일 경계가 UTC. 로컬 타임존 의존 제거(결정적).

서킷 브레이커는 `paper_state.halted`로 영속되고, panic도 같은 플래그를 공유한다(한 메커니즘).
UTC 자정에 리셋되어 다음 날 다시 매매 가능.

---

## 8. CLI 명령 (`cli.py`에 추가, 기존 `_session()`·`STRATEGIES` 재사용)

- **`paper`** — 페이퍼 루프 시작(포그라운드, 재시작 안전).
  옵션: `--symbol`(BTC-USDT-SWAP) `--timeframe`(1h) `--strategy`(rsi-mr) `--capital`(1000)
  `--leverage`(3) `--poll-seconds`(예: 60). 시작 시 `load_state`로 이어받고, 없으면 새로 시작.
- **`paper-status`** — 현재 상태 출력(읽기 전용): equity, 보유 포지션(있으면), 오늘 실현 PnL,
  halted 여부, 마지막 처리 봉, 최근 거래 수.
- **`panic`** — 비상정지: `halted=True` + 보유 포지션 즉시 전량 청산. 청산 가격(last price)은
  **DB의 최신 닫힌 봉 종가**를 사용(페이퍼는 실주문이 없어 그게 가장 최근 관측가). 실행 중인
  루프와 **상태 플래그를 공유**하므로, 루프가 다음 틱에서 정지를 존중하고 panic 자체도 청산을
  즉시 수행·영속. (옵션: `--symbol/--timeframe/--strategy`로 run_key 지정.)
- **`paper-logs`** — 최근 `paper_trades` N개 출력(감사). 옵션 `--limit`(기본 20).

---

## 9. 테스트 전략 (TDD: RED → GREEN → commit)

수학·금융 로직은 손으로 검증 가능한 결정적 테스트로 덮는다. 봉을 주입해 시계/네트워크와 분리.

1. **circuit_breaker (순수)**:
   - `should_halt` 경계: -5% 바로 위(차단 안 됨)/정확히 -5%(차단)/아래(차단).
   - `is_new_utc_day`: 같은 날(False), 자정 직후(True), 여러 날 점프(True).
2. **store 라운드트립**:
   - `save_state` → `load_state` 동일 복원(포지션 있음/없음 둘 다, `targets_remaining` JSON 포함).
   - 빈 DB `load_state` → 초기 자본 fresh 상태.
   - `append_trade` → `recent_trades` 순서/내용 일치.
3. **trader 1틱(`run_one_tick`)**:
   - 포지션 없음 + 진입 신호 봉 → 포지션 개설 + `open_fee` 차감 + 상태 저장.
   - 포지션 있음 + 손절 터치 봉 → 청산, `paper_trades` 1건, equity 즉시 실현.
   - 같은 봉 재처리(ts==last) → 무동작(중복 방지).
4. **서킷 브레이커 게이트(루프 통합)**:
   - `daily_realized_pnl`이 -5% 이하인 상태에서 진입 신호 → **진입 차단**(포지션 안 생김),
     보유 포지션은 계속 손절/익절 관리됨.
   - UTC 자정 넘는 봉 → 카운터·halt 리셋 후 진입 재개.
5. **panic**:
   - 보유 포지션 + `panic_close(last_price)` → 포지션 flat, `halted=True`,
     `paper_trades`에 `reason="panic"` 1건(last_price 기준 손익).
6. **재시작 복구**:
   - 포지션 보유 상태 저장 → 새 trader 인스턴스 `load_state` → 포지션·equity·`last_processed_bar_ts`
     동일. 이어서 틱 처리 시 중복 없이 재개.
7. **parity (백테=실전 일치 — 핵심 검증)**:
   - 스크립트된 봉 시퀀스를 ① `run_backtest`에 통째로, ② `run_one_tick`을 봉마다 순차로 먹였을 때
     **거래(side/entry/exit/reason)와 최종 equity가 일치**. 둘이 갈리면 재사용이 깨진 것 →
     이 테스트가 회귀 가드. (funding 이벤트 없는 깨끗한 케이스로 시작.)

리스크 불변식은 사이징에서 이미 `assert`로 강제(슬리피지 포함). 페이퍼는 같은 사이징을 쓰므로
실현 손실이 5% 예산을 넘지 않는다 — parity/1틱 테스트가 간접 확인.

---

## 10. 에러 처리 / 운영

- **폴링 실패**: Week 1 수집기 내부 재시도 후에도 실패하면 그 틱을 로그 남기고 **스킵**.
  루프는 죽지 않고 다음 틱에서 재시도(닫힌 봉은 불변이라 한 틱 놓쳐도 다음에 따라잡음).
- **프로세스 크래시**: tmux/systemd가 재시작 → `load_state`로 포지션·자본·halt·마지막 봉 복구 →
  `last_processed_bar_ts` 중복 방지로 안전하게 재개.
- **단일 writer 가정**: 페이퍼 루프가 유일한 DB writer(Week 1과 동일 가정). `panic`은 짧은
  쓰기 1회(플래그+청산)라 실무상 충돌 없음. (멀티 writer는 out of scope.)
- **봉 마감 정밀도**: Week 1 `drop_unclosed`(벽시계 기준)에 의존. OKX `confirm` 필드 기반 정밀
  판정은 `TODOS.md` pre-live blocker로 이미 등록 — 페이퍼($0)에선 한 봉 지연 허용.
- **운영(프로세스 관리)**: 커스텀 슈퍼바이저 없음. README/스펙에 tmux(`tmux new -s paper →
  quantpilot paper`)와 systemd 유닛 예시를 문서화. 재시작 안전성은 상태 영속으로 보장.

---

## 11. 다음 단계 연결 (Week 4)

- **하드닝**: 로깅 강화, 엣지케이스, (필요 시) confirm-field 봉 마감 등 pre-live 항목 착수.
- **7일 페이퍼런**: 이 루프를 tmux/systemd로 7일 가동 → `paper_trades` + 라이브 데이터 축적.
- **validate**: 축적된 거래/equity로 Sharpe·MaxDD 등 지표 산출(이때 equity 곡선 테이블 필요 시 추가).
- 실거래(Week 5+)는 `TODOS.md`의 **pre-live blocker**를 전부 처리한 뒤에만.

---

## 부록 A — 재사용 vs 신규 한눈에

| | 재사용(그대로) | 신규(이번 Week) |
|---|---|---|
| 매매 판단 | `check_exits`, `generate_signal` | — |
| 진입 합성 | `open_position`(엔진, private→public 승격) | — |
| 리스크 | `calculate_position_size`, `assert_stop_within_liquidation`, `build_targets` | `circuit_breaker`(일일 정지) |
| 비용 | `apply_slippage`, `fee_for`, `funding_between` | — |
| 데이터 | `collect_ohlcv`, `load_candles_df` | — |
| 모델 | `Position`, `Fill`, `Trade` | — |
| 영속 | (Week 1 DB 세션) | `paper_state`, `paper_trades` 테이블 + `store` |
| 루프 | — | `paper/trader.py` |
| CLI | `_session()`, `STRATEGIES` | `paper`/`paper-status`/`panic`/`paper-logs` |
