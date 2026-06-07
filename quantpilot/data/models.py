# data/models.py
#
# 설계 원칙 (이 파일 전체 적용):
# - 타임스탬프는 전부 int ms epoch (UTC). datetime 객체 안 씀.
#   WHY: SQLite는 네이티브 타임존 타입이 없어서 datetime 저장 시
#        로컬/UTC 혼동 버그가 남. 정수면 모호함 0.
# - 테이블 간 외래키(FK) 없음. symbol 문자열로만 논리적 연결.
#   WHY: 원시 시장 데이터는 append 위주라 참조무결성 강제가 득보다 실.
#        캔들을 instrument 캐시보다 먼저 받을 수도 있음.
from sqlalchemy import (
    BigInteger, Column, Float, Index, Integer, String, UniqueConstraint,
)

from quantpilot.data.db import Base


class Candle(Base):
    """OHLCV 캔들 1개. 거래소 raw 데이터를 그대로 보존."""
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True)
    exchange = Column(String, nullable=False, default="okx")
    symbol = Column(String, nullable=False)       # "BTC-USDT-SWAP"
    timeframe = Column(String, nullable=False)    # "1h" | "15m"
    # WHY String timeframe: ccxt가 문자열로 받음. enum 변환 한 단계 제거.
    ts = Column(BigInteger, nullable=False)       # 캔들 open time, ms epoch UTC
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)        # ccxt OHLCV[5] (정규화된 거래량)
    # WHY 단위 주의: ccxt가 정규화한 값이라 OKX 선물에선 '계약 수' 가 아니라
    #   base-asset(예: BTC) 거래량일 수 있음. 단위는 ccxt 버전/심볼마다 다를 수
    #   있으니, Week 2 sizing/PnL에 쓰기 전 ct_val로 환산·검증할 것
    #   (1 BTC = 1/ct_val 계약). 계약 수로 단정하지 말 것.
    # WHY 단일 컬럼: 통화환산 volume(volCcy)은 Week 1에서 안 씀(YAGNI).
    inserted_at = Column(BigInteger, nullable=False)  # 적재 시각 ms epoch
    # WHY inserted_at: "이 캔들 언제 받았지?" 디버깅이 의외로 잦음.

    __table_args__ = (
        # 이 unique 제약이 idempotency의 핵심.
        # WHY: 같은 (거래소,심볼,봉,시각)은 단 1행. upsert가 여기 걸려
        #      중복 없이 무시됨. 증분 수집의 토대.
        UniqueConstraint("exchange", "symbol", "timeframe", "ts"),
        Index("ix_candle_lookup", "symbol", "timeframe", "ts"),  # 범위 조회
    )


class FundingRate(Base):
    """선물 funding rate 1개. 8시간마다 1개."""
    __tablename__ = "funding_rates"

    id = Column(Integer, primary_key=True)
    exchange = Column(String, nullable=False, default="okx")
    symbol = Column(String, nullable=False)
    ts = Column(BigInteger, nullable=False)        # funding time, ms epoch UTC
    funding_rate = Column(Float, nullable=False)   # 0.0001 = 0.01%
    inserted_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        # idempotency: 같은 (거래소,심볼,funding시각)은 1행.
        UniqueConstraint("exchange", "symbol", "ts"),
    )


class Instrument(Base):
    """거래 명세 메타데이터. 심볼당 1행. Week 2 sizing이 ct_val을 읽음."""
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True)
    exchange = Column(String, nullable=False, default="okx")
    symbol = Column(String, nullable=False)
    ct_val = Column(Float, nullable=False)         # 계약 면값 (BTC-USDT-SWAP=0.01)
    # WHY 캐시: Week 2 position sizing이 매번 읽음. 미리 받아둠.
    ct_val_ccy = Column(String, nullable=False)    # "BTC"
    lot_sz = Column(Float, nullable=False)         # 최소 주문 증분(계약)
    min_sz = Column(Float, nullable=False)         # 최소 주문 수량
    tick_sz = Column(Float, nullable=False)        # 가격 최소 단위
    updated_at = Column(BigInteger, nullable=False)  # 갱신 시각 ms epoch

    __table_args__ = (UniqueConstraint("exchange", "symbol"),)
