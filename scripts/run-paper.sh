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

echo "[run-paper] 데이터 시드: $SYMBOL $TIMEFRAME"
quantpilot collect --symbol "$SYMBOL" --timeframe "$TIMEFRAME" --days 30
quantpilot collect-funding --symbol "$SYMBOL" --days 30

echo "[run-paper] 페이퍼 루프 시작 (poll ${POLL}s). 중단: 이 창에서 Ctrl-C, 비상정지: 다른 셸에서 'quantpilot panic'."
exec quantpilot paper --symbol "$SYMBOL" --timeframe "$TIMEFRAME" --strategy "$STRATEGY" --poll-seconds "$POLL"
