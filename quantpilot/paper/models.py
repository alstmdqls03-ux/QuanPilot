"""페이퍼 트레이더 영속 테이블. 상태 1행(재시작 복구) + 거래 로그(감사).

설계: data/models.py와 동일 규약 — ts는 int ms epoch UTC, FK 없음(run_key 문자열 연결).
포지션은 한 번에 1개라 paper_state 행에 인라인(정규화 X → 복구가 원자적).
"""
from sqlalchemy import BigInteger, Boolean, Column, Float, Integer, String

from quantpilot.data.db import Base


class PaperStateRow(Base):
    """현재 런의 상태 스냅샷(단일 행, run_key가 PK). 재시작 시 이 행으로 정확 복구."""
    __tablename__ = "paper_state"

    run_key = Column(String, primary_key=True)   # "symbol|timeframe|strategy"
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    strategy = Column(String, nullable=False)
    equity = Column(Float, nullable=False)             # 현재 실현 자본(USDT)
    day_start_equity = Column(Float, nullable=False)   # 오늘 시작 자본(서킷 기준선)
    day_start_ts = Column(BigInteger, nullable=False)  # 오늘 UTC 경계
    daily_realized_pnl = Column(Float, nullable=False, default=0.0)
    halted = Column(Boolean, nullable=False, default=False)  # panic/서킷 정지
    last_processed_bar_ts = Column(BigInteger, nullable=True)  # 중복방지·재개 지점
    # 포지션(열려 있을 때만 non-NULL). WHY 인라인: 한 번에 1개라 별 테이블 불필요.
    pos_side = Column(String, nullable=True)
    pos_entry = Column(Float, nullable=True)
    pos_contracts = Column(Integer, nullable=True)
    pos_original_contracts = Column(Integer, nullable=True)
    pos_stop = Column(Float, nullable=True)
    pos_targets_remaining = Column(String, nullable=True)  # JSON [[price,frac],...]
    pos_opened_ts = Column(BigInteger, nullable=True)
    pos_open_fee = Column(Float, nullable=True)            # 진입 수수료(Trade 집계용)
    pos_pending_fills = Column(String, nullable=True)      # JSON fills(분할익절 누적)


class PaperTradeRow(Base):
    """청산 완료된 거래 로그(append-only). Week 2 Trade의 영속 버전."""
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True)
    run_key = Column(String, nullable=False)
    side = Column(String, nullable=False)
    entry = Column(Float, nullable=False)
    exit = Column(Float, nullable=False)
    contracts = Column(Integer, nullable=False)
    pnl_gross = Column(Float, nullable=False)
    fees = Column(Float, nullable=False)
    funding = Column(Float, nullable=False)
    pnl_net = Column(Float, nullable=False)
    opened_ts = Column(BigInteger, nullable=False)
    closed_ts = Column(BigInteger, nullable=False)
    reason = Column(String, nullable=False)
