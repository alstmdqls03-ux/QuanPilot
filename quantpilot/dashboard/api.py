"""대시보드 상태 JSON 조립(읽기 전용). MINCODE 프런트의 /api/state 응답.

WHY 순수 조립 함수: 서버(HTTP)와 분리해 in-memory DB로 단위 테스트 가능하게 한다.
숫자는 전부 실데이터·실코드(지표는 strategy.indicators, 청산가는 risk.liquidation)에서
나온다 — 프런트는 표시만 한다.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from sqlalchemy import select

from quantpilot.backtest.engine import _pnl
from quantpilot.backtest.metrics import compute_metrics, periods_per_year
from quantpilot.data.models import Candle, FundingRate, Instrument
from quantpilot.paper.models import PaperStateRow
from quantpilot.paper.store import load_equity_curve, load_state, make_run_key, recent_trades
from quantpilot.risk.liquidation import liquidation_price
from quantpilot.risk.sizing import calculate_position_size
from quantpilot.risk.take_profit import build_targets
from quantpilot.strategy.indicators import atr, rsi
from quantpilot.strategy.rsi_mean_reversion import RsiMeanReversion

# 대시보드 표시용 상수 — 페이퍼 CLI 기본값과 동일(quantpilot paper 옵션 기준).
LEVERAGE = 3
RISK_PCT = 5.0
FEE_BPS = 5.0
SLIPPAGE_BPS = 2.0
BREAKER_PCT = 5.0


def _loop_alive() -> bool:
    """페이퍼 루프 프로세스 생존 여부(같은 머신 가정). pgrep 실패 시 False."""
    try:
        r = subprocess.run(["pgrep", "-f", "quantpilot paper --symbol"],
                           capture_output=True, timeout=2)
        return r.returncode == 0
    except Exception:
        return False


def _tail_log(run_key: str, log_dir: str = "logs", n: int = 80) -> list[dict]:
    """회전 로그 파일 마지막 n줄 → [{ts_text, level, text}]. 파일 없으면 빈 리스트."""
    safe = run_key.replace("|", "_")
    path = Path(log_dir) / f"paper-{safe}.log"
    if not path.exists():
        return []
    lines = path.read_text(errors="replace").splitlines()[-n:]
    out = []
    for ln in reversed(lines):
        # 형식: "2026-06-08 14:49:59,619 INFO 메시지"
        parts = ln.split(" ", 3)
        if len(parts) >= 4 and parts[2] in ("INFO", "WARNING", "ERROR"):
            level = {"INFO": "info", "WARNING": "warn", "ERROR": "error"}[parts[2]]
            out.append({"ts_text": parts[1].split(",")[0], "level": level, "text": parts[3]})
        else:
            out.append({"ts_text": "", "level": "info", "text": ln})
    return out


def _position_block(state, price: float, ct_val: float) -> dict | None:
    p = state.position
    if p is None:
        return None
    direction = 1.0 if p.side == "long" else -1.0
    # WHY R=|entry-stop|: 실엔진은 손절선을 옮기지 않으므로(본전 이동 없음) 항상 초기 R.
    r_unit = abs(p.entry - p.stop)
    r_now = ((price - p.entry) * direction / r_unit) if r_unit > 0 else 0.0
    liq = liquidation_price(p.entry, LEVERAGE, p.side)
    unreal = _pnl(p.side, p.entry, price, p.contracts, ct_val)
    pending_net = sum(f.pnl_gross - f.fee for f in state.pending_fills)
    # 손절 시 잔여 손실(추정): 이미 실현된 부분익절 net + 남은 계약이 stop에 청산될 때
    # gross − 예상 청산 수수료 − 진입 수수료. funding 미반영(보유 중 미정산) → '추정' 라벨.
    stop_fee_est = abs(p.contracts * p.stop * ct_val) * (FEE_BPS / 10000.0)
    loss_at_stop = (pending_net + _pnl(p.side, p.entry, p.stop, p.contracts, ct_val)
                    - stop_fee_est - state.open_fee)
    # TP 사다리 전체(1R/2R/3R) 재구성: targets_remaining에 없는 가격 = 체결됨.
    full = build_targets(p.entry, p.stop, p.side)
    remaining_prices = [t[0] for t in p.targets_remaining]
    fills_by_reason = {f.reason: f for f in state.pending_fills}
    ladder = []
    for i, (tp_price, frac) in enumerate(full, start=1):
        filled = not any(abs(tp_price - rp) < 1e-6 for rp in remaining_prices)
        f = fills_by_reason.get(f"tp{i}")
        ladder.append({
            "label": f"TP{i}", "r": float(i), "price": tp_price, "frac": frac,
            "contracts": (f.contracts if f else
                          max(1, round(p.original_contracts * frac))),
            "filled": filled,
            "fill_price": f.price if f else None,
            "fill_ts": f.ts if f else None,
        })
    return {
        "side": p.side, "entry": p.entry, "contracts": p.contracts,
        "original_contracts": p.original_contracts, "stop": p.stop,
        "opened_ts": p.opened_ts, "r_unit": r_unit, "r_now": r_now,
        "liq": liq, "liq_gap_pct": abs(price - liq) / price * 100 if price else 0.0,
        "unrealized": unreal, "loss_at_stop": loss_at_stop,
        "open_fee": state.open_fee,
        "fees_accum": state.open_fee + sum(f.fee for f in state.pending_fills),
        "realized_partial_net": pending_net,
        "ladder": ladder,
        "pending_fills": [{"ts": f.ts, "price": f.price, "contracts": f.contracts,
                           "fee": f.fee, "reason": f.reason, "pnl_gross": f.pnl_gross}
                          for f in state.pending_fills],
    }


def build_state(session, symbol: str = "BTC-USDT-SWAP", timeframe: str = "1h",
                strategy: str = "rsi-mr", n_candles: int = 120,
                log_dir: str = "logs") -> dict:
    """대시보드 한 화면에 필요한 전체 상태를 dict로 조립(JSON 직렬화 가능)."""
    rk = make_run_key(symbol, timeframe, strategy)
    now_ms = int(time.time() * 1000)
    strat = RsiMeanReversion(timeframe=timeframe)

    if session.get(PaperStateRow, rk) is None:
        return {"run": False, "run_key": rk,
                "hint": "페이퍼 런 없음 — ./scripts/run-paper.sh 로 시작하세요."}

    inst = session.execute(select(Instrument).where(
        Instrument.symbol == symbol)).scalar_one_or_none()
    ct_val = inst.ct_val if inst else 0.01

    rows = session.execute(
        select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
        .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
        .order_by(Candle.ts.desc()).limit(n_candles)).all()
    candles = [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5] or 0.0}
               for r in reversed(rows)]

    rsi_vals: list[float | None] = []
    atr_last = None
    if len(candles) >= strat.rsi_period + 1:
        import pandas as pd
        closes = pd.Series([c["c"] for c in candles])
        highs = pd.Series([c["h"] for c in candles])
        lows = pd.Series([c["l"] for c in candles])
        rs = rsi(closes, strat.rsi_period)
        rsi_vals = [None if pd.isna(v) else float(v) for v in rs]
        atr_last = float(atr(highs, lows, closes, strat.atr_period).iloc[-1])

    state = load_state(session, rk, symbol=symbol, timeframe=timeframe,
                       strategy=strategy, capital=0.0, day_start_ts=0)
    price = candles[-1]["c"] if candles else (
        state.position.entry if state.position else 0.0)

    # 다음 진입 사이징 미리보기 — 실제 사이징 함수로 계산(불변식 동일).
    next_max_loss = None
    if atr_last and state.position is None and price:
        stop_preview = price - strat.atr_k * atr_last
        try:
            sz = calculate_position_size(state.equity, RISK_PCT / 100.0, price,
                                         stop_preview, ct_val, inst.lot_sz if inst else 1.0,
                                         leverage=LEVERAGE, fee_bps=FEE_BPS,
                                         slippage_bps=SLIPPAGE_BPS)
            # invariant와 동일 정의: max_loss + 왕복 수수료 추정 ≤ 자본×5%
            fee_est = sz.contracts * price * ct_val * (FEE_BPS / 10000.0) * 2
            next_max_loss = sz.max_loss_usd + fee_est
        except Exception:
            next_max_loss = None    # 사이징 불가(자본 부족 등) → 표시 생략

    trades = recent_trades(session, rk, 500)
    curve = load_equity_curve(session, rk)
    metrics = (compute_metrics(curve, trades, periods_per_year(timeframe))
               if len(curve) >= 2 else None)
    if metrics and metrics.get("profit_factor") == float("inf"):
        metrics = {**metrics, "profit_factor": None}   # JSON엔 Infinity 없음

    fr = session.execute(
        select(FundingRate.ts, FundingRate.funding_rate)
        .where(FundingRate.symbol == symbol)
        .order_by(FundingRate.ts.desc()).limit(1)).first()

    pos = _position_block(state, price, ct_val)
    equity_now = state.equity + (pos["unrealized"] if pos else 0.0)

    last_bar_ts = candles[-1]["ts"] if candles else None
    return {
        "run": True, "run_key": rk, "symbol": symbol, "timeframe": timeframe,
        "strategy": strategy, "now_ms": now_ms,
        "loop_alive": _loop_alive(),
        "halted": state.halted, "panic_halted": state.panic_halted,
        "last_processed_bar_ts": state.last_processed_bar_ts,
        "last_bar_ts": last_bar_ts,
        "freshness_sec": ((now_ms - last_bar_ts) // 1000) if last_bar_ts else None,
        "price": price,
        "prev_close": candles[-2]["c"] if len(candles) >= 2 else price,
        "equity": equity_now, "realized_equity": state.equity,
        "day_start_equity": state.day_start_equity,
        "daily_realized_pnl": state.daily_realized_pnl,
        "breaker": {"pct": BREAKER_PCT,
                    "limit_usd": state.day_start_equity * BREAKER_PCT / 100.0,
                    "used_usd": max(0.0, -state.daily_realized_pnl)},
        "position": pos,
        "next_trade_max_loss": next_max_loss,
        "params": {"riskPct": RISK_PCT, "leverage": LEVERAGE,
                   "rsiPeriod": strat.rsi_period, "atrPeriod": strat.atr_period,
                   "entryLow": strat.low, "entryHigh": strat.high,
                   "exitLow": strat.exit_band[0], "exitHigh": strat.exit_band[1],
                   "atrK": strat.atr_k, "takerBps": FEE_BPS, "slipBps": SLIPPAGE_BPS,
                   "breakerPct": BREAKER_PCT, "ctVal": ct_val,
                   "tpR": [1.0, 2.0, 3.0], "tpFrac": [0.33, 0.33, 0.34],
                   "fundingRate": fr[1] if fr else None,
                   "fundingTs": fr[0] if fr else None},
        "candles": candles,
        "rsi": rsi_vals,
        "equity_curve": [[ts, eq] for ts, eq in curve],
        "trades": [{"side": t.side, "entry": t.entry, "exit": t.exit,
                    "contracts": t.contracts, "pnl_gross": t.pnl_gross,
                    "fees": t.fees, "funding": t.funding, "pnl_net": t.pnl_net,
                    "opened_ts": t.opened_ts, "closed_ts": t.closed_ts,
                    "reason": t.reason} for t in trades],
        "metrics": metrics,
        "logs": _tail_log(rk, log_dir),
    }
