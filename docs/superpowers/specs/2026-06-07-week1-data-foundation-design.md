# Spec: QuantPilot Week 1 — Foundation + Data Collection

Date: 2026-06-07
Status: APPROVED (brainstorming 완료, writing-plans 대기)
Parent design: `~/.gstack/projects/quantpilot/seungbinmin-main-design-20260606-042827.md` (전체 4주 MVP 설계, office-hours 산출물)
Scope: 전체 4주 MVP 중 **Week 1만**. Week 2-4는 별도 spec.

---

## 1. 이 문서의 위치 (전체 흐름 중)

```
[완료]  office-hours    → design doc (4주 전체 그림, 승인됨)
[완료]  brainstorming   → 이 spec (Week 1을 구현 가능하게 구체화)
[다음]  writing-plans   → Week 1 구현 계획 (단계별 task)
[그후]  구현            → 코드 작성
```

전체 4주 구성:
| 주차 | 하는 일 | 완료 조건 |
|------|---------|-----------|
| **Week 1** (이 spec) | Foundation + 데이터 수집 | `collect`로 1h+15m 1년치 DB 적재 |
| Week 2 | 백테스트 엔진 + 첫 전략 + sizing | `backtest`로 train/OOS Sharpe 출력 |
| Week 3 | paper trader + risk 모듈 + kill switch | `paper` 24시간 무중단 + `panic` |
| Week 4 | hardening + 7일 종이거래 | gross/net 분리 P&L 리포트 |

## 2. Week 1 목표 & 완료 조건

**목표**: OKX의 시장 데이터(가격 캔들 + funding rate)를 안정적으로 수집해서 로컬 SQLite에 쌓는 토대를 만든다. 이 데이터 위에 Week 2 백테스트가 얹힌다.

**완료 조건 (Definition of Done)**:
- [ ] `quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 365` → 약 8,760봉 적재
- [ ] `quantpilot collect --symbol BTC-USDT-SWAP --timeframe 15m --days 365` → 약 35,040봉 적재
- [ ] `quantpilot collect-funding --symbol BTC-USDT-SWAP --days 365` → 약 1,095개 적재
- [ ] 위 명령들을 **재실행해도 중복이 안 생기고** 새 데이터만 이어붙음 (idempotent 증분)
- [ ] `quantpilot status` → DB에 적재된 내용 요약 출력
- [ ] 미완성(현재 형성 중) 캔들은 저장 안 됨 (lookahead bias 방지)
- [ ] fixture 기반 단위 테스트 통과 (파싱/페이지네이션/drop_unclosed/idempotency)

## 3. 확정된 결정 사항 (brainstorming Q&A)

| 결정 | 선택 | 이유 |
|------|------|------|
| OKX 접근 방식 | **ccxt unified API** | 페이지네이션·rate limit 일부 내장, 빠른 구현, 거래소 이식 용이 |
| DB 테이블 범위 | **3개만** (Candle, FundingRate, Instrument) | YAGNI — Week 1이 실제 쓰는 것만. Trade/Position 등은 Week 2-3에 추가 |
| Timeframe | **1h + 15m, 각 1년** | RSI 전략이 쓰는 구간과 일치. 5m/1m은 계획 없으므로 제외 |
| 재실행 동작 | **idempotent 증분 (upsert)** | cron 재수집·Week 3 paper의 전제 |
| 테스트 전략 | **fixture 기반 + 선택적 live smoke** | 빠르고 결정적, CI 가능 |
| 코드 구조 | **Approach A: 타깃 구조, Week 1 파일만** | design doc 패키지 경계 유지 → Week 2-3가 리팩터 없이 파일 추가로 끝남 |

## 4. 아키텍처 (Week 1 파일만)

design doc의 패키지 경계를 그대로 쓰되, Week 1이 실제 쓰는 파일만 생성한다.
**빈 `strategy/`, `backtest/`, `paper/`, `risk/` 패키지는 만들지 않는다** (Week 2-3에 생김).

```
quantpilot/
├── config.py              # pydantic settings (DB 경로, 거래소)
├── exchange/
│   ├── client.py          # ccxt.okx 래퍼 — 거래소 통신만 담당, DB 모름
│   └── instruments.py     # ccxt market dict → Instrument 파싱
├── data/
│   ├── db.py              # SQLAlchemy engine, session factory
│   ├── models.py          # Candle, FundingRate, Instrument (3개)
│   └── collector.py       # 증분 upsert 로직 (OHLCV + funding)
└── cli.py                 # click: collect, collect-funding, status
tests/
├── fixtures/              # 저장된 OKX 응답 JSON
├── test_collector.py      # 파싱/페이지네이션/drop_unclosed/idempotency
├── test_instruments.py    # ctVal 파싱
└── test_live.py           # @pytest.mark.live (수동 실행)
```

