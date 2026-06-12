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


def test_heal_stuck_client_terminates(session):
    """Fix 3: 거래소가 since를 무시하고 고정 봉을 반복 반환해도 무한루프 없이 종료.

    WHY: StuckClient는 항상 동일한 ts를 반환 → max(rows)+tf_ms가 cursor와 같아짐
    → cursor <= prev_cursor 조건이 True → break. 유한 종료 보장.
    수정 전: cursor = max(rows)+tf_ms가 고정값이므로 while cursor<=end 가 무한루프.
    """
    # gap 3봉(T0+3h~T0+5h) 생성
    _seed(session, [T0 + i * HOUR for i in [0, 1, 2, 6, 7]])

    class StuckClient:
        """항상 gap 시작 직전 봉을 반환(since 무시). cursor가 전진 안 함."""
        def __init__(self):
            self.calls = 0

        def fetch_ohlcv(self, symbol, timeframe, since_ms, limit):
            self.calls += 1
            # gap 시작 이전 ts 고정 반환 → cursor = stuck_ts + tf_ms = T0+3h (end 이하)
            stuck_ts = T0 + 2 * HOUR  # gap start=T0+3h 이하라 항상 end(=T0+5h) 이하
            return [{"ts": stuck_ts, "open": 1.0, "high": 2.0,
                     "low": 0.5, "close": 1.5, "volume": 3.0}]

    client = StuckClient()
    # timeout: 루프가 무한이면 테스트 자체가 멈추므로 호출 횟수로 간접 검증
    r = heal_gaps(session, client, "BTC-USDT-SWAP", "1h",
                  now_ms=T0 + 100 * HOUR)
    # 유한 종료: StuckClient는 upsert=0(stuck_ts가 이미 DB에 있거나 end 이하), call≥1
    assert client.calls >= 1, "클라이언트가 호출되지 않음"
    # 핵심: 결과 반환됨(무한루프 없이 종료) — gaps_found≥3(gap 있음)
    assert r["gaps_found"] >= 3, f"gap이 감지되지 않음: {r}"
