import pytest

from quantpilot.data.db import make_engine, make_session_factory, init_db


@pytest.fixture
def session():
    """테스트용 in-memory SQLite 세션. 매 테스트마다 새 DB.

    WHY in-memory: 디스크 안 건드리고 빠르며, 테스트 간 격리됨.
    """
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = make_session_factory(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
