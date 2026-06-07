from click.testing import CliRunner

from quantpilot.cli import cli


def test_backtest_rejects_unknown_strategy(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    result = CliRunner().invoke(cli, ["backtest", "--strategy", "nope",
                                      "--symbol", "BTC-USDT-SWAP", "--timeframe", "1h"])
    assert result.exit_code != 0
    assert "nope" in result.output
    assert "Traceback" not in result.output


def test_backtest_empty_db_clean_error(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    result = CliRunner().invoke(cli, ["backtest", "--strategy", "rsi-mr",
                                      "--symbol", "BTC-USDT-SWAP", "--timeframe", "1h"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output   # 친절한 에러