**모듈 책임 분리 이유**: `client.py`가 거래소 통신만 담당하면 나중에 Binance 추가 시 `client.py`만 교체. `collector.py`는 "무엇을/언제 받을지"만 결정하고 ccxt 세부는 client에 위임.

## 5. 데이터 모델 (3개 테이블)

### 설계 원칙 (전 테이블 공통)
- **타임스탬프는 전부 int ms epoch (UTC)**. datetime 객체 안 씀.
  - WHY: SQLite는 네이티브 타임존 타입이 없어 datetime 저장 시 로컬/UTC 혼동 버그 발생. 정수면 모호함 0.
- **테이블 간 외래키(FK) 없음**. `symbol` 문자열로만 논리적 연결.
  - WHY: 원시 시장 데이터는 append 위주. 참조무결성 강제는 쓰기 순서 의존성만 만들고 이득 없음. 캔들을 instrument 캐시보다 먼저 받아도 문제없어야 함.
- **모든 스키마 결정에 WHY 주석 필수** (사용자 요청 — 아래 코드 참조).

### ERD (의도적으로 최소: 3 테이블, FK 0개)

```
┌─────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│   Instrument    │   │     Candle       │   │   FundingRate    │
│  (메타데이터)    │   │  (시계열 OHLCV)  │   │  (시계열 funding) │
├─────────────────┤   ├──────────────────┤   ├──────────────────┤
│ symbol (uniq)   │   │ symbol           │   │ symbol           │
│ ct_val          │   │ timeframe        │   │ ts               │
│ lot_sz, min_sz  │   │ ts               │   │ funding_rate     │
│ tick_sz         │   │ OHLCV            │   │                  │
└─────────────────┘   └──────────────────┘   └──────────────────┘
        └──────── symbol 문자열로 논리적 연결 (FK 강제 안 함) ───────┘
```

**왜 3개가 최소인가**:
- Candle(봉마다 1행)과 FundingRate(8시간마다 1행)는 시간 주기가 달라 한 테이블에 못 합침.
- Instrument는 시계열이 아닌 메타데이터(심볼당 1행)라 본질이 다름.
- Week 2-3에서 Trade/Position이 생기면 그땐 진짜 FK 관계 필요 → 그 코드 짤 때 추가.

### models.py (WHY 주석 포함)

