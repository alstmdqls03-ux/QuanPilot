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
from sqlalchemy import func, select


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
    client.load_markets()
    upsert_instruments(session, client, now_ms=_now_ms())
    summary = collect_ohlcv(session, client, symbol, timeframe, days=days, now_ms=_now_ms())
    click.echo(f"{symbol} {timeframe}: 신규 {summary['inserted']}개 적재")


@cli.command(name="collect-funding")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--days", default=365, show_default=True, type=int)
def collect_funding_cmd(symbol: str, days: int):
    """funding rate 증분 수집."""
    session, _ = _session()
    from quantpilot.exchange.client import OKXClient
    client = OKXClient()
    client.load_markets()
    summary = collect_funding(session, client, symbol, days=days, now_ms=_now_ms())
    click.echo(f"{symbol} funding: 신규 {summary['inserted']}개 적재")


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


if __name__ == "__main__":
    cli()
