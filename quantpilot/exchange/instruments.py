"""ccxt market dict → 우리 Instrument 필드로 파싱 (순수 함수)."""


def parse_instrument(market: dict, exchange: str = "okx") -> dict:
    """ccxt market dict에서 거래 명세를 추출.

    WHY market['id']를 symbol로 저장: ccxt의 'symbol'은 통합표기
    ('BTC/USDT:USDT')지만, 우리 DB·CLI는 OKX 네이티브 id
    ('BTC-USDT-SWAP')로 통일한다 (spec 일관성).

    WHY info[...]에서 읽기: ctVal/lotSz 등은 거래소 고유값이라
    ccxt의 표준 필드가 아니라 market['info'](raw 응답)에 들어있음.
    문자열로 오므로 float 변환 필요.
    """
    info = market["info"]
    return {
        "exchange": exchange,
        "symbol": market["id"],
        "ct_val": float(info["ctVal"]),
        "ct_val_ccy": info["ctValCcy"],
        "lot_sz": float(info["lotSz"]),
        "min_sz": float(info["minSz"]),
        "tick_sz": float(info["tickSz"]),
    }
