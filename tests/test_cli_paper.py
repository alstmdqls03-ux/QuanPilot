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
