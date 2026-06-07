from quantpilot.data.collector import drop_unclosed


def test_drop_unclosed_removes_forming_candle():
    tf_ms = 3_600_000  # 1h
    now = 1_700_007_200_000  # 두 번째 봉이 막 열린 시점(아직 안 닫힘)
    rows = [
        {"ts": 1_700_000_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": 1_700_003_600_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": 1_700_007_200_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ]
    kept = drop_unclosed(rows, tf_ms, now)
    # 마지막 봉(ts=...7_200_000)은 ts+tf(...10_800_000) > now 라서 미완성 → 제거.
    # 첫 두 봉은 닫혔으므로 유지.
    assert [r["ts"] for r in kept] == [1_700_000_000_000, 1_700_003_600_000]


def test_drop_unclosed_keeps_all_when_old():
    tf_ms = 3_600_000
    now = 1_800_000_000_000  # 충분히 미래 → 전부 닫힘
    rows = [{"ts": 1_700_000_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    assert len(drop_unclosed(rows, tf_ms, now)) == 1


from quantpilot.data.collector import (
    last_candle_ts, upsert_candles, last_funding_ts, upsert_funding,
)


def _candle(ts, close=100.0):
    return {"ts": ts, "open": 1, "high": 1, "low": 1, "close": close, "volume": 1}


def test_last_candle_ts_none_when_empty(session):
    assert last_candle_ts(session, "okx", "BTC-USDT-SWAP", "1h") is None


def test_upsert_candles_inserts_and_is_idempotent(session):
    rows = [_candle(1_700_000_000_000), _candle(1_700_003_600_000)]
    new1 = upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=1)
    assert new1 == 2
    # 같은 데이터 재삽입 → 신규 0, 중복 없음
    new2 = upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=1)
    assert new2 == 0
    from quantpilot.data.models import Candle
    assert session.query(Candle).count() == 2


def test_last_candle_ts_returns_max(session):
    rows = [_candle(1_700_000_000_000), _candle(1_700_003_600_000)]
    upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=1)
    assert last_candle_ts(session, "okx", "BTC-USDT-SWAP", "1h") == 1_700_003_600_000


def test_upsert_funding_idempotent(session):
    rows = [{"ts": 1_700_000_000_000, "funding_rate": 0.0001}]
    assert upsert_funding(session, "okx", "BTC-USDT-SWAP", rows, now_ms=1) == 1
    assert upsert_funding(session, "okx", "BTC-USDT-SWAP", rows, now_ms=1) == 0
    assert last_funding_ts(session, "okx", "BTC-USDT-SWAP") == 1_700_000_000_000
