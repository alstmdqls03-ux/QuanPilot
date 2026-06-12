from click.testing import CliRunner

from quantpilot.cli import cli


# ── 헬퍼: in-memory DB를 tmp_path 파일로 준비 + 캔들·Instrument 시딩 ──────────

def _seed_db(tmp_path, monkeypatch, n_candles: int = 300):
    """tmp_path에 SQLite DB 생성 후 Candle n_candles개 + Instrument 1개 삽입.

    WHY: CLI backtest 테스트는 실 data/quantpilot.db를 건드리지 않도록
    monkeypatch로 DB 경로를 tmp_path 파일로 교체하고, in-memory 세션으로 시딩한다.
    기존 test_cli_backtest 패턴(monkeypatch.setenv + CliRunner)을 그대로 따름.
    """
    from quantpilot.data.db import init_db, make_engine, make_session_factory
    from quantpilot.data.models import Candle, Instrument

    db = str(tmp_path / "t.db")
    monkeypatch.setenv("QUANTPILOT_DB_PATH", db)

    engine = make_engine(f"sqlite:///{db}")
    init_db(engine)
    s = make_session_factory(engine)()

    tf_ms = 3_600_000          # 1h in ms
    base = 1_700_000_000_000   # 2023-11-15 00:00:00 UTC (ms)
    close = 30_000.0
    for i in range(n_candles):
        s.add(Candle(
            exchange="okx", symbol="BTC-USDT-SWAP", timeframe="1h",
            ts=base + i * tf_ms,
            open=close, high=close + 50, low=close - 50, close=close,
            volume=1.0, inserted_at=base,
        ))
    s.add(Instrument(
        exchange="okx", symbol="BTC-USDT-SWAP",
        ct_val=0.01, ct_val_ccy="BTC",
        lot_sz=1.0, min_sz=1.0, tick_sz=0.1, updated_at=base,
    ))
    s.commit()
    s.close()

    return base, tf_ms


# ── 실패 테스트(RED): --start-ms / --end-ms 구간 옵션 ───────────────────────

def test_backtest_start_end_window(tmp_path, monkeypatch):
    """--start-ms/--end-ms로 중간 구간만 지정 시 정상 종료(exit_code 0).

    WHY: walk-forward는 전체 데이터를 여러 구간으로 나눠 각 구간을 독립 평가한다.
    --start-ms/--end-ms 옵션이 없으면 CLI 파싱 자체가 실패해 exit_code != 0이 됨.
    """
    base, tf_ms = _seed_db(tmp_path, monkeypatch, n_candles=300)

    # 구간: 봉 100번째~200번째 (lookback=42를 충분히 포함)
    start_ms = base + 100 * tf_ms
    end_ms   = base + 200 * tf_ms

    result = CliRunner().invoke(cli, [
        "backtest",
        "--strategy", "rsi-mr",
        "--symbol", "BTC-USDT-SWAP",
        "--timeframe", "1h",
        "--start-ms", str(start_ms),
        "--end-ms",   str(end_ms),
    ])
    assert result.exit_code == 0, (
        f"exit_code={result.exit_code}, output={result.output!r}")
    # 구간 밖 데이터가 결과에 없는지: equity curve 저장 메시지가 정상 출력되면 충분
    assert "equity curve" in result.output.lower() or "저장됨" in result.output


def test_backtest_start_end_rejects_empty_window(tmp_path, monkeypatch):
    """구간 필터 결과가 빈 df면 친절한 에러(Traceback 없음).

    WHY: --start-ms가 모든 봉보다 미래면 df가 비어 DataGapError를 내야 한다.
    기존 test_backtest_empty_db_clean_error와 동일한 에러 경로를 구간 버전으로 확인.
    """
    base, tf_ms = _seed_db(tmp_path, monkeypatch, n_candles=10)

    # 미래 구간 → df 빈 결과
    start_ms = base + 9999 * tf_ms

    result = CliRunner().invoke(cli, [
        "backtest",
        "--strategy", "rsi-mr",
        "--symbol", "BTC-USDT-SWAP",
        "--timeframe", "1h",
        "--start-ms", str(start_ms),
    ])
    assert result.exit_code != 0
    assert "Traceback" not in result.output


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
