"""QuantPilot CLI. Week 1: collect, collect-funding, status.

WHY click: 옵션 파싱·--help·검증을 데코레이터로 공짜 제공.
"""
from __future__ import annotations

import time
from pathlib import Path

import click

from quantpilot.config import Settings
from quantpilot.data.db import init_db, make_engine, make_session_factory
from quantpilot.data.collector import (
    collect_funding, collect_ohlcv, upsert_instruments,
)
from quantpilot.data.models import Candle, FundingRate, Instrument
from quantpilot.timeframes import SUPPORTED_TIMEFRAMES, timeframe_to_ms
from quantpilot.strategy.rsi_mean_reversion import RsiMeanReversion
from sqlalchemy import func, select

# 전략 레지스트리 — 새 전략 = 클래스 + 여기 1줄
STRATEGIES = {"rsi-mr": RsiMeanReversion}


def _session():
    settings = Settings()
    # data/ 는 gitignore라 신규 클론엔 없음 — 첫 실행 시 생성
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.db_url)
    init_db(engine)
    return make_session_factory(engine)(), settings


def _now_ms() -> int:
    return int(time.time() * 1000)


@click.group()
def cli():
    """QuantPilot — OKX edge lab (Week 1: 데이터 수집)."""


@cli.command()
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--days", default=365, show_default=True, type=int)
def collect(symbol: str, timeframe: str, days: int):
    """OHLCV 캔들 증분 수집."""
    # 사람 실수(잘못된 timeframe)는 네트워크 타기 전에 즉시 거부.
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise click.ClickException(
            f"지원하지 않는 timeframe '{timeframe}'. "
            f"사용 가능: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}"
        )
    session, _ = _session()
    from quantpilot.exchange.client import OKXClient
    client = OKXClient()
    try:
        client.load_markets()
        upsert_instruments(session, client, now_ms=_now_ms())
        summary = collect_ohlcv(session, client, symbol, timeframe, days=days, now_ms=_now_ms())
    except ValueError as e:
        # 잘못된 심볼 등(resolve_symbol) → raw traceback 대신 친절한 CLI 에러로.
        raise click.ClickException(str(e))
    click.echo(f"{symbol} {timeframe}: 신규 {summary['inserted']}개 적재")
    if summary.get("truncated"):
        click.echo(
            f"⚠️  OKX가 요청한 {days}일치 전부를 주지 않음(히스토리 한계 가능성). "
            f"'quantpilot status'로 실제 적재 범위를 확인하세요."
        )


@cli.command(name="collect-funding")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--days", default=365, show_default=True, type=int)
def collect_funding_cmd(symbol: str, days: int):
    """funding rate 증분 수집."""
    session, _ = _session()
    from quantpilot.exchange.client import OKXClient
    client = OKXClient()
    try:
        client.load_markets()
        summary = collect_funding(session, client, symbol, days=days, now_ms=_now_ms())
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{symbol} funding: 신규 {summary['inserted']}개 적재")
    if summary.get("truncated"):
        click.echo(
            f"⚠️  OKX가 요청한 {days}일치 funding 전부를 주지 않음(히스토리 한계 가능성). "
            f"'quantpilot status'로 실제 적재 범위를 확인하세요."
        )


@cli.command()
def status():
    """DB에 적재된 내용 요약 (보고만, 수정 안 함)."""
    session, _ = _session()
    # 심볼별로 그룹 (Week 1은 보통 BTC-USDT-SWAP 1개)
    symbols = [r[0] for r in session.execute(
        select(Candle.symbol).distinct()
    ).all()]
    if not symbols:
        click.echo("DB가 비어 있음. 먼저 'quantpilot collect'를 실행하세요.")
        return
    for sym in symbols:
        click.echo(sym)
        for tf in sorted(SUPPORTED_TIMEFRAMES):
            cnt = session.execute(
                select(func.count()).select_from(Candle).where(
                    Candle.symbol == sym, Candle.timeframe == tf)
            ).scalar_one()
            if cnt == 0:
                continue
            lo = session.execute(select(func.min(Candle.ts)).where(
                Candle.symbol == sym, Candle.timeframe == tf)).scalar_one()
            hi = session.execute(select(func.max(Candle.ts)).where(
                Candle.symbol == sym, Candle.timeframe == tf)).scalar_one()
            # 예상 봉 수 = (범위 / 봉길이) + 1. 실제와 단순 비교(보고용).
            expected = (hi - lo) // timeframe_to_ms(tf) + 1
            mark = "✓" if cnt >= expected else f"⚠ 예상 {expected}"
            click.echo(f"  {tf}: {cnt}봉  ({mark})")
        fcnt = session.execute(
            select(func.count()).select_from(FundingRate).where(
                FundingRate.symbol == sym)
        ).scalar_one()
        click.echo(f"  funding: {fcnt}개")
    icnt = session.execute(select(func.count()).select_from(Instrument)).scalar_one()
    click.echo(f"Instrument 캐시: {icnt}개 심볼")


