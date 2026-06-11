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


def _paper_ctx_and_state(symbol, timeframe, strategy, capital, leverage):
    """paper 루프 시작용 ctx+state 준비(세션·Instrument·전략).

    WHY 헬퍼 분리: paper 명령이 전략 인스턴스화 + Instrument(ct_val/lot_sz) 조회 + state
    복원을 한 번에 준비하도록 묶음. status/panic/logs는 더 가벼운 준비만 필요해 각자 처리.
    """
    from quantpilot.paper.store import load_state, make_run_key
    from quantpilot.paper.trader import TickContext

    if strategy not in STRATEGIES:
        raise click.ClickException(
            f"알 수 없는 전략 '{strategy}'. 사용 가능: {', '.join(STRATEGIES)}")
    session, _ = _session()
    inst = session.execute(select(Instrument).where(
        Instrument.symbol == symbol)).scalar_one_or_none()
    if inst is None:
        raise click.ClickException(
            f"{symbol} Instrument 캐시 없음. 먼저 'quantpilot collect'를 실행하세요.")
    rk = make_run_key(symbol, timeframe, strategy)
    state = load_state(session, rk, symbol=symbol, timeframe=timeframe,
                       strategy=strategy, capital=capital, day_start_ts=_now_ms())
    strat = STRATEGIES[strategy](timeframe=timeframe)
    ctx = TickContext(session=session, client=None, symbol=symbol, timeframe=timeframe,
                      strategy=strat, capital=capital, leverage=leverage,
                      ct_val=inst.ct_val, lot_sz=inst.lot_sz, run_key=rk)
    return session, ctx, state


@cli.command()
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
@click.option("--capital", default=1000.0, show_default=True, type=float)
@click.option("--leverage", default=3, show_default=True, type=int)
@click.option("--poll-seconds", default=60, show_default=True, type=int)
def paper(symbol, timeframe, strategy, capital, leverage, poll_seconds):
    """실시간 페이퍼 트레이딩 루프 시작(포그라운드, 재시작 안전)."""
    from quantpilot.exchange.client import OKXClient
    from quantpilot.paper.trader import run_loop

    session, ctx, state = _paper_ctx_and_state(symbol, timeframe, strategy, capital, leverage)
    client = OKXClient()
    client.load_markets()
    ctx.client = client
    ctx.poll_seconds = poll_seconds
    click.echo(
        f"페이퍼 시작: {symbol} {timeframe} {strategy} "
        f"(자본 {state.equity:.2f}, poll {poll_seconds}s). Ctrl-C로 중단."
    )
    try:
        run_loop(ctx, state)
    except KeyboardInterrupt:
        click.echo("\n중단됨. 상태는 DB에 저장됨(다음 실행 시 이어받음).")


@cli.command(name="paper-status")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
def paper_status(symbol, timeframe, strategy):
    """현재 페이퍼 상태 출력(읽기 전용)."""
    from quantpilot.paper.store import load_state, make_run_key, recent_trades
    from quantpilot.paper.models import PaperStateRow

    session, _ = _session()
    rk = make_run_key(symbol, timeframe, strategy)
    if session.get(PaperStateRow, rk) is None:
        click.echo(f"{rk}: 페이퍼 상태 없음(아직 시작 안 함).")
        return
    st = load_state(session, rk, symbol=symbol, timeframe=timeframe,
                    strategy=strategy, capital=0.0, day_start_ts=0)
    click.echo(f"{rk}")
    click.echo(
        f"  equity: {st.equity:.2f}  (오늘 시작 {st.day_start_equity:.2f}, "
        f"실현 PnL {st.daily_realized_pnl:+.2f})"
    )
    click.echo(f"  halted: {st.halted}   마지막 봉: {st.last_processed_bar_ts}")
    if st.position is None:
        click.echo("  포지션: 없음")
    else:
        p = st.position
        click.echo(f"  포지션: {p.side} {p.contracts}계약 @ {p.entry} (stop {p.stop})")
    click.echo(f"  최근 거래 {len(recent_trades(session, rk, 100))}건")


@cli.command()
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
def panic(symbol, timeframe, strategy):
    """비상정지: 보유 포지션 즉시 청산(최신 봉 종가) + 정지 플래그."""
    # WHY ops.execute_panic 공유: 웹 대시보드 킬스위치와 동일 코드 경로여야
    # 두 진입점의 안전장치 동작이 절대 갈라지지 않는다(원자성 포함).
    from quantpilot.paper.ops import PanicError, execute_panic

    session, _ = _session()
    try:
        r = execute_panic(session, symbol, timeframe, strategy)
    except PanicError as e:
        click.echo(str(e))
        return
    if not r.had_position:
        click.echo(f"정지 플래그 set. 청산할 포지션 없음. (equity {r.equity:.2f})")
    else:
        click.echo(
            f"비상청산 완료 @ {r.last_price} (net {r.pnl_net:+.2f}). 정지됨."
        )


