# Week 4 — 하드닝 + 측정 + 7일 페이퍼런 설계

작성일: 2026-06-08
상태: 설계 승인됨(스코프=포커스) → 구현 대기 (worktree + plan 단계로 진행)

---

## 1. 목적 / 배경

Week 3 페이퍼 트레이더를 **7일 무인 가동에 안전하게** 만들고, 그 결과를 **Week 2 백테와 동일한
지표로 측정 가능하게** 한 뒤, **7일 런을 시작**한다. 이게 MVP 로드맵의 마지막 검증 관문이다
(data→backtest→paper→**validate**→실거래 Week 5+).

### "7일 런"은 실시간이다 (프레이밍)
7일 페이퍼런은 **벽시계 7일**이 걸린다. 따라서 이 spec이 다루는 **빌드 산출물은 하드닝 +
측정 도구 + 런 셋업**이고, 실제 런·최종 검증은 그 뒤 시간이 지나며 운영으로 진행된다:
1. **빌드(이 spec):** 무인 안전 하드닝 + equity 측정 파이프라인 + 런 스크립트.
2. **운영:** tmux/systemd로 7일 런 시작 → 실제 페이퍼 거래·equity 축적.
3. **검증:** `paper-report`로 Sharpe/MaxDD/승률 측정 → Week 5(실거래) 게이트 판단.

### 무엇을 검증하나 (중요)
`rsi-mr`은 **수익 주장이 아니라 인프라 검증용 베이스라인**(strategy docstring). 그래서 7일 런이
검증하는 건 **"시스템이 7일간 안 죽고 정확히 기록·측정하는가"**(신뢰성 + 측정 파이프라인)이지,
"rsi-mr이 돈을 버는가"가 아니다. 진짜 엣지 발굴(더 나은 전략)은 이후 사이클.

### 리스크 게이트(불변)
**실거래(진짜 돈)는 Week 5+ 전까지 절대 없음.** Week 4도 전부 $0 페이퍼.

---

## 2. 스코프

### In scope (이번 Week에 빌드)
1. **킬스위치가 *도는 루프*를 멈춤** — `run_loop`이 매 틱 DB의 `halted`를 재확인. 외부 `panic`이
   세운 정지를 감지하면 상태를 DB에서 재로드(panic의 청산 결과 동기화)하고 루프를 정지.
2. **파일 로깅** — 매 틱(처리 봉·신호·거래·equity·에러)을 회전 파일 로그 + 콘솔에 기록.
3. **equity 곡선 기록 + `paper-report`** — `paper_equity` 테이블 1개 추가(봉마다 기록), `paper-report`
   CLI가 **Week 2 `metrics`/`report`를 재사용**해 Sharpe/MaxDD/총수익/승률/PF 출력.
4. **7일 런 셋업** — `scripts/run-paper.sh` + Week 3 tmux/systemd 문서 → 런 시작.

### Out of scope (deferred 유지 — TODOS.md)
- **JSON 역직렬화 방어**(스키마 진화 robustness) — Week 5 전.
- **panic 시 funding 정산** — Week 5 전.
- **confirm 필드 봉마감 정밀도** — Week 5 실거래 전 blocker.
- **다중 심볼/전략, 실주문, reconcile** — post-MVP.
- 위 3개를 지금 당기지 않는 이유: 전부 *실거래($)* 정확도/안전 항목이라 $0 페이퍼 7일 런의
  신뢰성·측정에는 영향이 작다. Week 5 진입 시 일괄 처리.

---

## 3. 아키텍처 개요

```
run_loop (하드닝)                         paper_equity (신규 테이블)
  매 틱:                                    run_key, ts, equity(실현+미실현)
   0) DB halted 재확인 ───┐                       ▲
      외부 panic 감지 시   │                       │ 봉마다 append
      → 상태 재로드 → 정지 │                paper-report (신규 CLI)
   1) run_one_tick ───────┼──► 봉마다 equity 기록 ─┘   = load_equity_curve + paper_trades
      (기존 + equity 기록) │                            → Week 2 compute_metrics 재사용
   2) 파일 로그 ──────────┘                            → Sharpe/MaxDD/총수익/승률/PF 출력
   3) sleep
```

### 재사용 (그대로)
| 재사용 | 모듈 | 용도 |
|---|---|---|
| `compute_metrics(curve, trades, ppy)` / `periods_per_year` | `backtest.metrics` | paper-report 지표 계산 — **백테와 동일 지표** |
| `format_console(...)`(또는 일부) | `backtest.report` | 콘솔 출력 포맷 |
| `process_bar` / `run_one_tick` / `panic_close` | `paper.trader` | 기존 틱 로직(여기에 equity 기록 + halt 재확인만 추가) |
| `PaperState` / `load_state` / `persist_tick` | `paper.store` | 상태/영속(equity append 추가) |
| `_pnl(side, entry, price, contracts, ct_val)` | `backtest.engine` | 봉별 미실현 계산(equity 곡선용) |

