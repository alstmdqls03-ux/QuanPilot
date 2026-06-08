#!/usr/bin/env bash
# 7일 페이퍼런 런처: 데이터 시드 후 페이퍼 루프 시작.
# 사용: tmux new -s paper → ./scripts/run-paper.sh → Ctrl-b d (detach)
set -euo pipefail

SYMBOL="${SYMBOL:-BTC-USDT-SWAP}"
TIMEFRAME="${TIMEFRAME:-1h}"
STRATEGY="${STRATEGY:-rsi-mr}"
POLL="${POLL:-60}"

# venv 활성화(워크트리/루트 어디서 실행하든)
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi

# WHY 시드 3일만: 첫 틱은 last_processed_bar_ts=None이라 적재된 과거 봉을 전부 replay한다.
# 30일을 시드하면 "7일 런" 리포트가 30일 과거 replay로 오염됨(/review Codex 지적). 지표 계산
# warmup(lookback≈42봉≈2일)에 필요한 최소치만 시드 → 곡선이 라이브 위주가 되게 한다.
# (과거 데이터 축적이 따로 필요하면 `quantpilot collect --days N`을 수동 실행. 진짜 live-from-now는
#  TODOS Week 5: 첫 런에서 과거 replay 없이 '지금'부터 시작하는 옵션.)
SEED_DAYS="${SEED_DAYS:-3}"
echo "[run-paper] 데이터 시드(warmup ${SEED_DAYS}일): $SYMBOL $TIMEFRAME"
quantpilot collect --symbol "$SYMBOL" --timeframe "$TIMEFRAME" --days "$SEED_DAYS"
quantpilot collect-funding --symbol "$SYMBOL" --days "$SEED_DAYS"

echo "[run-paper] 페이퍼 루프 시작 (poll ${POLL}s). 중단: 이 창에서 Ctrl-C, 비상정지: 다른 셸에서 'quantpilot panic'."
exec quantpilot paper --symbol "$SYMBOL" --timeframe "$TIMEFRAME" --strategy "$STRATEGY" --poll-seconds "$POLL"
