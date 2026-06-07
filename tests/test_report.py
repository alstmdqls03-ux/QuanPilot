from quantpilot.backtest.models import BacktestResult
from quantpilot.backtest.report import format_console, save_equity_png


def _result():
    curve = [(1_700_000_000_000 + i * 3_600_000, 1000.0 + i) for i in range(20)]
    return BacktestResult(trades=[], equity_curve=curve, split_ts=curve[10][0],
                          train_metrics={"sharpe": 1.2, "max_drawdown": -0.1,
                                         "total_return": 0.05, "n_trades": 3,
                                         "win_rate": 0.66, "profit_factor": 1.8},
                          oos_metrics={"sharpe": 0.7, "max_drawdown": -0.12,
                                       "total_return": 0.02, "n_trades": 1,
                                       "win_rate": 1.0, "profit_factor": 2.0})


def test_console_has_train_and_oos():
    out = format_console(_result(), symbol="BTC-USDT-SWAP", strategy="rsi-mr")
    assert "Train" in out and "OOS" in out
    assert "1.2" in out and "0.7" in out   # train/OOS Sharpe


def test_save_png_creates_file(tmp_path):
    path = tmp_path / "eq.png"
    save_equity_png(_result(), str(path))
    assert path.exists() and path.stat().st_size > 0
