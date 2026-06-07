# Spec: QuantPilot Week 2 — Backtest Engine + First Strategy + Sizing

Date: 2026-06-07
Status: APPROVED (brainstorming 완료, writing-plans 대기)
Parent design: `~/.gstack/projects/quantpilot/seungbinmin-main-design-20260606-042827.md` (전체 4주 MVP)
Predecessor: `docs/superpowers/specs/2026-06-07-week1-data-foundation-design.md` (Week 1, main에 머지됨)
Scope: 전체 4주 MVP 중 **Week 2만**. Week 3-4는 별도 spec.

---

## 1. 이 문서의 위치 (전체 흐름 중)

| 주차 | 하는 일 | 완료 조건 | 상태 |
|------|---------|-----------|------|
| Week 1 | Foundation + 데이터 수집 | `collect`로 1h+15m 1년치 DB 적재 | ✅ 머지 완료 |
| **Week 2** (이 spec) | 백테스트 엔진 + 첫 전략 + sizing | `backtest`로 train/OOS Sharpe + equity curve | 🔜 |
| Week 3 | paper trader + risk 모듈 + kill switch | `paper` 24시간 + `panic` | |
| Week 4 | hardening + 7일 종이거래 | gross/net 분리 P&L 리포트 | |

Week 2는 Week 1이 쌓은 `Candle`/`FundingRate`/`Instrument` 데이터를 **읽어서** "이 전략이 과거에 돈을 벌었나?"를 정직하게 측정한다.

## 2. Week 2 목표 & 완료 조건

**목표**: event-driven 백테스트 엔진으로 RSI mean-reversion 전략을 과거 데이터에 돌려, 수수료·펀딩·슬리피지를 차감한 정직한 성과(train/OOS Sharpe 등)를 측정한다. 핵심 설계 원칙: **백테스트와 (Week 3)페이퍼가 같은 IStrategy·risk·engine 코드를 공유**한다.

**완료 조건 (DoD)**:
- [ ] `quantpilot backtest --strategy rsi-mr --symbol BTC-USDT-SWAP --timeframe 1h --oos-months 2 --capital 1000` 동작
- [ ] 출력에 **Train Sharpe + OOS Sharpe** 둘 다 표시 (과최적화 진단)
- [ ] 모든 거래에 **fee·funding·slippage 차감**, gross/net 둘 다 리포트
- [ ] **equity curve PNG** 생성 (train/OOS 색 구분, 경로 출력)
- [ ] **gap 체크 게이트**: 데이터 구멍 감지 시 경고, `--allow-gaps` 없으면 중단
- [ ] **새 전략 = 클래스 1개 + 레지스트리 1줄** (open/closed)
- [ ] 위험 모듈 invariant: sizing이 `max_loss ≤ capital×5%` 보장 (ctVal 반영, fuzz 테스트)
- [ ] "봉 안에서 손절 먼저" 보수 가정 검증 (stop+TP 동시 닿는 봉 → stop 체결)
- [ ] fixture/합성 데이터 기반 단위 테스트 통과 (지표·sizing·engine·metrics·gap·CLI)

## 3. 확정된 결정 (brainstorming Q&A)

| 결정 | 선택 | 이유 |
|------|------|------|
| 백테스트 엔진 | **event-driven** (봉 하나씩) | Week 3 페이퍼가 같은 코드 재사용 → "백테=실전 일치". 손절·분할익절 자연 표현 |
| 지표 계산 | **직접 구현** (RSI/ATR/EMA) | 전략 edge가 지표 해석. 수학 소유 → 디버깅 가능, 의존성 0, TDD로 공식 고정 |
| 데이터 품질 | **gap 체크 게이트** (감지·경고) | 백테 정확도와 직결. 메우기·재수집은 TODOS로 defer |
| 결과 출력 | **콘솔 수치 + equity curve PNG** | 그래프로 보는 학습 가치. matplotlib은 안정적 의존성 |
| train/test | **최근 2개월 OOS, 나머지 train** | 과최적화 탐지. walk-forward는 post-MVP |
| 책임 분리 | **Approach A**: 전략=신호 / risk=사이징·손절 / engine=체결·비용·상태 | 리스크가 모든 전략에 일관 적용. 각 조각 독립 테스트 |

## 4. 아키텍처 (Week 1 위에 3 패키지 추가)

