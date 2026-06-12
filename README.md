# QuantPilot — 백테스트 엔진 (Week 1–2)

OKX 시장 데이터(가격 캔들 + funding rate)를 로컬 SQLite에 적재하고(Week 1),
그 데이터에 전략을 돌려 train/OOS 성과를 측정하는(Week 2) CLI.
public 데이터만 쓰므로 **API 키가 필요 없습니다**.

## 설치
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## 사용
```bash
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 365
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 15m --days 365
quantpilot collect-funding --symbol BTC-USDT-SWAP --days 365
quantpilot status
```

수집은 idempotent 증분입니다 — 다시 실행하면 새 데이터만 이어붙고 중복은 무시됩니다.

## 백테스트 (Week 2)
```bash
quantpilot backtest --strategy rsi-mr --symbol BTC-USDT-SWAP \
    --timeframe 1h --oos-months 2 --capital 1000
# → Train/OOS Sharpe·MaxDD·승률 표 + equity curve PNG
```
- 데이터의 마지막 `--oos-months` 개월은 **OOS(out-of-sample)** 로 분리해 과최적화를 드러냅니다.
- 비용(수수료·funding·slippage)을 차감한 **net** 기준이며, 한 봉이 손절·익절을 동시에
  건드리면 **손절 먼저** 체결로 가정해 백테스트 낙관 편향을 막습니다.
- `--allow-gaps` 없이는 데이터 구멍이 있으면 실행을 막습니다(연속 봉 가정 보호).
- 새 전략 추가 = `quantpilot/strategy/`에 `IStrategy` 구현 1개 + `cli.py`의 `STRATEGIES`에 1줄.

> baseline `rsi-mr`는 수익성 보장이 아니라 파이프라인 검증용입니다. OOS Sharpe가
> 음수로 나오면 "이 전략엔 edge가 없다"를 시스템이 정확히 말해주는 것입니다.

## confluence 전략 (BOT-SPEC 모드 A 코어)

차트패턴 강의(`00-자동매매봇-규칙명세서.md`)의 **근거 겹침 점수제**를 구현한 두 번째 전략.
한 자리에서 여러 시그널이 겹칠 때만 진입합니다.

```bash
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 4h --days 730 --heal   # 상위 TF
quantpilot backtest --strategy confluence --symbol BTC-USDT-SWAP \
    --timeframe 1h --htf 4h --oos-months 4
quantpilot backtest --strategy confluence --start-ms <ts> --end-ms <ts>      # walk-forward 분할
```

- **시그널(점수)**: 매물대 지지/저항(+2) · RSI 다이버전스(+2, 더블 +1) · 피보 0.5~0.618 존(+1) ·
  RSI 극단(+1) · 4h 동발 보너스(+2캡). **총점 ≥4 & 계열 ≥2**면 진입(리스크 2.5%), **≥6 & ≥3**이면
  강진입(5%). 게이트: 손익비 ≥1.5(G2), 직전 20봉 일방추세면 역추세 진입 차단(V1).
- **기반 모듈**(전부 직접 구현·룩어헤드-프리): `pivots`(ZigZag 확정 피벗) → `zones`(매물대) ·
  `divergence` · `fib`. `--htf`는 상위 TF를 **이미 마감된 봉만** 슬라이스해 주입(미래 정보 차단).
- **청산**은 Week 2 엔진 재사용: TP 사다리 50/40/10 + TP1 후 손절 본전 이동 + 손절. 백테=페이퍼
  일치(parity 테스트).
- gap 메우기: `collect --heal`로 기존 데이터의 누락 구간만 재수집(연속성 보장).

> ⚠️ **검증 결과(`docs/validation/confluence-v1.md`)**: BTC/ETH 1h 2년에서 **합격 못 함**.
> 기본 임계는 거래가 2년 3~8건뿐(표본 과소), 임계를 완화해 거래를 20+로 늘리면 PF가 1 근처로
> 수렴(엣지 없음). 전략 결함이 아니라 신호 희소성 — **미검증/잠정 음성**으로, 실거래 근거가
> 전혀 아닙니다. Phase 2(15m 진입·모드 B·채널)로 신호를 늘려 재검증해야 합니다.

## Week 3 — 페이퍼 트레이더

> 실거래(진짜 돈)는 Week 5+ 전까지 없음. 페이퍼는 **$0 리스크** 시뮬레이션.

### 사용법

```bash
# 1) 데이터 먼저 수집
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 365
quantpilot collect-funding --symbol BTC-USDT-SWAP --days 365

# 2) 페이퍼 루프 시작 (포그라운드, Ctrl-C 로 중단)
quantpilot paper --symbol BTC-USDT-SWAP --timeframe 1h --strategy rsi-mr \
    --capital 1000 --leverage 3 --poll-seconds 60

# 3) 상태 확인 (읽기 전용)
quantpilot paper-status

# 4) 최근 거래 로그
quantpilot paper-logs --limit 20

# 5) 비상정지 — 포지션 즉시 청산 + 신규 진입 차단
quantpilot panic
```