```python
# data/models.py
#
# 설계 원칙 (이 파일 전체에 적용):
# - 타임스탬프는 전부 int ms epoch (UTC). datetime 객체 안 씀.
#   WHY: SQLite는 네이티브 타임존 타입이 없어서 datetime 저장 시
#        로컬/UTC 혼동 버그가 남. 정수로 저장하면 모호함이 0.
# - 테이블 간 외래키(FK) 없음. symbol 문자열로만 논리적 연결.
#   WHY: 원시 시장 데이터는 append 위주라 참조무결성 강제가
#        득보다 실. 캔들을 instrument 캐시보다 먼저 받을 수도 있음.

class Candle(Base):
    """OHLCV 캔들 1개. 거래소 raw 데이터를 그대로 보존."""
    __tablename__ = "candles"

    id          = Column(Integer, primary_key=True)
    exchange    = Column(String, nullable=False, default="okx")
    symbol      = Column(String, nullable=False)      # "BTC-USDT-SWAP"
    timeframe   = Column(String, nullable=False)      # "1h" | "15m"
                                                      # WHY String: ccxt가 문자열로 받음. enum 변환 한 단계 제거.
    ts          = Column(BigInteger, nullable=False)  # 캔들 open time, ms epoch UTC
    open        = Column(Float, nullable=False)
    high        = Column(Float, nullable=False)
    low         = Column(Float, nullable=False)
    close       = Column(Float, nullable=False)
    volume      = Column(Float, nullable=False)       # ccxt OHLCV[5]. 계약 수량 기준.
                                                      # WHY 단일 컬럼: 통화환산 volume은 Week 1에서 안 씀(YAGNI).
    inserted_at = Column(BigInteger, nullable=False)  # 이 행을 DB에 넣은 시각, ms epoch
                                                      # WHY: "이 캔들 언제 받았지?" 디버깅이 의외로 잦음.

    __table_args__ = (
        # 이 unique 제약이 idempotency의 핵심.
        # WHY: 같은 (거래소,심볼,봉,시각)은 단 1행. 재실행 시 upsert가
        #      여기 걸려서 중복 없이 무시됨. 증분 수집의 토대.
        UniqueConstraint("exchange", "symbol", "timeframe", "ts"),
        Index("ix_candle_lookup", "symbol", "timeframe", "ts"),  # 범위 조회용
    )

class FundingRate(Base):
    """선물 funding rate 1개. 8시간마다 1개."""
    __tablename__ = "funding_rates"

    id           = Column(Integer, primary_key=True)
    exchange     = Column(String, nullable=False, default="okx")
    symbol       = Column(String, nullable=False)
    ts           = Column(BigInteger, nullable=False)  # funding time, ms epoch UTC
    funding_rate = Column(Float, nullable=False)        # e.g., 0.0001 = 0.01%
    inserted_at  = Column(BigInteger, nullable=False)

    __table_args__ = (
        # idempotency: 같은 (거래소,심볼,funding시각)은 1행.
        UniqueConstraint("exchange", "symbol", "ts"),
    )

class Instrument(Base):
    """거래 명세 메타데이터. 심볼당 1행. Week 2 sizing이 ct_val을 읽음."""
    __tablename__ = "instruments"

    id          = Column(Integer, primary_key=True)
    exchange    = Column(String, nullable=False, default="okx")
    symbol      = Column(String, nullable=False)
    ct_val      = Column(Float, nullable=False)   # 계약 면값 (BTC-USDT-SWAP=0.01)
                                                  # WHY 캐시: Week 2 position sizing이 매번 읽음. 미리 받아둠.
    ct_val_ccy  = Column(String, nullable=False)  # "BTC"
    lot_sz      = Column(Float, nullable=False)   # 최소 주문 증분(계약)
    min_sz      = Column(Float, nullable=False)   # 최소 주문 수량
    tick_sz     = Column(Float, nullable=False)   # 가격 최소 단위
    updated_at  = Column(BigInteger, nullable=False)  # 마지막 갱신 ms epoch

    __table_args__ = (UniqueConstraint("exchange", "symbol"),)
```

## 6. Collector 동작 흐름

### `quantpilot collect` 전체 흐름
```
1. config 로드 (DB 경로, 거래소. key 불필요 — 전부 public 엔드포인트)
2. ccxt.okx(enableRateLimit=True) 생성
   WHY enableRateLimit: rate limit 간격을 ccxt가 자동 처리. Week 1엔 직접 토큰버킷 불필요.
3. instruments 갱신: load_markets() → ctVal/lotSz/minSz/tickSz 파싱 → Instrument upsert
   WHY 먼저: Week 2 sizing이 ct_val을 읽으므로 미리 캐시.
4. 시작점 결정 (증분의 핵심):
   SELECT max(ts) FROM candles WHERE symbol=? AND timeframe=?
     • 없으면 → since = now - days×86400000  (처음부터)
     • 있으면 → since = last_ts + timeframe_ms  (그다음 봉부터)
5. 페이지네이션 루프:
   while since < now:
     batch = fetch_ohlcv(symbol, tf, since=cursor, limit=100)
     if not batch: break
     batch = drop_unclosed(batch)        # 미완성 봉 제거
     upsert_candles(batch)               # ON CONFLICT DO NOTHING
     cursor = batch[-1].ts + timeframe_ms
     진행률 출력
   WHY limit=100: OKX 1회 최대 100봉. 1년 1h = 약 88회 호출.
6. 요약 출력: "8,760봉 적재 (신규 N, 중복 M), 범위 X~Y"
```

### 핵심 안전장치 1: 미완성 캔들 버리기
```python
def drop_unclosed(batch, timeframe_ms, now_ms):
    # 현재 형성 중인 봉은 OHLC가 계속 변함.
    # WHY: 안 닫힌 봉을 저장하면 → 재실행 때 같은 ts인데 값이 달라짐
    #      → idempotency 깨지고 백테스트가 오염됨 (lookahead bias).
    #      봉이 완전히 닫힌 것만(ts + 봉길이 <= 현재) 저장.
    return [c for c in batch if c.ts + timeframe_ms <= now_ms]
```

### 핵심 안전장치 2: 네트워크 끊김 = 재실행으로 복구
```
페이지네이션 중 timeout/429 → 짧은 backoff 재시도 몇 번
그래도 실패 → 받은 데까지 commit하고 깨끗하게 종료
WHY: 증분 설계라 다음 실행이 마지막 저장 ts부터 자동 재개. 중간에 죽어도 데이터 손상 0.
```

