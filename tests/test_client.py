import json
from pathlib import Path

import ccxt
import pytest

from quantpilot.exchange.client import OKXClient

FIX = Path(__file__).parent / "fixtures"


class FakeCcxt:
    """ccxt.okx 흉내. 네트워크 없이 fixture를 돌려줌."""
    def __init__(self):
        self.markets = {
            "BTC/USDT:USDT": json.loads((FIX / "market_btc.json").read_text())
        }
        self.last_ohlcv_call = None

    def load_markets(self):
        return self.markets

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.last_ohlcv_call = (symbol, timeframe, since, limit)
        return json.loads((FIX / "ohlcv_btc_1h.json").read_text())

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        return json.loads((FIX / "funding_btc.json").read_text())


class FlakyCcxt(FakeCcxt):
    """N번 NetworkError를 던진 뒤 성공. 재시도 로직 검증용."""
    def __init__(self, fail_times):
        super().__init__()
        self._fail = fail_times

    def fetch_ohlcv(self, *a, **k):
        if self._fail > 0:
            self._fail -= 1
            raise ccxt.NetworkError("temporary")
        return super().fetch_ohlcv(*a, **k)


def test_resolve_symbol_translates_native_to_unified():
    c = OKXClient(ccxt_client=FakeCcxt())
    c.load_markets()
    assert c.resolve_symbol("BTC-USDT-SWAP") == "BTC/USDT:USDT"


def test_fetch_ohlcv_normalizes_rows():
    c = OKXClient(ccxt_client=FakeCcxt())
    c.load_markets()
    rows = c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=1700000000000, limit=100)
    assert rows[0] == {
        "ts": 1700000000000, "open": 100.0, "high": 110.0,
        "low": 95.0, "close": 105.0, "volume": 1234.0,
    }
    assert len(rows) == 2


def test_fetch_ohlcv_passes_unified_symbol_to_ccxt():
    fake = FakeCcxt()
    c = OKXClient(ccxt_client=fake)
    c.load_markets()
    c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=123, limit=100)
    # ccxt에는 통합 심볼이 전달돼야 함
    assert fake.last_ohlcv_call[0] == "BTC/USDT:USDT"


def test_fetch_funding_normalizes_rows():
    c = OKXClient(ccxt_client=FakeCcxt())
    c.load_markets()
    rows = c.fetch_funding("BTC-USDT-SWAP", since_ms=1700000000000, limit=100)
    assert rows[0] == {"ts": 1700000000000, "funding_rate": 0.0001}
    assert len(rows) == 2


def test_markets_list_for_instruments():
    c = OKXClient(ccxt_client=FakeCcxt())
    markets = c.load_markets()
    assert "BTC/USDT:USDT" in markets


def test_fetch_ohlcv_retries_on_network_error(monkeypatch):
    # 일시적 NetworkError는 backoff 후 재시도되어 결국 성공해야 함.
    monkeypatch.setattr("quantpilot.exchange.client.time.sleep", lambda *_: None)
    c = OKXClient(ccxt_client=FlakyCcxt(fail_times=2))
    c.load_markets()
    rows = c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=0, limit=100)
    assert len(rows) == 2  # 2번 실패 후 3번째 성공


def test_fetch_ohlcv_gives_up_after_max_attempts(monkeypatch):
    # 계속 실패하면 마지막엔 예외를 올려서 호출부가 알 수 있게 함.
    monkeypatch.setattr("quantpilot.exchange.client.time.sleep", lambda *_: None)
    c = OKXClient(ccxt_client=FlakyCcxt(fail_times=99))
    c.load_markets()
    with pytest.raises(ccxt.NetworkError):
        c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=0, limit=100)
