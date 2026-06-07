from quantpilot.backtest.metrics import compute_metrics, sharpe, max_drawdown


def test_max_drawdown_known_curve():
    curve = [(0, 100.0), (1, 120.0), (2, 90.0), (3, 110.0)]  # 120→90 = -25%
    assert abs(max_drawdown(curve) - (-0.25)) < 1e-9


def test_sharpe_zero_when_flat():
    curve = [(i, 100.0) for i in range(10)]  # 변화 없음 → 수익 0
    assert sharpe(curve, periods_per_year=8760) == 0.0


def test_sharpe_positive_for_uptrend():
    curve = [(i, 100.0 * (1.001 ** i)) for i in range(200)]  # 꾸준 상승
    assert sharpe(curve, periods_per_year=8760) > 0


def test_compute_metrics_keys():
    curve = [(i, 100.0 + i) for i in range(50)]
    m = compute_metrics(curve, trades=[], periods_per_year=8760)
    for k in ("sharpe", "max_drawdown", "total_return", "n_trades", "win_rate", "profit_factor"):
        assert k in m