### funding collector (거의 동일)
```
fetch_funding_rate_history(symbol, since, limit) 페이지네이션
→ FundingRate upsert (8시간마다 1개, 1년 ≈ 1,095개)
→ 동일한 증분 + idempotent 로직
```

## 7. CLI 명령 (click 사용)

```bash
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 365
quantpilot collect-funding --symbol BTC-USDT-SWAP --days 365
quantpilot status
```

WHY click: 옵션 파싱·`--help`·입력 검증을 데코레이터로 공짜 제공. 직접 구현 불필요.

`status` 출력 예시:
```
BTC-USDT-SWAP
  1h:  8,760봉 / 예상 8,760  (2025-06-07 ~ 2026-06-07)  ✓
  15m: 35,040봉 / 예상 35,040 (2025-06-07 ~ 2026-06-07)  ✓
  funding: 1,095개
Instrument 캐시: ctVal=0.01, lotSz=1, 갱신 3시간 전
```
WHY "예상 N" 표시: `(기간 / 봉길이)`로 계산한 기대 개수와 실제 행 수를 단순 비교만 함.
이건 **빠진 게 있나 눈으로 확인**하는 용도. "빠진 구간을 자동으로 찾아 다시 받는"
gap 자동 감지+재수집(section 10, out of scope)과는 다름. status는 보고만, 수정 안 함.

## 8. 에러 처리

**종류 A — 일시적 (재시도로 해결)**: 네트워크 타임아웃, 429 Too Many Requests
→ backoff 재시도 (간격 1s→2s→4s). 몇 번 실패 시 받은 데까지 저장 후 종료 (증분이라 재실행으로 재개).

**종류 B — 사람이 고쳐야 함 (재시도 무의미)**: 오타난 심볼, 지원 안 하는 timeframe
→ 즉시 멈추고 명확한 메시지. 예: `"심볼 'BTC-USDT-SWAPP'를 OKX에서 못 찾음. 사용 가능: ..."`

원칙: 일시적은 조용히 재시도, 사람 실수는 바로 멈추고 친절히 알림. 둘을 섞지 않음.

## 9. 테스트 전략

**fixture 기반** (인터넷 없이 결정적):
- OKX 응답을 1번 받아 `tests/fixtures/`에 JSON 저장 → 테스트는 그걸 읽음.
- 검증 대상:
  - 파싱: raw → Candle 변환 정확성
  - 페이지네이션 커서: `last_ts + timeframe_ms` 계산
  - **drop_unclosed**: 미완성 봉 필터링 (가장 중요)
  - upsert idempotency: 같은 데이터 2번 넣어도 중복 없음

**선택적 live smoke**: `@pytest.mark.live` — 평소엔 안 돌고 `pytest -m live`로 수동 실행. "진짜 OKX가 응답하나" 1회 확인.
WHY 분리: 일반 테스트는 fixture로 빠르고 안정적, 인터넷 문제로 깨지지 않게.

## 10. Out of Scope (Week 1 아님 — 이후 주차로 명시 defer)

- 전략(strategy/), 백테스트(backtest/), paper trader, risk 모듈 → Week 2-3
- Trade/Fill/Signal/Position 테이블 → 쓰는 코드와 함께 Week 2-3에 추가
- API key 발급 / 주문 / position mode 검증 → Week 1은 public 데이터만이라 불필요
- 5m/1m timeframe, 두 번째 심볼 실거래 → 계획 없음 (YAGNI)
- gap 자동 감지·재수집 → 증분만으로 충분. post-MVP

## 11. Open Questions (구현 중 결정)

1. **fixture를 어떻게 생성하나**: 첫 구현 시 live API를 1회 호출해 응답을 직접 저장 vs 손으로 작성. → 실 응답 저장 권장 (현실적인 형태 보장).
2. **데이터 보존**: 1h/15m는 1년 유지로 무난(~50MB). 1m 도입 시 보존 정책 재검토 (현재 미도입).
3. **config 위치**: `.env` + pydantic BaseSettings. DB 경로 기본값 `data/quantpilot.db`.

## 12. 프로젝트 컨벤션 (이 프로젝트 전체 적용)

- **DB/스키마 코드에는 항상 WHY 주석** — 왜 이 타입/제약/구조인지 설명 (사용자 요청).
- **타임스탬프는 int ms epoch (UTC)** 통일.
- **YAGNI** — 쓰는 코드와 함께 스키마/모듈 추가. 미리 안 만듦.
- 사용자는 트레이딩/봇 초보 → 코드·커밋·문서에 개념 설명을 곁들임.
