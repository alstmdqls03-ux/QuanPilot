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

머지 전 CRITICAL(부분익절 실현손익 즉시 반영) + 유지보수 전부 수정 완료.
아래는 보수적이거나 MVP에 영향 적어 **의도적으로 deferred**한 모델 정밀도 항목.

- [ ] **funding을 보유 구간별 실제 보유 수량으로 정산** — 현재 `_finalize`는 funding을
  `original_contracts` 기준 원 notional로 보유 구간 전체에 일괄 부과한다. 부분익절로
  수량이 줄어든 뒤에도 원 수량으로 과금 → funding 과다 청구(부분익절 ladder에서 ~20-30%).
  방향은 보수적(비용 과대 → 나쁜 전략을 좋게 보이게 못 함)이라 MVP는 OK. 실거래 전 정밀화.
  (Claude adversarial #2, conf 8)
- [ ] **sizing 5% invariant에 청산 슬리피지 포함** — 사이징은 raw stop 가격 손실로
  5% 예산을 잡지만, 엔진은 stop을 슬리피지만큼 불리하게 체결한다. 실제 최악 손실이
  예산을 슬리피지분 초과. 2bps에선 미미하나 실거래 전 stop±slippage로 사이징하거나
  "5% 한도는 슬리피지 제외" 명시. (Claude adversarial #3, conf 7)
- [ ] **metrics가 equity≤0(청산 근접) 경로를 -100%로 surface** — `sharpe._returns`는
  직전 equity가 0인 봉을 건너뛰고, `max_drawdown`은 peak>0에서만 갱신해 파산 경로의
  최악 낙폭을 과소 보고할 수 있다. 5% 위험이라 발생 가능성 낮지만 가드 추가 권장.
  (Claude adversarial #6, conf 6)

## 유지보수 (cosmetic, 급하지 않음) — Week 1 테스트 린트 빚

- [ ] `tests/test_cli.py` 미사용 import 3개(make_engine/make_session_factory/init_db) 제거.
- [ ] `tests/test_collector.py` E402(모듈 import가 파일 상단 아님) 정리 — 의도적 구조면 noqa.
  (Week 2 브랜치에선 소스 게이트 `ruff check quantpilot/`만 적용; 테스트 린트는 별도 정리.)
