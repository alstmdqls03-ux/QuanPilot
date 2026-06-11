"""gap 메우기: 기존 데이터의 누락 구간만 재요청해 채운다."""
from quantpilot.data.collector import heal_gaps, upsert_candles

HOUR = 3_600_000
T0 = 1_780_000_000_000


class FakeClient:
    """요청 구간의 캔들을 돌려주는 가짜 클라이언트(결정적)."""
    def __init__(self):
        self.calls = []

    def fetch_ohlcv(self, symbol, timeframe, since_ms, limit):
        self.calls.append(since_ms)
        return [{"ts": since_ms + i * HOUR, "open": 1.0, "high": 2.0,
                 "low": 0.5, "close": 1.5, "volume": 3.0} for i in range(limit)]


def _seed(session, ts_list):
    rows = [{"ts": t, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
             "volume": 3.0} for t in ts_list]
    upsert_candles(session, "okx", "BTC-USDT-SWAP", "1h", rows, now_ms=T0 + 100 * HOUR)


def test_heal_fills_interior_gap(session):
    _seed(session, [T0 + i * HOUR for i in [0, 1, 2, 3, 4, 8, 9, 10]])
    client = FakeClient()
    r = heal_gaps(session, client, "BTC-USDT-SWAP", "1h", now_ms=T0 + 100 * HOUR)
    assert r["gaps_found"] == 3
    assert r["inserted"] == 3
    from quantpilot.backtest.data_loader import load_candles_df, detect_gaps
    df = load_candles_df(session, "BTC-USDT-SWAP", "1h")
    missing, _ = detect_gaps(list(df.index), HOUR)
    assert missing == 0
    assert client.calls[0] == T0 + 5 * HOUR


def test_heal_noop_when_continuous(session):
    _seed(session, [T0 + i * HOUR for i in range(5)])
    r = heal_gaps(session, FakeClient(), "BTC-USDT-SWAP", "1h", now_ms=T0 + 100 * HOUR)
    assert r == {"gaps_found": 0, "inserted": 0}


def test_heal_multipage_advances_cursor(session):
    # gap 5봉 > page_limit 2 → while 루프가 여러 번 돌며 커서 전진해야 함
    _seed(session, [T0 + i * HOUR for i in [0, 1, 2, 8, 9]])     # 3..7 누락(5봉)
    client = FakeClient()
    r = heal_gaps(session, client, "BTC-USDT-SWAP", "1h",
                  now_ms=T0 + 100 * HOUR, page_limit=2)
    assert r["gaps_found"] == 5 and r["inserted"] == 5
    assert len(client.calls) >= 3                       # 2+2+1 페이지
    assert client.calls == sorted(client.calls)         # 커서 단조 전진


def test_heal_partial_fill_reported(session):
    # 거래소가 빈 응답을 주면(히스토리 한계) 일부만 채우고 정직하게 보고
    _seed(session, [T0 + i * HOUR for i in [0, 1, 2, 8, 9]])
    class EmptyClient:
        def fetch_ohlcv(self, symbol, timeframe, since_ms, limit):
            return []
    r = heal_gaps(session, EmptyClient(), "BTC-USDT-SWAP", "1h",
                  now_ms=T0 + 100 * HOUR)
    assert r["gaps_found"] == 5 and r["inserted"] == 0
