from click.testing import CliRunner

from quantpilot.cli import cli


def test_confluence_registered():
    from quantpilot.cli import STRATEGIES
    from quantpilot.strategy.confluence import ConfluenceStrategy
    assert STRATEGIES["confluence"] is ConfluenceStrategy


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


def test_backtest_htf_unsupported_rejects(tmp_path, monkeypatch):
    """--htf에 미지원 timeframe을 넣으면 ClickException으로 깔끔하게 거부."""
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    result = CliRunner().invoke(cli, ["backtest", "--strategy", "rsi-mr",
                                      "--symbol", "BTC-USDT-SWAP", "--timeframe", "1h",
                                      "--htf", "999x"])
    assert result.exit_code != 0
    assert "999x" in result.output
    assert "Traceback" not in result.output


def test_backtest_htf_valid_passthrough(tmp_path, monkeypatch):
    """--htf 4h는 파싱에서 거부하지 않고 DB 없음 에러까지 진행(경로 통과 확인)."""
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    result = CliRunner().invoke(cli, ["backtest", "--strategy", "confluence",
                                      "--symbol", "BTC-USDT-SWAP", "--timeframe", "1h",
                                      "--htf", "4h"])
    # 미지원 htf가 아니면 통과 → DB 없어서 에러(DataGapError 또는 Instrument 없음)
    assert result.exit_code != 0
    assert "999x" not in result.output         # htf 파싱 오류는 아님
    assert "Traceback" not in result.output
