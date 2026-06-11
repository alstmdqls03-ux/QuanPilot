# Confluence 전략 (BOT-SPEC 모드 A 코어) — Phase 1 설계

> 출처: 사용자 정리 규칙 명세서 `~/Desktop/DevWork/차트패턴분석/00-자동매매봇-규칙명세서.md`
> (BOT-SPEC v1.0, "MJ의 라스트댄스" 강의 1~7강 통합본). 본 문서는 그중 **모드 A(되돌림
> 점수제)의 코어 슬라이스**를 QuantPilot에 얹는 Phase 1 설계다.
>
> **한계 고지(원문 §10 승계)**: 전략 규칙은 단일 유튜브 강사 주장으로 수익성 미검증.
> 본 프로젝트의 목적이 정확히 이것의 $0 검증이다: backtest → walk-forward → 교차심볼
> → paper. 검증 실패 시 "전략 기각"도 유효한 결과로 취급한다.

## 1. 목적 / 완료 조건

- **목적**: BOT-SPEC 모드 A의 점수제(겹침 근거 진입)를 `IStrategy` 플러그인 `confluence`
  로 구현하고, 멀티심볼·멀티TF 데이터 위에서 통계 검증까지 끝낸다.
- **완료 조건**:
  1. `quantpilot backtest --strategy confluence`가 BTC/ETH 1h 2년 데이터에서 동작
  2. 시그널 전부 룩어헤드-프리 테스트 통과 (§8)
  3. 검증 리포트: train/OOS + walk-forward + BTC↔ETH 교차 + rsi-mr 베이스라인 비교
  4. (검증 통과 시) `quantpilot paper --strategy confluence` 페이퍼 가동 가능

## 2. 확정된 결정 (brainstorming Q&A)

| # | 질문 | 결정 |
|---|------|------|
| 1 | Phase 1 범위 | **코어 점수제 슬라이스**: S1 매물대, S2 다이버전스, S4 피보, S5 RSI극단, S6 4h보너스 + 점수·게이트 + TP 50/40/10·BE트레일. S3 채널·모드 B는 defer |
| 2 | 파동 정의 | **ZigZag 확정 피벗** (ATR×k 되돌림 확정). 채널 이탈 판정 대체 |
| 3 | 검증 데이터 | **BTC+ETH × 15m/1h/4h × 2년** + gap 연속성 재수집 선행 |
| 4 | 멀티TF 실행 | **1h 판정+진입**, 4h는 읽기전용 컨텍스트(S6/G4). 15m 진입은 Phase 2 |
| 5 | 리스크 | **5% + 점수 연동**: 4~5점=2.5%, 6점+=5% (기존 사이징 invariant 재사용) |

## 3. 아키텍처 (신규/수정 파일)

```
quantpilot/strategy/pivots.py      [신규] ZigZag 확정 피벗 — 공통 기반
quantpilot/strategy/zones.py       [신규] 매물대 박스 + 플립 + 휩소 필터
quantpilot/strategy/divergence.py  [신규] RSI 다이버전스 (컨펌/폐기 상태기계)
quantpilot/strategy/fib.py         [신규] 직전 파동 피보나치 레벨
quantpilot/strategy/confluence.py  [신규] 점수 합산 + 게이트 + IStrategy ("confluence")
quantpilot/backtest/engine.py      [수정] TP 사다리 파라미터화 + BE 트레일링 옵션
quantpilot/risk/take_profit.py     [수정] build_targets에 fractions/targets 주입 허용
quantpilot/backtest/data_loader.py [수정] HTF(4h) 컨텍스트 로더
quantpilot/data/collector.py       [수정] gap 검출 + 재수집 (기존 pre-live TODO 해결)
quantpilot/cli.py                  [수정] STRATEGIES 등록, backtest에 --htf 옵션
```

원칙 유지: 수학 직접 구현(외부 TA 라이브러리 금지), 순수 함수, WHY 주석,
백테=페이퍼 일치(엔진 함수 공유), 손절 먼저 보수 가정.

## 4. 컴포넌트 상세

### 4.1 pivots.py — ZigZag 확정 피벗
- `confirmed_pivots(df, atr_k=3.0) -> list[Pivot(ts, price, kind{"H","L"}, confirmed_ts)]`
- 정의: 마지막 극점에서 **ATR(14)×k 이상 반대 방향 이동이 봉마감으로 확인**되는 순간
  그 극점을 피벗으로 확정. `confirmed_ts` = 확정된 봉의 ts.
- **룩어헤드 금지의 핵심**: 소비자는 `confirmed_ts <= 현재 봉 ts`인 피벗만 볼 수 있다.
  미확정 잠정 극점은 절대 노출하지 않는다.
