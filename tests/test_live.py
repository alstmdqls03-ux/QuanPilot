"""실제 OKX 연결 확인. 기본 실행에선 제외됨(pyproject addopts).
수동 실행: pytest -m live -v
"""
import pytest

from quantpilot.exchange.client import OKXClient


@pytest.mark.live
def test_okx_public_ohlcv_reachable():
    """진짜 OKX public 엔드포인트가 응답하고 정규화가 동작하는지."""
    c = OKXClient()  # 실제 ccxt.okx
    c.load_markets()
    rows = c.fetch_ohlcv("BTC-USDT-SWAP", "1h", since_ms=0, limit=5)
    assert len(rows) > 0
    first = rows[0]
    assert set(first) == {"ts", "open", "high", "low", "close", "volume"}
    assert first["high"] >= first["low"]


@pytest.mark.live
def test_okx_funding_reachable():
    c = OKXClient()
    c.load_markets()
    rows = c.fetch_funding("BTC-USDT-SWAP", since_ms=0, limit=5)
    assert len(rows) > 0
    assert "funding_rate" in rows[0]
