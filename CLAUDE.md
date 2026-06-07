# QuantPilot — 프로젝트 가이드 (Claude Code)

OKX 암호화폐 선물 **자동매매 edge-finding 인프라**. 특정 봇 하나가 아니라, 전략을
발굴·검증하는 시스템. 내 돈(소액)으로 운영. 선물, 3–5x 레버리지, per-trade 5% 리스크.

## 리스크 게이트 (가장 중요)
**실거래(진짜 돈)는 Week 5+ 전까지 절대 없음.** data → backtest → paper → validate를
전부 **$0 리스크**로 통과한 뒤에만 실거래. 이 순서를 건너뛰자는 제안은 거절.

## 현재 상태 / 로드맵
- **Week 1 — 데이터 수집** ✅ merged (OKX 캔들+funding → SQLite, API키 불필요)
- **Week 2 — 백테스트 엔진** ✅ merged (`main` 기준; 지표·전략·리스크·엔진·리포트·CLI)
- **Week 3 — 페이퍼 트레이더** ⬅️ 다음. Week 2 엔진(`backtest.engine.check_exits`,
  `strategy.base.IStrategy`, `risk` 사이징)을 **그대로 재사용** + 리스크 게이트 + kill switch
- **Week 4 — 하드닝 + 7일 페이퍼런**
- 실거래 전 필수 숙제는 항상 `TODOS.md`의 **pre-live blocker** 섹션 참고.

## 작업 방식 (한 Week씩, 스킬 라우팅)
요청이 "다음 단계 가자" 류면 아래 순서의 다음 단계를 자동 진행한다:
1. `/brainstorming` (또는 범위가 모호하면 `/office-hours`) — 설계
2. `/spec` 또는 설계 문서 → spec 작성 후 git commit
3. `/superpowers:using-git-worktrees` — `.claude/worktrees/`에 격리 작업공간
4. `/superpowers:writing-plans` — TDD task로 분해
5. `/superpowers:executing-plans` (subagent-driven) — task마다 **fresh 서브에이전트**로
   RED→GREEN→commit, 그 뒤 2단계 리뷰(스펙 준수 → 코드 품질)
6. `/superpowers:finishing-a-development-branch` → `/review`(+ Codex 크로스모델) → CLI QA → merge
7. `배포`/`ship` → 테스트 통과 시 origin push

## 코드 컨벤션 (반드시 지킬 것)
- **WHY 주석 필수**: DB 스키마·금융 로직(사이징·PnL·청산·funding)엔 "왜 이렇게 했는지"를
  항상 남긴다. 사용자가 명시적으로 요청한 규칙.
- **테이블/ERD 최소화**: 새 테이블·관계는 꼭 필요한 것만.
- **수학은 직접 구현·소유**: 지표(RSI/ATR/EMA 등)는 손으로 구현. pandas-ta/ta-lib 같은
  블랙박스 의존성 금지. 디버깅 가능해야 함.
- **TDD 필수**: 구현 전 실패 테스트(RED) 먼저 확인 → 구현(GREEN) → commit.
- **리스크 불변식은 assert로 강제**: per-trade 5% (max_loss + fee + 손절 슬리피지 ≤ 예산).
- **백테=실전 일치**: 엔진은 per-bar step 함수로 짜서 Week 3 페이퍼가 그대로 재사용.
- **손절 먼저(보수 가정)**: 한 봉이 stop·TP 동시 터치 시 stop 먼저 체결로 가정.

## 사용자 컨텍스트
- 트레이딩/봇 **초보자**. 진행하면서 개념을 **설명**해줄 것. 답변은 **한국어**.
- 한 번에 한 Week만. 큰 결정은 선택지를 제시하고 물어볼 것.

## 스택 / 함정
- Python **3.12** (ccxt, SQLAlchemy, pydantic-settings, click, pandas, numpy, matplotlib, pytest).
  venv는 반드시 `python3.12 -m venv .venv`로 생성 — 시스템 python3.9면 editable install 깨짐.
- 린트 게이트: **`ruff check quantpilot/`** (소스). 테스트 파일 린트 빚은 별도 관리.
- 네이티브 worktree는 `.claude/worktrees/` 아래 (EnterWorktree).
- **절대 `git add -A` 금지** — `.claude/`·`.planning/`·`.env` 사고 위험. 의도한 파일만 stage.
- **`.env` 절대 커밋 금지.**

## 배포 (`배포`/`ship` 키워드)
1. `pytest` 전체 실행 (전역 CLAUDE.md의 `apps/api` 경로는 무시 — QuantPilot은 루트 패키지)
2. 실패 시 보고하고 중단(commit/push 안 함)
3. 통과 시: 의도한 변경만 commit(conventional) → `git push origin main`
4. 커밋 메시지는 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`로 끝맺음