```
quantpilot/
├── (Week 1: config, timeframes, exchange/, data/, cli.py — 변경 없음)
├── strategy/
│   ├── __init__.py
│   ├── base.py            # IStrategy, Signal, SignalSide (계약)
│   ├── indicators.py      # rsi(), atr(), ema() — 직접 구현, 순수 함수
│   └── rsi_mean_reversion.py
├── risk/
│   ├── __init__.py
│   ├── sizing.py          # calculate_position_size (ctVal, 5%, invariant assert)
│   ├── liquidation.py     # liquidation_price + 손절-청산 거리 가드
│   └── take_profit.py     # TPLadder (1R/2R/3R 분할)
├── backtest/
│   ├── __init__.py
│   ├── models.py          # Position, Trade, Fill, BacktestResult (dataclass)
│   ├── data_loader.py     # DB 캔들 → DataFrame + gap 체크 게이트
│   ├── costs.py           # fee/funding/slippage 적용
│   ├── engine.py          # event 루프: 봉 하나씩, 체결, 비용
│   ├── metrics.py         # Sharpe, max DD, 승률, profit factor (gross/net)
│   └── report.py          # 콘솔 표 + equity curve PNG (matplotlib)
└── cli.py                 # + backtest 명령 (기존 파일에 추가)

tests/                     # 각 모듈별 + 합성 데이터 기반 engine/metrics/gap 테스트
```

**책임 분리 이유**: 전략은 신호만(stateless), risk는 순수 함수, engine은 상태·체결·비용. 새 전략 추가해도 risk·engine은 그대로 → "전략만 바뀌고 인프라는 남는다".

**Week 3 재사용 범위 (정확히)**: Week 3 페이퍼는 **per-bar 처리 로직**(`check_exits`, `apply_funding`, `process_signal`)과 **risk 모듈 전부**, **IStrategy/Signal**을 재사용한다. 단 **바깥 루프만 다름** — Week 2는 과거 캔들을 배치로 재생, Week 3은 새 봉이 닫힐 때마다 실시간으로 같은 per-bar 함수를 호출. 그래서 per-bar step을 engine의 배치 루프와 분리해 함수로 빼둔다 (engine.py는 "캔들을 순회하며 per-bar step을 호출"만).

## 5. 핵심 인터페이스 (lock — Week 3가 그대로 재사용)

```python
# strategy/base.py
SignalSide = Literal["long", "short", "exit", "hold"]

@dataclass(frozen=True)
class Signal:
    side: SignalSide
    confidence: float                 # 0.0–1.0
    suggested_stop: float | None      # 절대 가격. long/short일 때만 의미
    meta: dict                        # 디버깅 — RSI값, 신호 사유

class IStrategy(ABC):
    name: str
    timeframe: str
    lookback: int                     # 필요한 봉 수 (RSI-14 → 약 30)

    @abstractmethod
    def generate_signal(self, window, open_position) -> Signal:
        """window = 마지막 lookback개 닫힌 봉(pandas, 오름차순). 현재 봉 = window.iloc[-1].
        전략이 window에서 RSI/ATR를 직접 계산해 신호 반환. 상태 없음(stateless).
        WHY window 방식: prepare/캐시 없이 stateless → 백테스트(과거 봉)든
        페이퍼(새 봉)든 '최근 lookback개 봉'을 넘기면 동일 동작. 백테=페이퍼 일치의 토대.
        매 봉 재계산은 8760×30=순식간이라 속도 무관."""
```

```python
# backtest/models.py
@dataclass
class Position:
    side: Literal["long", "short"]
    entry: float
    contracts: int
    stop: float
    targets_remaining: list[tuple[float, float]]   # [(price, fraction), ...]
    opened_ts: int

@dataclass
class Trade:                          # 청산 완료된 한 거래
    side: str
    entry: float
    exit: float
    contracts: int
    pnl_gross: float
    fees: float
    funding: float
    pnl_net: float
    opened_ts: int
    closed_ts: int
    reason: str                       # "stop" | "tp1".."tp3" | "exit_signal"
```

WHY: `suggested_stop`만 전략이 제안하고 사이징·체결은 risk/engine이 담당 → 리스크가 모든 전략에 일관. `Trade`에 gross/net + fees/funding 분리 기록 → "수수료 빼면 수익 사라지나?"가 항상 보임.

## 6. Engine 흐름 (backtest/engine.py)

