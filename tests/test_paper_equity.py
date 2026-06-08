from sqlalchemy import select


def test_paper_equity_table_created(session):
    from quantpilot.paper.models import PaperEquityRow
    assert session.execute(select(PaperEquityRow)).scalars().all() == []
