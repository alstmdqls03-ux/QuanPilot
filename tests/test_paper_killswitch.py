from quantpilot.data.db import init_db, make_engine, make_session_factory
from quantpilot.paper.store import (
    PaperState, make_run_key, read_halted, save_state)


def _file_sessions(tmp_path):
    # 두 세션이 같은 파일 DB를 공유(별 프로세스 흉내). :memory:는 연결 간 공유 안 됨.
    engine = make_engine(f"sqlite:///{tmp_path / 'qp.db'}")
    init_db(engine)
    SL = make_session_factory(engine)
    return SL(), SL()


def test_read_halted_sees_external_commit(tmp_path):
    s1, s2 = _file_sessions(tmp_path)
    rk = make_run_key("BTC-USDT-SWAP", "1h", "rsi-mr")
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="rsi-mr", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    save_state(s1, st)                       # s1: halted=False 저장
    assert read_halted(s1, rk) is False
    # s2(별 프로세스 흉내)가 halted=True로 갱신
    st.halted = True
    save_state(s2, st)
    # s1은 캐시를 들고 있지만 read_halted가 expire로 외부 변경을 봐야 함
    assert read_halted(s1, rk) is True


def test_read_halted_missing_row_is_false(session):
    assert read_halted(session, make_run_key("X", "1h", "rsi-mr")) is False


def test_setup_paper_logger_writes_to_file(tmp_path):
    from quantpilot.paper.logsetup import setup_paper_logger
    log_dir = tmp_path / "logs"
    logger = setup_paper_logger("BTC-USDT-SWAP|1h|rsi-mr", log_dir=str(log_dir))
    logger.info("hello-qa-line")
    for h in logger.handlers:
        h.flush()
    files = list(log_dir.glob("paper-*.log"))
    assert files, "로그 파일이 생성돼야 함"
    assert "hello-qa-line" in files[0].read_text()
