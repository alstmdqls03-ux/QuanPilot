import json
from pathlib import Path

from quantpilot.exchange.instruments import parse_instrument

FIX = Path(__file__).parent / "fixtures"


def test_parse_instrument_from_market():
    market = json.loads((FIX / "market_btc.json").read_text())
    inst = parse_instrument(market, exchange="okx")
    assert inst["exchange"] == "okx"
    assert inst["symbol"] == "BTC-USDT-SWAP"   # OKX 네이티브 id를 저장
    assert inst["ct_val"] == 0.01
    assert inst["ct_val_ccy"] == "BTC"
    assert inst["lot_sz"] == 1.0
    assert inst["min_sz"] == 1.0
    assert inst["tick_sz"] == 0.1
