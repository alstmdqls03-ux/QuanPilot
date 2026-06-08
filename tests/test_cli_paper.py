"""CLI paper 명령 smoke 테스트 — 상태 없음 케이스(크래시 방지)."""
from click.testing import CliRunner

from quantpilot.cli import cli


def test_paper_status_empty(monkeypatch, tmp_path):
    # 빈 DB에서 paper-status는 "상태 없음" 안내, 크래시 없음
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(tmp_path / "q.db"))
    r = CliRunner().invoke(cli, ["paper-status"])
    assert r.exit_code == 0
    assert "상태" in r.output or "없음" in r.output


def test_paper_logs_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(tmp_path / "q.db"))
    r = CliRunner().invoke(cli, ["paper-logs"])
    assert r.exit_code == 0
    # WHY 출력 내용 확인: exit_code==0만으로는 명령이 올바른 코드 경로를 탔는지 모름.
    # "거래 없음" 메시지 또는 run_key 형식 문자열(SYMBOL|TF|STRATEGY)이 있어야
    # paper-logs가 실제로 빈 거래 목록을 처리한 경로를 통과했음이 보장됨.
    assert "거래 없음" in r.output or "|" in r.output, (
        f"paper-logs 출력이 예상 메시지를 포함하지 않음: {r.output!r}")
