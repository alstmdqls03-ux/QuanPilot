# QuantPilot TODOs

`/review`(Claude + Codex 크로스모델 adversarial)에서 나온 데이터 정합성 항목 중,
Week 1 머지 시점에 **고치지 않고 의도적으로 미룬** 것들. 대부분 실거래(Week 3+) 진입
전에는 반드시 다시 봐야 한다. (싼 항목 #1/#4/#6/#7은 머지 전 수정 완료.)

## 실거래 전 필수 (pre-live blockers)

- [ ] **candle finality를 OKX `confirm` 필드로 판정** — 현재 `drop_unclosed`는 로컬
  `now_ms`(벽시계)로 봉 마감을 추정한다. ccxt가 OKX의 `confirm` 필드를 버려서
  교환소 기준 마감을 확인 못 함. 로컬 시계가 OKX보다 밀리면 닫힌 봉을 잘못 버려
  1봉 지연이 생긴다. → raw OKX `/api/v5/market/candles`의 `confirm`을 쓰거나,
  NTP 동기(`time_sync`)를 강제. (cross-model 확인: Claude #7 + Codex)

- [ ] **연속성 검증 + gap 재수집** — `max(ts)` 워터마크 + short-page break 구조라,
  중간에 한 봉이 빠지면 다음 실행이 그 구멍을 다시 안 받아 **영구 hole**이 된다.
  (spec section 10에서 "gap 자동 재수집 = post-MVP"로 이미 deferred했으나,
  cross-model 둘 다 HIGH로 재확인: Claude #5 + Codex.) 실거래/백테스트 전
  연속성 체크(예상 ts 그리드 vs 실제) + 빠진 구간 재요청 추가.

- [ ] **funding realizedRate vs fundingRate 확인** — ccxt
  `fetch_funding_rate_history`가 실현(realized) funding을 주는지, 예측(predicted)을
  주는지 검증. 예측값을 과거 테이블에 넣으면 백테스트 carry 비용이 틀림. (Codex medium)

## 데이터 의미 (document / 검증)

- [ ] **`Candle.volume` 단위 확정** — ccxt OHLCV[5]가 OKX 선물에서 base-asset(BTC)
  볼륨인지 계약 수인지 실데이터로 확인하고 주석/스키마에 확정. Week 2 sizing이
  `ct_val`로 환산해 쓰기 전 필수. (머지 전: 주석을 "단정 금지"로 완화해둠.)

- [ ] **중복 ts·다른 값 처리 정책** — `on_conflict_do_nothing`이라 잘못 쓰인 첫 값이
  영구 보존된다(idempotency는 "동일 행"에만 성립). 닫힌 봉은 불변이라 보통 OK지만,
  거래소 정정·첫 쓰기 오류 시 갱신할지 정책 결정. (Codex)

## 유지보수 (cosmetic, 급하지 않음)

- [ ] `cli.py _session()`이 안 쓰는 `settings`를 튜플로 반환 — `return session`만으로 단순화.
- [ ] `collect-funding`이 `upsert_instruments`를 스킵 — funding만 돌린 신규 DB는
  Instrument 캐시가 비어 Week 2 sizing이 실패할 수 있음. 호출 추가하거나 주석으로 명시.
- [ ] `cli.py`의 `OKXClient` inline import 2곳 → 모듈 상단으로 (순환참조 없음).
- [ ] `collector.py` funding 8h를 모듈 상수(`FUNDING_INTERVAL_MS`)로 (현재 trunc 판정용 지역변수).

## Week 2 백테스트 /review 미뤄둔 항목 (실거래 전 재검토)

머지 전 수정 완료: CRITICAL(부분익절 실현손익 즉시 반영) + 유지보수 7개 + sizing
슬리피지 불변식(Codex #1) + 테스트 공백. 아래는 cross-model(Claude+Codex)이
**pre-live blocker**로 합의했으나 Week 2(인프라 검증, $0)엔 영향 적어 deferred.

- [ ] **[pre-live] funding을 보유 구간별 실제 보유 수량으로 정산** — `_build_trade`는
  funding을 `original_contracts` 기준 원 notional로 보유 구간 전체에 일괄 부과한다.
  부분익절로 수량이 줄어든 뒤에도 원 수량으로 계산 → **롱은 과다 청구(보수적), 숏은
  과다 수취(낙관적 — 숏 PnL을 부풀림)**. 숏 방향은 보수적이지 않으므로 실거래 전 필수.
  보유 sub-window별 실제 수량으로 funding 누적하도록 수정. (Claude #2 + Codex #2)
- [ ] **[pre-live] funding을 보유 중에도 equity 곡선에 반영 + 종료 시 미청산 포지션도 청구**
  — 현재 funding은 청산 시 일괄 차감이라 보유 중 곡선(Sharpe/MaxDD)엔 빠져 있고,
  백테스트 끝에 열린 채 남은 포지션은 funding이 한 번도 안 걸린다. (Codex #3)
- [ ] **[pre-live] metrics가 equity≤0(청산 근접) 경로를 -100%로 surface** —
  `sharpe._returns`는 직전 equity가 0인 봉을 건너뛰고 `max_drawdown`은 peak>0에서만
  갱신해 파산 경로의 최악 낙폭을 과소 보고할 수 있다. (Claude #6 + Codex)
- [ ] **OOS 거래 지표가 train 구간 PnL을 포함할 수 있음** — `cli.py`가 OOS 거래를
  `closed_ts >= split_ts`로 가르므로, train에서 열고 OOS에서 닫은 거래가 train 손익까지
  OOS 승률/PF에 들어간다. 곡선 기반 지표(Sharpe/MaxDD)는 ts로 정확히 분리됨. 거래 지표는
  `opened_ts` 기준 분리하거나 straddling 거래 제외. (Codex #6)
- [ ] **1계약 포지션은 분할익절이 안 됨** — `[0.33,0.33,0.34]` × 1계약은 모든 타겟
  수량이 round→0이라 TP가 한 번도 안 걸리고 stop/exit로만 청산. 소액 계좌 엣지케이스.
  마지막 타겟이 잔량을 받도록(floor) 보정 검토. (Codex #7)

## 유지보수 (cosmetic, 급하지 않음) — Week 1 테스트 린트 빚

- [ ] `tests/test_cli.py` 미사용 import 3개(make_engine/make_session_factory/init_db) 제거.
- [ ] `tests/test_collector.py` E402(모듈 import가 파일 상단 아님) 정리 — 의도적 구조면 noqa.
  (Week 2 브랜치에선 소스 게이트 `ruff check quantpilot/`만 적용; 테스트 린트는 별도 정리.)