### 신규/변경
1. **`paper/models.py`** — `PaperEquityRow` 테이블 추가(run_key, ts, equity). (테이블 1개만 추가.)
2. **`paper/store.py`** — `append_equity(session, run_key, ts, equity)` + `load_equity_curve(session, run_key)`.
   `persist_tick`이 equity 포인트도 같은 트랜잭션에 기록(원자성 유지).
3. **`paper/trader.py`** — (a) `run_one_tick`이 봉마다 equity(실현+미실현) 기록, (b) `run_loop`이
   매 틱 DB `halted` 재확인 → 외부 panic 감지 시 상태 재로드 후 정지, (c) 로깅 호출.
4. **`paper/logsetup.py`**(신규, 작게) — `logging` + `RotatingFileHandler` 설정 함수.
5. **`cli.py`** — `paper-report` 명령 추가, `paper` 명령에 로깅 와이어링.
6. **`scripts/run-paper.sh`**(신규) — 수집→`quantpilot paper` 런처. README에 운영 절차.

---

## 4. 컴포넌트 상세

### 4a. 킬스위치가 도는 루프를 멈춤 (안전 핵심)
**문제(Week 3 /review 발견):** `run_loop`은 in-memory `state`를 들고 돌고, `quantpilot panic`은
별도 프로세스로 SQLite만 갱신한다. 루프는 그 행을 다시 안 읽으므로 panic이 *도는 루프*를 못 멈춘다.

**설계:** `run_one_tick` 시작에 DB의 `halted`만 가볍게 재조회(`session.get(PaperStateRow, run_key).halted`).
- 외부에서 `halted=True`로 바뀐 게 감지되면(=in-memory는 False인데 DB는 True): **DB에서 전체 상태를
  재로드**(panic이 포지션을 청산·정지시킨 결과를 in-memory에 동기화) 후 `run_loop`에 "정지" 신호 반환.
- `run_loop`은 그 신호를 받으면 로그 남기고 루프 종료(또는 idle). **킬스위치 = 멈춤** 의미 충족.
- WHY 재조회가 싸다: PK 단건 조회 1회/틱(1h 봉이면 분당 1회 미만). 무시 가능한 비용으로 무인
  런의 안전을 보장.

> 이 변경은 Week 3 /review의 in-memory-vs-DB divergence robustness도 함께 해결한다.

### 4b. 파일 로깅
- `paper/logsetup.py`: `setup_paper_logger(run_key) -> logging.Logger`. RotatingFileHandler
  (`logs/paper-{run_key 안전화}.log`, maxBytes·backupCount 설정) + StreamHandler(콘솔).
- `run_one_tick`/`run_loop`/`panic_close` 경로의 stderr `print`를 logger 호출로 교체:
  틱 시작, 처리 봉 수, 신호, 진입/청산 거래, equity, 정지/에러를 INFO/WARNING으로 기록.
- WHY: 7일 무인 런은 "무슨 일이 있었나"를 사후 리뷰할 로그가 없으면 디버깅 불가.
- `logs/`는 gitignore.

### 4c. equity 곡선 기록
- **`PaperEquityRow`**(테이블 1개): `id, run_key, ts(BigInteger ms), equity(Float)`.
  **`UNIQUE(run_key, ts)`** + append는 conflict 무시(idempotent) — 재시작 재처리 시 같은 봉
  equity가 중복 적재되지 않음(Week 1 캔들 upsert와 동일 패턴). report 조회는 ts 정렬.
- **봉별 equity = 실현 + 미실현**(Week 2 `equity_curve`와 동일 의미): 처리한 각 봉에서
  `equity_point = state.equity + (_pnl(pos.side, pos.entry, bar.close, pos.contracts, ct_val) if 포지션 else 0)`.
  WHY 미실현 포함: 보유 중 drawdown이 곡선에 반영돼야 MaxDD/Sharpe가 백테와 같은 의미.
- `store.append_equity`로 기록하되 **`persist_tick`이 거래+상태+equity를 한 트랜잭션**에 커밋
  (Week 3 원자성 유지 — 재시작 중복/유실 방지). `run_one_tick`이 처리한 봉마다 equity 포인트를
  모아 `persist_tick`에 함께 넘긴다(시그니처에 `equity_points` 인자 추가).
- **처리하는 결정 봉(lookback 이후)마다 기록** — 거래가 아직 없어도 그 봉의 equity(=자본,
  flat)를 남긴다. WHY: MaxDD/Sharpe는 거래 전 flat 구간 포함 전체 곡선이 있어야 정확.
  warmup 봉(lookback 미만)·빈 DB는 기록 없음.
- **중복 방지**: 같은 ts는 1회만(재시작 재처리 시 `(run_key, ts)` 유니크 또는 append 전 dedup).

