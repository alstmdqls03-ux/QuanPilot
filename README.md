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