@cli.command(name="paper-logs")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
@click.option("--limit", default=20, show_default=True, type=int)
def paper_logs(symbol, timeframe, strategy, limit):
    """최근 페이퍼 거래 로그 출력."""
    from quantpilot.paper.display import fmt_trade_line, summarize_trades
    from quantpilot.paper.store import make_run_key, recent_trades

    session, _ = _session()
    rk = make_run_key(symbol, timeframe, strategy)
    trades = recent_trades(session, rk, limit)
    if not trades:
        click.echo(f"{rk}: 거래 없음.")
        return
    click.echo(rk)
    for t in trades:
        click.echo("  " + fmt_trade_line(t))
    click.echo("  " + "─" * 46)
    # WHY '이 목록' 라벨: recent_trades(limit)로 잘린 부분집합 기준 요약임을 명시.
    # 전체 누적·승률은 paper-report가 모든 거래로 계산해 담당한다.
    click.echo("  이 목록 " + summarize_trades(trades))


@cli.command(name="paper-report")
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
def paper_report(symbol, timeframe, strategy):
    """페이퍼 런 성과 지표(백테와 동일 지표) 출력."""
    # WHY compute_metrics 재사용: 페이퍼와 백테를 동일한 수식으로 측정해야
    # "페이퍼 Sharpe 1.2 → 백테 1.1과 유사" 처럼 직접 비교 가능. 별도 구현은 지표 불일치 위험.
    from quantpilot.backtest.metrics import compute_metrics, periods_per_year
    from quantpilot.paper.store import load_equity_curve, make_run_key, recent_trades

    session, _ = _session()
    rk = make_run_key(symbol, timeframe, strategy)
    curve = load_equity_curve(session, rk)
    if len(curve) < 2:
        click.echo(f"{rk}: equity 곡선 부족(아직 런 안 했거나 결정 봉 < 2). "
                   f"'quantpilot paper'로 런을 시작하세요.")
        return
    from quantpilot.paper.display import summarize_trades

    trades = recent_trades(session, rk, 1_000_000)
    m = compute_metrics(curve, trades, periods_per_year(timeframe))
    # 수익률은 상세 지표의 total_return과 동일 소스 → 두 값이 어긋나지 않게 재사용.
    ret_pct = m["total_return"] * 100.0
    click.echo(f"{rk}  ({len(curve)}봉, {curve[0][0]}~{curve[-1][0]})")
    # 사람이 먼저 읽는 평이한 요약(손익/자산) → 그 아래 기술 지표.
    click.echo("  📊 손익 요약: " + summarize_trades(trades))
    click.echo(f"  💰 자산(평가 포함, 곡선 마지막): {curve[-1][1]:,.2f}  "
               f"(수익률 {ret_pct:+.2f}%)")
    click.echo("  ── 상세 지표 ──")
    click.echo(f"  total_return: {m['total_return']}")
    click.echo(f"  sharpe:       {m['sharpe']}")
    click.echo(f"  max_drawdown: {m['max_drawdown']}")
    click.echo(f"  n_trades:     {m['n_trades']}  win_rate {m['win_rate']}  "
               f"profit_factor {m['profit_factor']}")
    click.echo(f"  equity(곡선 마지막): {curve[-1][1]:.2f}")


@cli.command()
@click.option("--symbol", default="BTC-USDT-SWAP", show_default=True)
@click.option("--timeframe", default="1h", show_default=True)
@click.option("--strategy", default="rsi-mr", show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True,
              help="킬스위치 엔드포인트가 있으므로 외부 바인딩 금지 권장.")
@click.option("--port", default=8787, show_default=True, type=int)
def dashboard(symbol, timeframe, strategy, host, port):
    """MINCODE 웹 대시보드 서버 시작(실DB 읽기 + 킬스위치). 페이퍼 루프와 별개 프로세스."""
    from quantpilot.dashboard.server import make_server

    settings = Settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.db_url)
    init_db(engine)
    factory = make_session_factory(engine)
    srv = make_server(factory, symbol=symbol, timeframe=timeframe, strategy=strategy,
                      host=host, port=port)
    click.echo(f"MINCODE 대시보드: http://{host}:{port}  (중단: Ctrl-C)")
    click.echo("주의: 비상정지 버튼은 실제 킬스위치입니다 (CLI 'quantpilot panic'과 동일).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        click.echo("\n대시보드 종료.")


if __name__ == "__main__":
    cli()
