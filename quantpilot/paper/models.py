"""페이퍼 트레이더 영속 테이블. 상태 1행(재시작 복구) + 거래 로그(감사).

설계: data/models.py와 동일 규약 — ts는 int ms epoch UTC, FK 없음(run_key 문자열 연결).
포지션은 한 번에 1개라 paper_state 행에 인라인(정규화 X → 복구가 원자적).
"""
from sqlalchemy import BigInteger, Boolean, Column, Float, Integer, String, UniqueConstraint

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
    panic_halted = Column(Boolean, nullable=False, default=False)  # 수동 panic 정지(서킷 halted와 분리)
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


class PaperEquityRow(Base):
    """봉별 equity 포인트(실현+미실현). paper-report가 Sharpe/MaxDD 계산에 사용.

    WHY UNIQUE(run_key, ts): 틱 재처리(재시작/오류 복구) 시 같은 봉 equity가 중복 적재되면
    곡선이 왜곡된다. (run_key, ts) 유니크 + on_conflict_do_nothing으로 idempotent(Week 1 캔들 패턴).
    """
    __tablename__ = "paper_equity"

    id = Column(Integer, primary_key=True)
    run_key = Column(String, nullable=False)
    ts = Column(BigInteger, nullable=False)        # 봉 ts (ms epoch UTC)
    equity = Column(Float, nullable=False)         # 실현 + 미실현(그 봉 종가 기준)

    __table_args__ = (UniqueConstraint("run_key", "ts"),)


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
