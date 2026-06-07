from click.testing import CliRunner

from quantpilot.cli import cli
from quantpilot.data.db import make_engine, make_session_factory, init_db


def test_status_empty_db(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "BTC-USDT-SWAP" in result.output or "비어" in result.output


def test_collect_rejects_bad_timeframe(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    runner = CliRunner()
    result = runner.invoke(cli, ["collect", "--symbol", "BTC-USDT-SWAP",
                                 "--timeframe", "7m", "--days", "1"])
    assert result.exit_code != 0
    assert "7m" in result.output
