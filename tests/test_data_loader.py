
from quantpilot.backtest.data_loader import detect_gaps, load_candles_df
from quantpilot.data.models import Candle


def _add_candle(session, ts, close=100.0):
    session.add(Candle(exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
                       ts=ts, open=close, high=close, low=close, close=close,
                       volume=1.0, inserted_at=1))


def test_detect_gaps_finds_holes():
    tf = 3_600_000
    base = 1_700_000_000_000
    # 0,1,3 봉 존재 (2번 누락)
    ts_list = [base, base + tf, base + 3 * tf]
    gaps, ranges = detect_gaps(ts_list, tf)
    assert gaps == 1
    assert ranges  # 누락 구간 보고됨


def test_detect_gaps_none_when_contiguous():
    tf = 3_600_000
    base = 1_700_000_000_000
    ts_list = [base + i * tf for i in range(5)]
    gaps, ranges = detect_gaps(ts_list, tf)
    assert gaps == 0


def test_load_candles_df(session):
    tf = 3_600_000
    base = 1_700_000_000_000
    for i in range(3):
        _add_candle(session, base + i * tf, close=100.0 + i)
    session.commit()
    df = load_candles_df(session, "BTC-USDT-SWAP", "1h")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3
    assert df.index.name == "ts"
    assert df["close"].iloc[-1] == 102.0
