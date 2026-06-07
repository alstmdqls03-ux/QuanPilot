"""백테스트 성과 지표. Sharpe는 per-bar 자본 수익률 기준(spec 11)."""
from __future__ import annotations

import math


def _returns(curve: list[tuple[int, float]]) -> list[float]:
    eq = [e for _, e in curve]
    return [(eq[i] / eq[i - 1] - 1.0) for i in range(1, len(eq)) if eq[i - 1] != 0]


def sharpe(curve: list[tuple[int, float]], periods_per_year: float) -> float:
    """per-bar 수익률의 평균/표준편차 × √연환산. rf=0 가정."""
    rets = _returns(curve)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def max_drawdown(curve: list[tuple[int, float]]) -> float:
    """최대 낙폭(음수 비율). 고점 대비 최대 하락."""
    peak = -math.inf
    mdd = 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return mdd


def compute_metrics(curve, trades, periods_per_year: float) -> dict:
    """곡선 + 거래 목록 → 지표 dict (net 기준)."""
    eq = [e for _, e in curve]
    total_return = (eq[-1] / eq[0] - 1.0) if len(eq) >= 2 and eq[0] != 0 else 0.0
    wins = [t for t in trades if t.pnl_net > 0]
    losses = [t for t in trades if t.pnl_net < 0]
    gross_profit = sum(t.pnl_net for t in wins)
    gross_loss = abs(sum(t.pnl_net for t in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    return {
        "sharpe": round(sharpe(curve, periods_per_year), 3),
        "max_drawdown": round(max_drawdown(curve), 4),
        "total_return": round(total_return, 4),
        "n_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0.0,
        "profit_factor": round(pf, 3) if pf != float("inf") else pf,
    }


def periods_per_year(timeframe: str) -> float:
    """연환산 계수. 1h → 24×365, 15m → 96×365."""
    from quantpilot.timeframes import timeframe_to_ms
    tf_ms = timeframe_to_ms(timeframe)
    bars_per_day = 86_400_000 / tf_ms
    return bars_per_day * 365
