"""표시 레이어(quantpilot.paper.display) 단위 테스트.

WHY 순수 함수 테스트: 손익/리스크 계산은 engine·store가 소유하고 여기는 '이미
확정된 숫자'를 사람이 읽기 쉽게 포맷팅만 한다. DB 없이 빠르게 검증 가능해야 함.
"""
from types import SimpleNamespace

from quantpilot.paper.display import (
    fmt_money,
    fmt_price,
    fmt_trade_line,
    fmt_ts,
    reason_kr,
    side_kr,
    summarize_trades,
)


def _t(**kw):
    base = dict(
        side="short", entry=62586.08, exit=61704.04, contracts=4,
        pnl_net=32.80, closed_ts=1780837200000, reason="exit_signal",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_fmt_money_sign():
    assert fmt_money(32.8) == "+$32.80"
    assert fmt_money(-8.5) == "-$8.50"
    assert fmt_money(0.0) == "+$0.00"


def test_side_kr():
    assert side_kr("long") == "롱"
    assert side_kr("short") == "숏"


def test_reason_kr_maps_known_and_passes_unknown():
    assert reason_kr("exit_signal") == "RSI중립복귀"
    assert reason_kr("stop") == "손절"
    assert reason_kr("tp1") == "분할익절"
    assert reason_kr("tp3") == "분할익절"
    assert reason_kr("panic") == "비상정지"
    # 미지의 사유는 원문을 그대로 노출(정보 손실 방지)
    assert reason_kr("weird") == "weird"


def test_fmt_ts_is_utc_minute():
    # 1780837200000 ms == 2026-06-07 13:00 UTC (거래소/캔들 ts는 UTC 기준)
    assert fmt_ts(1780837200000) == "06-07 13:00"


def test_fmt_price_large_rounds_small_keeps_decimals():
    assert fmt_price(62586.08) == "62,586"
    assert fmt_price(1.2345) == "1.2345"


def test_fmt_trade_line_profit_has_win_marker():
    line = fmt_trade_line(_t(pnl_net=32.80, side="short", reason="exit_signal"))
    assert "✅ 이익" in line
    assert "숏" in line
    assert "+$32.80" in line
    assert "RSI중립복귀" in line


def test_fmt_trade_line_loss_has_loss_marker():
    line = fmt_trade_line(_t(pnl_net=-8.5, side="long", reason="stop"))
    assert "❌ 손실" in line
    assert "롱" in line
    assert "-$8.50" in line
    assert "손절" in line


def test_summarize_trades_counts_winrate_and_realized():
    trades = [_t(pnl_net=32.80), _t(pnl_net=15.29)]
    s = summarize_trades(trades)
    assert "2건" in s
    assert "✅ 2" in s
    assert "❌ 0" in s
    assert "+$48.09" in s
    assert "100%" in s


def test_summarize_trades_mixed_winrate():
    trades = [_t(pnl_net=10.0), _t(pnl_net=-4.0)]
    s = summarize_trades(trades)
    assert "✅ 1" in s
    assert "❌ 1" in s
    assert "50%" in s
    assert "+$6.00" in s


def test_summarize_trades_empty():
    s = summarize_trades([])
    assert "0건" in s
