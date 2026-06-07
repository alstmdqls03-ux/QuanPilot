"""백테스트 결과 출력 — 콘솔 표 + equity curve PNG."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # WHY Agg: 헤드리스(서버/CI)에서 화면 없이 PNG 저장
import matplotlib.pyplot as plt  # noqa: E402

from quantpilot.backtest.models import BacktestResult  # noqa: E402

_KEYS = [("sharpe", "Sharpe"), ("max_drawdown", "MaxDD"),
         ("total_return", "Return"), ("win_rate", "WinRate"),
         ("profit_factor", "PF"), ("n_trades", "Trades")]


def format_console(result: BacktestResult, symbol: str, strategy: str) -> str:
    """Train | OOS 표 텍스트."""
    t, o = result.train_metrics, result.oos_metrics
    lines = [f"Backtest: {strategy} on {symbol}",
             f"{'Metric':<10}{'Train':>12}{'OOS':>12}"]
    for key, label in _KEYS:
        lines.append(f"{label:<10}{str(t.get(key, '-')):>12}{str(o.get(key, '-')):>12}")
    # 과최적화 힌트
    if t.get("sharpe", 0) and o.get("sharpe", 0) is not None:
        if t.get("sharpe", 0) > 1.0 and o.get("sharpe", 0) < t.get("sharpe", 0) * 0.5:
            lines.append("⚠️  Train≫OOS Sharpe — 과최적화 의심")
    return "\n".join(lines)


def save_equity_png(result: BacktestResult, path: str) -> None:
    """train(파랑)+OOS(주황) equity curve, 분리선 포함 PNG 저장."""
    ts = [t for t, _ in result.equity_curve]
    eq = [e for _, e in result.equity_curve]  # noqa: F841
    split = result.split_ts
    fig, ax = plt.subplots(figsize=(10, 5))
    train_x = [t for t in ts if t < split]
    train_y = [e for t, e in result.equity_curve if t < split]
    oos_x = [t for t in ts if t >= split]
    oos_y = [e for t, e in result.equity_curve if t >= split]
    ax.plot(train_x, train_y, color="tab:blue", label="Train")
    ax.plot(oos_x, oos_y, color="tab:orange", label="OOS")
    ax.axvline(split, color="gray", linestyle="--", linewidth=1)
    ax.set_xlabel("ts (ms)")
    ax.set_ylabel("equity (USDT)")
    ax.legend()
    ax.set_title("Equity Curve")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
