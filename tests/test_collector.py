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


from quantpilot.data.collector import collect_ohlcv, collect_funding, upsert_instruments


class FakeClientForCollect:
    """페이지네이션을 흉내내는 가짜 client.

    since_ms 이후의 봉을 limit개씩 잘라서 돌려줌. 끝나면 빈 리스트.
    """
    def __init__(self, all_rows, kind="ohlcv"):
        self._all = sorted(all_rows, key=lambda r: r["ts"])
        self._kind = kind

    def _page(self, since_ms, limit):
        nxt = [r for r in self._all if r["ts"] >= since_ms][:limit]
        return nxt

    def fetch_ohlcv(self, okx_symbol, timeframe, since_ms, limit=100):
        return self._page(since_ms, limit)

    def fetch_funding(self, okx_symbol, since_ms, limit=100):
        return self._page(since_ms, limit)


def test_collect_ohlcv_backfills_and_drops_unclosed(session):
    tf_ms = 3_600_000
    base = 1_700_000_000_000
    # 5개 봉: 마지막 1개는 미완성이 되도록 now를 설정
    rows = [_candle(base + i * tf_ms) for i in range(5)]
    now = base + 4 * tf_ms + 100  # 5번째 봉(index4)은 아직 안 닫힘
    client = FakeClientForCollect(rows, kind="ohlcv")

    summary = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h",
                            days=1, now_ms=now, page_limit=2)
    from quantpilot.data.models import Candle
    # 미완성 1개 제외 → 4개 저장
    assert session.query(Candle).count() == 4
    assert summary["inserted"] == 4


def test_collect_ohlcv_is_incremental_on_rerun(session):
    tf_ms = 3_600_000
    base = 1_700_000_000_000
    rows = [_candle(base + i * tf_ms) for i in range(4)]
    now = base + 10 * tf_ms  # 전부 닫힘
    client = FakeClientForCollect(rows)

    s1 = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h", days=1, now_ms=now, page_limit=2)
    assert s1["inserted"] == 4
    # 재실행: 신규 0
    s2 = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h", days=1, now_ms=now, page_limit=2)
    assert s2["inserted"] == 0


def test_collect_funding_backfills(session):
    base = 1_700_000_000_000
    eight_h = 8 * 3_600_000
    rows = [{"ts": base + i * eight_h, "funding_rate": 0.0001} for i in range(3)]
    now = base + 100 * eight_h
    client = FakeClientForCollect(rows, kind="funding")
    # WHY days=90: now is ~33 days ahead of base; need lookback > 33 days so
    # since falls before base and all 3 test rows are within the fetch window.
    summary = collect_funding(session, client, "BTC-USDT-SWAP", days=90, now_ms=now, page_limit=2)
    from quantpilot.data.models import FundingRate
    assert session.query(FundingRate).count() == 3
    assert summary["inserted"] == 3


def test_upsert_instruments_writes_row(session):
    import json
    from pathlib import Path

    class FakeClientMarkets:
        def load_markets(self):
            m = json.loads((Path(__file__).parent / "fixtures" / "market_btc.json").read_text())
            return {m["symbol"]: m}

    n = upsert_instruments(session, FakeClientMarkets(), now_ms=1)
    from quantpilot.data.models import Instrument
    assert session.query(Instrument).filter_by(symbol="BTC-USDT-SWAP").one().ct_val == 0.01
    assert n == 1


def test_collect_funding_no_skip_on_variable_cadence(session):
    # 회귀(#1): funding 주기가 8h이 아니라 4h 간격이어도 빠짐 없이 수집돼야 함.
    # page_limit=1로 강제하면, 옛 코드(cursor += 8h)는 base+4h 이벤트를 건너뛴다.
    base = 1_700_000_000_000
    four_h = 4 * 3_600_000
    rows = [{"ts": base + i * four_h, "funding_rate": 0.0001} for i in range(3)]
    now = base + 1000 * four_h
    client = FakeClientForCollect(rows, kind="funding")
    summary = collect_funding(session, client, "BTC-USDT-SWAP", days=365, now_ms=now, page_limit=1)
    from quantpilot.data.models import FundingRate
    assert session.query(FundingRate).count() == 3  # 4h 간격 미스 없이 셋 다
    assert summary["inserted"] == 3


def test_collect_ohlcv_flags_truncation(session):
    # #6: 데이터가 페이지 경계에서 끝나고 now보다 한참 이전이면 truncated=True.
    tf_ms = 3_600_000
    base = 1_700_000_000_000
    rows = [_candle(base + i * tf_ms) for i in range(4)]  # page_limit 배수에 맞춤
    now = base + 50 * tf_ms  # 데이터 끝(base+3tf)이 now보다 한참 전
    client = FakeClientForCollect(rows)
    s = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h", days=365, now_ms=now, page_limit=2)
    assert s["inserted"] == 4
    assert s["truncated"] is True


def test_collect_ohlcv_no_truncation_when_current(session):
    # #6: 데이터가 now 직전까지 있으면 truncated=False(정상 종료).
    tf_ms = 3_600_000
    base = 1_700_000_000_000
    rows = [_candle(base + i * tf_ms) for i in range(4)]
    now = base + 4 * tf_ms + 100  # 마지막 봉 직후 = 현재
    client = FakeClientForCollect(rows)
    s = collect_ohlcv(session, client, "BTC-USDT-SWAP", "1h", days=365, now_ms=now, page_limit=2)
    assert s["truncated"] is False