- 파동 = 인접 확정 피벗(H↔L) 쌍. atr_k는 [설계] 파라미터(백테 민감도 스윕 §7).

### 4.2 zones.py — 매물대 (S1)
- `detect_zones(df, pivots, ...) -> list[Zone(top, bottom, created_ts, flipped, broken_ts)]`
- 검출: 확정 피벗들이 ATR×k_z 범위 안에 n회 이상 군집한 가격대를 박스로 등록
  (원문 "횡보하며 오래 거래된 박스권"의 정량화 — [설계]).
- 플립: 봉**마감**이 박스 하단 아래(상향은 상단 위)면 이탈 확정 → 역할 전환, 박스 유지.
  장중 스파이크는 무시(V4 휩소 필터 내장).
- 발화: 가격이 경계 ±ATR×0.25 안 도달. 첫 터치 > 재터치 (메타에 touch_count).

### 4.3 divergence.py — RSI 다이버전스 (S2)
상태기계(시그널 인스턴스마다):
```
DETECTED   가격 LL+RSI HL (롱; 숏은 거울) — 두 비교점 모두 '확정 피벗', RSI는 해당
           피벗 봉의 값. 롱은 RSI<30 구간 발생만 / 숏은 RSI>70 구간만 유효
WAITING    봉마감 대기 (원문 컨펌 ①)
DISCARDED  다음 봉이 비교 저점(고점) 재이탈 — F1 폐기 (원문 컨펌 ②)
CONFIRMED  꼭짓점 형성 후 재반등 = 반전 방향 봉마감 확인 (원문 컨펌 ③)
```
- 점수는 CONFIRMED만 +2. 같은 방향 연속 2회(둘 다 유효 구간) = 더블 +1.
- RSI 30/70 단독은 진입 불가(원문 금지) — S5 보조 점수로만.

### 4.4 fib.py — 피보나치 (S4)
- `fib_levels(wave_high, wave_low) -> {0.382, 0.5, 0.618}` (직전 **확정** 파동 기준)
- 발화: 가격이 0.5~0.618 존 도달 +1. 목표가 산출(§5 TP2)에도 재사용.

### 4.5 confluence.py — 조립 (IStrategy)
- `ConfluenceStrategy(timeframe="1h")`, registry key `"confluence"`.
- 생성자/엔진에서 **HTF(4h) 캔들 주입** — `generate_signal` 호출 시점의 1h 봉마감
  기준으로 **이미 마감된 4h 봉까지만** 슬라이스해 전달(룩어헤드 금지).
- 매 봉: 피벗/존/다이버전스/피보 갱신 → 방향별 점수 합산:

| ID | 조건 | 점수 |
|----|------|:---:|
| S1 | 매물대 지지(롱)/저항(숏) 도달 (플립 리테스트 포함) | +2 |
| S2 | 다이버전스 CONFIRMED (유효 구간) | +2 |
| S2+ | 더블 다이버전스 | +1 |
| S4 | 피보 0.5~0.618 존 도달 | +1 |
| S5 | RSI≤30(롱)/≥70(숏) | +1 |
| S6 | S1 또는 S2가 4h에서도 동시 성립 | +1 (캡 +2) |

- 판정: 총점≥4 & 계열≥2 → 진입(리스크 2.5%) / 총점≥6 & 계열≥3 → 강진입(5%).
  점수→리스크는 `Signal.strength`(0.5/1.0)로 전달, 사이징이 5%×strength로 적용.
- **게이트/베토 (진입 전 전부 통과)**:
  - G1 봉마감+다음봉: 기존 closed-bar 엔진이 보장 (작업 없음)
  - G2 R:R≥1.5: (TP1 거리)/(손절 거리) <1.5면 스킵. TP1=경로상 첫 매물대 경계 →
    **V6(목표 경로 차단) 자동 내장**
  - V1 원웨이: 직전 20봉 동일방향 봉 비율 >0.8이면 역추세 진입 차단 ([설계], 스윕 대상)
  - V2 나이프캐칭: 다이버전스 컨펌 절차(③ 반전 봉마감)가 커버
  - V4 휩소: zones/피벗이 봉마감 판정만 쓰므로 구조 내장
- 손절: 직전 확정 피벗 아래(롱)/위(숏). 기존 청산가 가드 + 사이징 assert 그대로.

## 5. 엔진 확장 (백테=페이퍼 일치 보존)

