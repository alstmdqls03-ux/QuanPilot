from sqlalchemy import select


def test_paper_tables_created(session):
    # init_db가 paper 테이블을 등록·생성했으면 빈 조회가 에러 없이 동작
    from quantpilot.paper.models import PaperStateRow, PaperTradeRow
    assert session.execute(select(PaperStateRow)).scalars().all() == []
    assert session.execute(select(PaperTradeRow)).scalars().all() == []
