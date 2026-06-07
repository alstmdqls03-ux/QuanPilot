"""SQLAlchemy 엔진/세션 팩토리.

WHY 분리: 모델(models.py)과 엔진 생성을 나눠 두면 테스트에서
in-memory SQLite로 쉽게 갈아끼울 수 있음.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 모든 모델이 상속하는 베이스. models.py가 이걸 import.
Base = declarative_base()


def make_engine(db_url: str):
    """db_url로 엔진 생성. 예: 'sqlite:///data/quantpilot.db'"""
    # WHY future=True: SQLAlchemy 2.x 스타일 동작 보장.
    return create_engine(db_url, future=True)


def make_session_factory(engine):
    """세션 팩토리 생성. 호출부에서 SessionLocal() 로 세션 획득."""
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db(engine) -> None:
    """모든 테이블 생성 (이미 있으면 무시). 앱/테스트 시작 시 1회 호출."""
    # models를 import해야 Base.metadata에 테이블이 등록됨.
    from quantpilot.data import models  # noqa: F401
    # 페이퍼 상태/거래 테이블도 같은 Base에 등록(단일 create_all 경로 유지).
    from quantpilot.paper import models as _paper_models  # noqa: F401

    Base.metadata.create_all(engine)