```
for 각 봉 i (lookback 이후):
  bar = candles[i]                          # open/high/low/close/ts
  window = candles[i-lookback+1 : i+1]

  1. 열린 포지션 있으면 → 이 봉에서 손절·TP 체결 먼저 판정 (bar high/low로)
  2. funding 적용 (8h 시각에 포지션 보유 중이면 funding_rate 차감)
  3. signal = strategy.generate_signal(window, position)
  4. 신호 처리:
     - long/short & 포지션 없음 → sizing 계산 → 진입(슬리피지+fee 차감)
     - exit & 포지션 있음 → 청산
  5. equity 곡선에 (ts, 평가자본) 기록
→ BacktestResult(trades, equity_curve, train_metrics, oos_metrics)
```

### ⭐ 핵심 모델링 결정 — "봉 안에서 손절 먼저"

한 봉의 high·low가 **손절가와 익절가를 동시에** 건드리면, 봉 내부 체결 순서를 모른다.
→ **보수적으로 "손절이 먼저 체결됐다"고 가정**한다.

WHY: 낙관적으로 "TP 먼저" 가정하면 백테스트 수익이 부풀려져 실거래에서 박살난다. retail 백테스트 over-optimism의 1번 원인. 손절 먼저 가정은 백테스트가 자기 자신에게 거짓말 안 하게 하는 장치. (엔진 테스트 ②가 이걸 검증)

## 7. Risk 모듈 (Week 3·실거래가 그대로 재사용)

```python
# risk/sizing.py
def calculate_position_size(capital, risk_pct, entry, stop, ct_val, lot_sz,
                            leverage, maint_margin_rate, fee_bps, side) -> SizingResult:
    # Invariant(강제 assert): max_loss + fee_estimate ≤ capital × risk_pct × 1.02
    # ctVal 반영, 레버리지 상한 클램프, 청산 거리 체크(liquidation.py)
    # 자세한 구현은 parent design doc의 sizing.py 스케치 따름.

# risk/liquidation.py
def liquidation_price(entry, leverage, side, mmr=0.005) -> float: ...
# 가드: |stop - entry| > |liq - entry| × 0.7 면 진입 거부 (StopBeyondLiquidationError)

# risk/take_profit.py
@dataclass
class TPLadder:
    @classmethod
    def from_r_multiples(cls, entry, stop, side,
                         r_multiples=[1.0, 2.0, 3.0],
                         fractions=[0.33, 0.33, 0.34]) -> "TPLadder":
        """R = |entry - stop|. target = entry ± R×r. 사용자 원래 구상 '적정 비율 분할 익절'."""
```

## 8. Costs (backtest/costs.py)

```
fee:       진입 notional × taker_bps + 청산 fill마다.  기본 taker 5bps(0.05%), config 노출
slippage:  체결가를 불리한 쪽으로 slippage_bps.  기본 2~5bps
funding:   8h 시각마다 포지션_notional × funding_rate 차감 (롱은 +funding일 때 지불)
           → Week 1 FundingRate 테이블 읽음
```
모든 비용은 `Trade`에 분리 기록 → gross/net 둘 다 리포트.

## 9. Indicators (backtest 전 직접 구현, 순수 함수)

```python
# strategy/indicators.py — 전부 pure, 입력 pd.Series → 출력 pd.Series
def rsi(close: pd.Series, period: int = 14) -> pd.Series: ...   # Wilder's smoothing
def atr(high, low, close, period: int = 14) -> pd.Series: ...
def ema(series: pd.Series, period: int) -> pd.Series: ...
```
TDD: 알려진 입력 시계열의 공식값과 대조해 고정 (예: 단조 상승 시계열의 RSI → 100 수렴).

## 10. 첫 전략 (strategy/rsi_mean_reversion.py)

```
RSI(14) < 30 → long 신호, suggested_stop = entry - ATR(14) × k
RSI(14) > 70 → short 신호, suggested_stop = entry + ATR(14) × k
포지션 보유 중 RSI가 중립(45~55) 복귀 → exit 신호
```
파라미터(30/70/k)는 **train 구간에서만** 결정. baseline은 외부 검증된 가설 차용 (parent design 참조 — 수익성 단정 아님, infra 검증용 신호 생성기).

## 11. Metrics + train/test (backtest/metrics.py)

```
net(비용 차감) 기준 + gross 병기:
  Sharpe        **per-bar 자본 수익률**(equity_curve의 봉 단위 % 변화)의
                평균/표준편차 × √(연환산). 1h봉 → √(24×365). per-trade 아님.
                WHY per-bar: 표준 정의이고, 거래 빈도와 무관하게 위험 보정됨.
  max drawdown  자본 곡선 최대 고점→저점 낙폭
  win rate      net pnl > 0 거래 비율
  profit factor 총이익/총손실
  total return  최종/초기 - 1
  거래 수
train/test 분리: 최근 oos_months(기본 2) = OOS, 나머지 = train.
  → Train·OOS 메트릭 나란히. train≫OOS = 과최적화 신호.
```

