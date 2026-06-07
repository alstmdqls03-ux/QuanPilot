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


def test_status_creates_missing_parent_dir(tmp_path, monkeypatch):
    # 부모 디렉토리가 없는 경로라도 status가 크래시 없이 동작해야 함.
    db = tmp_path / "nonexistent" / "sub" / "x.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0


def test_collect_rejects_bad_timeframe(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))
    runner = CliRunner()
    result = runner.invoke(cli, ["collect", "--symbol", "BTC-USDT-SWAP",
                                 "--timeframe", "7m", "--days", "1"])
    assert result.exit_code != 0
    assert "7m" in result.output


def test_collect_bad_symbol_clean_error(tmp_path, monkeypatch):
    # QA 회귀: 잘못된 심볼은 raw Traceback이 아니라 친절한 CLI 에러로 끝나야 함.
    # resolve_symbol이 던지는 ValueError를 CLI가 ClickException으로 변환하는지 검증.
    db = tmp_path / "t.db"
    monkeypatch.setenv("QUANTPILOT_DB_PATH", str(db))

    class _BadSymbolClient:
        def load_markets(self):
            return {}

        def fetch_ohlcv(self, *a, **k):
            raise ValueError("심볼 'FAKE-NOPE-SWAP'를 OKX에서 못 찾음.")

    # cli는 함수 안에서 quantpilot.exchange.client.OKXClient를 import하므로 거기서 패치.
    monkeypatch.setattr("quantpilot.exchange.client.OKXClient", _BadSymbolClient)
    result = CliRunner().invoke(cli, ["collect", "--symbol", "FAKE-NOPE-SWAP",
                                      "--timeframe", "1h", "--days", "1"])
    assert result.exit_code != 0
    assert "FAKE-NOPE-SWAP" in result.output
    assert "Error:" in result.output          # click의 깔끔한 에러 포맷
    assert "Traceback" not in result.output    # raw 트레이스백 노출 안 됨