@cli.command()
@click.option("--strategy", default="rsi-mr", show_default=True)
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--oos-months", default=2, show_default=True, type=int)
@click.option("--capital", default=1000.0, show_default=True, type=float)
@click.option("--leverage", default=3, show_default=True, type=int)
@click.option("--allow-gaps", is_flag=True, default=False)
def backtest(strategy, symbol, timeframe, oos_months, capital, leverage, allow_gaps):
    """과거 데이터에 전략을 돌려 train/OOS 성과 측정."""
    if strategy not in STRATEGIES:
        raise click.ClickException(
            f"알 수 없는 전략 '{strategy}'. 사용 가능: {', '.join(STRATEGIES)}")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise click.ClickException(
            f"지원하지 않는 timeframe '{timeframe}'. 사용 가능: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}")

    from quantpilot.backtest.data_loader import DataGapError, load_with_gap_check
    from quantpilot.backtest.engine import run_backtest
    from quantpilot.backtest.metrics import compute_metrics, periods_per_year
    from quantpilot.backtest.report import format_console, save_equity_png
    from quantpilot.data.models import FundingRate, Instrument
    from sqlalchemy import select

    session, _ = _session()
    try:
        df, gaps, _ = load_with_gap_check(session, symbol, timeframe, allow_gaps)
    except DataGapError as e:
        raise click.ClickException(str(e))
    if gaps:
        click.echo(f"⚠️  {gaps}개 봉 누락 (--allow-gaps로 진행 중)")

    # ct_val 조회 (없으면 안내)
    inst = session.execute(select(Instrument).where(
        Instrument.symbol == symbol)).scalar_one_or_none()
    if inst is None:
        raise click.ClickException(
            f"{symbol} Instrument 캐시 없음. 먼저 'quantpilot collect'를 실행하세요.")

    funding_events = [(f.ts, f.funding_rate) for f in session.execute(
        select(FundingRate).where(FundingRate.symbol == symbol)
        .order_by(FundingRate.ts)).scalars().all()]

    # train/OOS 분리: 마지막 oos_months 개월을 OOS
    split_ts = int(df.index[-1]) - oos_months * 30 * 86_400_000

    strat = STRATEGIES[strategy](timeframe=timeframe)
    result = run_backtest(
        candles=df, strategy=strat, capital=capital, ct_val=inst.ct_val,
        lot_sz=inst.lot_sz, leverage=leverage, fee_bps=5, slippage_bps=2,
        funding_events=funding_events, oos_split_ts=split_ts)

    ppy = periods_per_year(timeframe)
    train_curve = [(t, e) for t, e in result.equity_curve if t < split_ts]
    oos_curve = [(t, e) for t, e in result.equity_curve if t >= split_ts]
    train_trades = [t for t in result.trades if t.closed_ts < split_ts]
    oos_trades = [t for t in result.trades if t.closed_ts >= split_ts]
    result.train_metrics = compute_metrics(train_curve, train_trades, ppy)
    result.oos_metrics = compute_metrics(oos_curve, oos_trades, ppy)

    click.echo(format_console(result, symbol, strategy))
    png = f"backtest_{symbol}_{strategy}_{_now_ms()}.png"
    save_equity_png(result, png)
    click.echo(f"equity curve 저장됨: {png}")


if __name__ == "__main__":
    cli()