## 12. 출력 (backtest/report.py)

```
콘솔 표:    Train | OOS  ×  (Sharpe, maxDD, 승률, PF, 수익률, 거래수), gross/net
equity PNG: train(파랑)+OOS(주황) 한 그래프, 분리 시점 세로선
            → "backtest_<symbol>_<strategy>_<ts>.png 저장됨" 경로 출력
```
WHY now_ms/timestamp 주입: 결정적 테스트 위해 파일명 타임스탬프는 호출부에서 주입.

## 13. Gap 체크 게이트 (backtest/data_loader.py)

```
DB 캔들 → pandas DataFrame 로드 (symbol+timeframe+기간)
예상 봉수 = (끝-시작)/봉길이 + 1, 실제 = 행수, gap = 차이 + 위치 탐지
gap > 0 → 경고("1h 12개 누락, 구간 X~Y"), --allow-gaps 없으면 중단(exit≠0)
```
(Week 1 `status`의 예상-vs-실제 로직 재활용. 메우기·재수집은 TODOS로 defer.)

## 14. CLI (cli.py에 추가)

```bash
quantpilot backtest --strategy rsi-mr --symbol BTC-USDT-SWAP \
    --timeframe 1h --oos-months 2 --capital 1000 [--leverage 3] [--allow-gaps]
```
전략 레지스트리: `STRATEGIES = {"rsi-mr": RsiMeanReversion}` → 새 전략 = 클래스 + 1줄 등록.
잘못된 전략 이름·심볼은 네트워크/연산 전 친절한 ClickException (Week 1 QA 교훈).

## 15. 테스트 전략 (TDD, fixture/합성 데이터)

```
indicators   RSI/ATR/EMA를 알려진 공식값으로 검증
sizing       ctVal × 다중심볼 × invariant fuzz (max_loss ≤ 5%)
liquidation  손절-청산 거리 가드
take_profit  1R/2R/3R 레벨 계산
engine       ① 손계산 가능한 합성 시계열로 pnl 검증
             ② "봉 안 손절 먼저" (stop+TP 동시 닿는 봉 → stop 체결 assert)
             ③ fee/funding/slippage 적용 (gross vs net 차이)
             ④ 결정적(같은 입력 → 같은 결과)
metrics      알려진 equity curve로 Sharpe/maxDD 검증
gap gate     구멍 있는 합성 캔들 → 감지
CLI          CliRunner + 가짜 전략 + in-memory 데이터 → 백테스트 동작
```

## 16. Out of Scope (Week 2 아님 — defer)

- paper trader, 실시간, circuit breaker, panic → Week 3
- walk-forward rolling validation → post-MVP (단순 train/test split만)
- gap 자동 메우기·재수집 → Week 1 TODOS (감지·경고만 Week 2)
- 두 번째 전략(MA crossover) → Week 2 끝에 인터페이스 검증용 sketch만, 본 구현은 이후
- 다중 심볼·다중 포지션 → 단일 심볼·단일 포지션 (Broker 추상화는 over-engineering)
- volume 단위 확정 → RSI-MR·sizing은 volume 안 씀, Week 1 TODOS 유지

## 17. Open Questions (구현 중 결정)

1. **연환산 계수**: 1h는 √(24×365). 15m는 √(96×365). timeframe에서 자동 도출.
2. **RSI 중립 exit 구간**: 45~55 vs 50 정확. 구현 시 train 결과 보고 결정.
3. **ATR stop 배수 k**: 기본 1.5~2.0. train에서만 튜닝.
4. **funding 적용 정밀도**: 8h 경계에 정확히 차감 vs 봉 단위 근사. 8h 경계 정확 권장.

## 18. 프로젝트 컨벤션 (Week 1과 동일)

- DB/수학/모델링 결정에 **WHY 주석** 필수.
- 타임스탬프 int ms epoch (UTC).
- YAGNI — 쓰는 코드와 함께 추가.
- 사용자는 트레이딩 초보 → 개념 설명 곁들임.
- 잘못된 입력은 raw traceback 아닌 친절한 CLI 에러 (Week 1 QA 교훈).

## 19. Week 1 TODOS 연계

이 spec이 Week 1 TODOS 중 다루는 것: **연속성(gap) 감지** (게이트로). 나머지(confirm 필드, gap 메우기, volume 단위, funding realizedRate)는 TODOS.md에 그대로 유지하며 Week 3+/실거래 전 처리.