### 운영 — 재시작 안전

모든 상태(포지션·자본·정지여부·마지막 봉)가 SQLite(`paper_state` 테이블)에 저장됩니다.
크래시·재부팅 후 같은 명령으로 다시 실행하면 자동 복구됩니다.

**tmux 예시:**
```bash
tmux new -s paper
quantpilot paper --symbol BTC-USDT-SWAP --timeframe 1h --strategy rsi-mr
# Ctrl-b d 로 detach. 재접속: tmux attach -t paper
```

**systemd 유닛 예시** (경로·venv는 환경에 맞게):
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

### 한계 (실거래 아님)

- 실주문 없음 — 슬리피지·수수료는 파라미터로 시뮬레이션.
- 실거래 전 필수 숙제: `TODOS.md`의 **pre-live blocker** 섹션 참조.

---

## Week 4 — 7일 페이퍼런

> 실거래(진짜 돈)는 Week 5+ 전까지 없음.

### 빌드된 것

- **측정**: `paper-report` 명령이 Sharpe·MaxDD·승률·누적 PnL·총 거래수를 출력.
- **안전**: `panic` 킬스위치가 *도는 루프*도 멈춤 — 루프가 다음 틱에 halt 플래그를 읽어 자동 종료.
- **회전 파일 로깅**: `paper` 루프가 `logs/paper.log`에 기록 (10 MB × 5개 rotation).

### 런 시작

```bash
tmux new -s paper
./scripts/run-paper.sh
# Ctrl-b d 로 detach. 재접속: tmux attach -t paper
```

`run-paper.sh`는 30일치 캔들·funding을 먼저 시드한 뒤 페이퍼 루프를 시작합니다.
심볼·타임프레임·전략·폴 간격은 환경변수로 덮어쓸 수 있습니다:

```bash
SYMBOL=ETH-USDT-SWAP TIMEFRAME=15m STRATEGY=rsi-mr POLL=30 ./scripts/run-paper.sh
```

### 점검

```bash
quantpilot paper-status          # 현재 자본·포지션·브레이커 상태·정지 여부
quantpilot paper-logs --limit 20 # 최근 거래 이벤트
quantpilot paper-report          # Sharpe / MaxDD / 승률 요약
```

### 비상정지

루프가 실행 중인 상태에서 **다른 셸**에서:

```bash
quantpilot panic
```

루프가 다음 틱(최대 `--poll-seconds` 초)에 halt 플래그를 감지하고 자동 종료합니다.
재시작하면 halt 상태가 유지되므로, 원인을 확인한 뒤 DB에서 `halted = 0`으로 리셋해야 합니다.

### 7일 후

```bash
quantpilot paper-report
```

Sharpe·MaxDD·승률을 확인해 Week 5(실거래) 게이트 판단 기준으로 활용합니다.
(실거래 전 최소 기준은 `TODOS.md` pre-live blocker 섹션에 명시.)

### 한계

`TODOS.md`의 pre-live blocker 항목(confirm 주문 필드, panic 중 funding 미처리, JSON 방어 코드)은
Week 5 진입 전에 처리해야 합니다.

---

## 테스트
```bash
pytest             # 빠른 단위 테스트 (fixture 기반)
pytest -m live     # 실제 OKX 연결 확인 (인터넷 필요, 수동)
```

## 설계
- Week 1 Spec: `docs/superpowers/specs/2026-06-07-week1-data-foundation-design.md`
- Week 1 Plan: `docs/superpowers/plans/2026-06-07-week1-data-foundation.md`
- Week 2 Spec: `docs/superpowers/specs/2026-06-07-week2-backtest-engine-design.md`
- Week 2 Plan: `docs/superpowers/plans/2026-06-08-week2-backtest-engine.md`

## 웹 대시보드 (MINCODE)

페이퍼 런을 실시간으로 보는 로컬 웹 UI. 모의 데이터가 아니라 **돌고 있는 런의 SQLite를
2초 폴링**으로 읽는다 (지표·청산가·사이징 전부 실코드로 계산).

```bash
quantpilot dashboard            # http://127.0.0.1:8787
```

- 화면 3개: 대시보드(캔들+RSI 스트립·equity 곡선·서킷 게이지·TP 사다리·비용분해·라이브 로그),
  매매 로그(거래/체결/시스템 로그), 전략 설정(읽기 전용 — 변경은 루프 재시작).
- **비상정지 버튼은 진짜 킬스위치다** — CLI `quantpilot panic`과 동일 코드 경로
  (`quantpilot/paper/ops.py`). 클릭 → 3초 내 재클릭으로 확정.
- 127.0.0.1 바인딩 기본. 쓰기 엔드포인트(panic)가 있으므로 외부에 노출하지 말 것.