1. **TP 사다리 파라미터화**: `Signal.meta["targets"]=[(price, frac), ...]` 제안 시
   엔진이 그것을 사용, 없으면 **현행 1R/2R/3R·33/33/34 기본값** → rsi-mr 거동 변화 0.
   confluence 타깃: TP1=첫 매물대 경계(50%), TP2=피보 0.618 목표(40%), TP3=러너(10%).
2. **BE 트레일링**: `Position.move_stop_to_be_after_tp1: bool` (기본 False).
   True면 TP1 체결 봉 마감 후 stop=entry. '손절 먼저' 가정 유지, panic·서킷 영향 없음.
3. 두 변경 모두 backtest.engine에만 — 페이퍼는 같은 함수 재사용으로 자동 상속.
   `test_paper_parity`에 confluence 케이스(부분익절+BE트레일 포함) 추가.

## 6. 데이터 계획

1. **gap 연속성 재수집 (선행)**: 예상 ts 그리드(타임프레임 간격) vs 실제 행 비교 →
   빠진 구간만 범위 재요청. `quantpilot collect --heal` 옵션. (pre-live TODO 해결)
2. **수집**: {BTC,ETH}-USDT-SWAP × {15m,1h,4h} × 730일 (+funding). 15m은 Phase 2
   진입 정밀화 대비 선수집.
3. 수집 후 `status`로 봉 수/연속성 확인이 검증 게이트.

## 7. 검증 계획 (합격 기준 사전 선언)

| 단계 | 내용 |
|------|------|
| V-1 | BTC 1h 2년 train/OOS (기존 split) — 기본 가중치로 |
| V-2 | walk-forward: 기간 3~4분할, 각 분할 OOS 지표 안정성 |
| V-3 | ETH 교차: BTC에서 정한 파라미터 그대로 ETH 적용 |
| V-4 | 민감도 스윕: ZigZag atr_k, 점수 임계(4/6), V1 비율 — 결과가 파라미터에 과민하면 적신호 |
| V-5 | rsi-mr 베이스라인과 동일 기간 비교 |

**합격**: 모든 OOS 구간 PF>1.0 그리고 MaxDD가 rsi-mr 대비 악화 없음.
**불합격 처리**: 가중치 보정 1회 재시도 → 그래도 미달이면 전략 기각 리포트 작성
(기각도 edge-finding의 정상 산출물).

## 8. 테스트 전략 (TDD, 룩어헤드 최우선)

- **룩어헤드-프리 공통 테스트** (시그널마다 필수): `f(data[:i])` 의 i시점 출력 ==
  `f(data_full)` 의 i시점 출력. 피벗 confirmed_ts 경계 케이스 포함.
- 명세 규칙 단위 테스트: 컨펌 3단계(③에서만 CONFIRMED), F1 폐기, 더블 보너스,
  유효 구간 제한(30/70), 플립 후 역할 전환, 휩소(장중 이탈 무시), G2 미달 스킵,
  V1 차단, 점수 연동 사이징(2.5%/5% invariant), TP 50/40/10 체결, BE 트레일링.
- 합성 데이터 fixture로 각 시그널을 결정적으로 재현(기존 테스트 패턴).
- 게이트: `ruff check quantpilot/` + 전체 pytest green 유지.

## 9. Out of Scope (Phase 2/3 defer)

S3 추세선/채널 자동작도, 모드 B(삼각수렴 P1·웻지 P2·F2/F3 플립), 15m 진입 타이밍,
예측 진입 모드(Phase 1 = 확인 진입 고정), 1d/1M 컨텍스트(G4는 4h로 부분 적용),
알람·노티(페이퍼 루프가 이미 봉마감 이벤트 드리븐 — §8 자연 충족), V3(모드 B 전용),
거래량 검증 바이낸스 현물 참조(OKX 볼륨으로 대체, 한계 기록).

## 10. 파라미터 블록 (초기값 — 전부 백테 보정 대상)

```json
{
  "strategy": "confluence", "timeframe": "1h", "htf": "4h",
  "zigzag_atr_k": 3.0,
  "zone": {"cluster_atr_k": 0.5, "min_touches": 2, "proximity_atr_k": 0.25},
  "rsi": {"period": 14, "overbought": 70, "oversold": 30},
  "fib": {"entry_zone": [0.5, 0.618], "target": 0.618},
  "score": {"entry_min": 4, "entry_families": 2, "strong_min": 6, "strong_families": 3},
  "risk": {"base_pct": 5.0, "weak_mult": 0.5, "rr_min": 1.5},
  "veto": {"one_way_lookback": 20, "one_way_ratio": 0.8},
  "tp_ladder": [["first_zone", 0.5], ["fib_0618", 0.4], ["runner", 0.1]],
  "be_trail_after_tp1": true
}
```
