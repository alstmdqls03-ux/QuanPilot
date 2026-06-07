import pytest
from sqlalchemy.exc import IntegrityError

from quantpilot.data.models import Candle, FundingRate, Instrument


def test_insert_and_read_candle(session):
    session.add(Candle(
        exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
        ts=1_700_000_000_000, open=100.0, high=110.0, low=95.0,
        close=105.0, volume=1234.0, inserted_at=1_700_000_001_000,
    ))
    session.commit()
    row = session.query(Candle).one()
    assert row.symbol == "BTC-USDT-SWAP"
    assert row.close == 105.0


def test_candle_unique_constraint_blocks_duplicate(session):
    # 같은 (exchange, symbol, timeframe, ts)는 단 1행이어야 함 (idempotency 토대).
    kwargs = dict(
        exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
        ts=1_700_000_000_000, open=1, high=1, low=1, close=1,
        volume=1, inserted_at=1,
    )
    session.add(Candle(**kwargs))
    session.commit()
    session.add(Candle(**kwargs))
    with pytest.raises(IntegrityError):
        session.commit()


def test_funding_and_instrument_insert(session):
    session.rollback()  # 이전 테스트 잔여 상태 정리
    session.add(FundingRate(
        exchange="okx", symbol="BTC-USDT-SWAP",
        ts=1_700_000_000_000, funding_rate=0.0001, inserted_at=1,
    ))
    session.add(Instrument(
        exchange="okx", symbol="BTC-USDT-SWAP", ct_val=0.01,
        ct_val_ccy="BTC", lot_sz=1.0, min_sz=1.0, tick_sz=0.1,
        updated_at=1,
    ))
    session.commit()
    assert session.query(FundingRate).count() == 1
    assert session.query(Instrument).one().ct_val == 0.01