### 4d. `paper-report` CLI (백테=페이퍼 측정 일치)
- `quantpilot paper-report --symbol --timeframe --strategy`:
  1. `load_equity_curve(run_key)` → `[(ts, equity), ...]`.
  2. `recent_trades(run_key, 큰 N)` → 거래 리스트.
  3. `ppy = periods_per_year(timeframe)`(Week 2 재사용).
  4. `metrics = compute_metrics(curve, trades, ppy)`(Week 2 재사용 — **백테와 동일 함수**).
  5. 콘솔 출력: 총수익률, Sharpe, MaxDD, 거래 수, 승률, PF, 기간(첫~마지막 ts).
- equity 곡선이 없으면(아직 런 안 함) 안내 메시지. WHY 재사용: 페이퍼 성과를 백테와 *같은 잣대*로
  봐야 "백테=실전 일치"가 지표 레벨까지 닫힌다.

### 4e. 7일 런 셋업
- **`scripts/run-paper.sh`**: (1) `quantpilot collect`(+`collect-funding`)로 데이터 시드 →
  (2) `quantpilot paper --symbol ... --timeframe 1h --strategy rsi-mr --poll-seconds N` 실행.
  실행 전 Instrument/캔들 존재를 보장(첫 런 warmup).
- README "7일 런" 절차: `tmux new -s paper` → `scripts/run-paper.sh` → detach. 중간 점검은
  `quantpilot paper-status`/`paper-logs`/`paper-report`, 비상정지는 `quantpilot panic`(이제 도는
  루프도 멈춤). systemd 유닛은 Week 3 README 예시 사용.
- 런 **시작 자체는 운영 단계**(사용자가 트리거하거나 함께 띄움) — 7일 소요.

---

## 5. 한 틱(tick) 변화 (Week 3 대비)

```
run_one_tick(ctx, state):
  0) [신규] DB halted 재확인 → 외부 True 감지 시 load_state로 재로드 후 (state, [], STOP) 반환
  1) (client 있으면) collect_ohlcv  ← 기존
  2) load_candles_df               ← 기존
  3) 새 봉마다 process_bar          ← 기존
     [신규] 각 봉 처리 후 equity_point(실현+미실현) 누적
  4) persist_tick(거래 + 상태 + [신규]equity 포인트들)  ← 한 트랜잭션(원자성 유지)
  [신규] 로깅: 처리 봉/거래/equity/정지
run_loop:
  while True: state, trades, stop = run_one_tick(...); if stop: log+break; sleep
```

---

## 6. 테스트 전략 (TDD)

1. **킬스위치 on loop**: 상태 저장(포지션 보유) → 별도로 DB `halted=True`로 set →
   `run_one_tick` 호출 시 STOP 신호 + state가 재로드(halted=True, 포지션은 panic 결과 반영)됨.
2. **equity 기록**: `run_one_tick` 후 `load_equity_curve`가 처리 봉 수만큼 포인트 반환, 각
   포인트 equity == 그 봉의 실현+미실현. 원자성: 거래와 equity가 같은 커밋(재시작 시 일관).
3. **paper-report 지표**: 알려진 equity 곡선 + 거래 → `compute_metrics` 결과가 기대 Sharpe/MaxDD와
   일치(Week 2 metrics 테스트 스타일 재사용). 빈 곡선 → graceful.
4. **CLI paper-report**: 빈 DB graceful + 시드 후 출력에 핵심 지표 포함.
5. **로깅**: `setup_paper_logger`가 핸들러 구성, 로그 1줄이 파일에 기록됨(가벼운 검증).
6. **회귀**: 기존 120 테스트 + parity 그대로 통과(equity 기록/halt 재확인이 거래 로직 불변).

리스크 불변식·parity는 Week 3 그대로 유지(이번 변경은 측정·안전 레이어, 매매 판단 불변).

---

## 7. 운영 — 7일 런 시작 방법 (빌드 후)
1. `tmux new -s paper`
2. `./scripts/run-paper.sh`(수집 → paper 루프). detach: `Ctrl-b d`.
3. 점검: `quantpilot paper-status` / `paper-logs` / `paper-report`.
4. 비상정지: `quantpilot panic`(별도 셸) → 도는 루프가 다음 틱에 감지·정지.
5. 7일 후: `quantpilot paper-report`로 최종 지표 → Week 5 게이트 판단.

---

## 8. Week 5 연결
- 7일 런 신뢰성·지표 확인 후, **실거래 전 blocker(TODOS.md pre-live)** 일괄 처리:
  confirm 필드 봉마감, panic funding, JSON 방어, funding 보유구간 정산 등.
- 그 뒤에야 소액 실거래(진짜 돈) 진입. 그 전까진 전부 $0.

---

## 부록 — 재사용 vs 신규 한눈에
| | 재사용 | 신규 |
|---|---|---|
| 지표 | `compute_metrics`/`periods_per_year`/`format_console` | `paper-report` CLI |
| 매매 | `process_bar`/`panic_close`(불변) | — |
| 영속 | `PaperState`/`persist_tick` | `PaperEquityRow` + `append_equity`/`load_equity_curve` |
| 루프 | `run_one_tick`/`run_loop`(+halt 재확인·equity 기록) | — |
| 운영 | Week 3 tmux/systemd 문서 | `scripts/run-paper.sh`, `logsetup.py` |
