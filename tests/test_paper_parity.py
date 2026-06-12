"""백테스트 == 페이퍼 parity 테스트(crown jewel).

WHY 이 테스트: 동일한 봉 시퀀스를 ①run_backtest 통째 ②process_bar 봉마다 실행해
거래와 최종 equity가 일치하는지 강제한다. 두 경로가 달라지면 페이퍼 결과를 신뢰할 수 없음.
"""
import pandas as pd

from quantpilot.backtest.engine import run_backtest
from quantpilot.paper.store import PaperState, make_run_key
from quantpilot.paper.trader import TickContext, process_bar
from quantpilot.strategy.base import IStrategy, Signal


class _LongOnce(IStrategy):
    name = "p-long"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("long", 1.0, price - 5.0, {})
        return Signal("hold", 0.0, None, {})


def _candles(closes):
    tf = 3_600_000
    base = 1_700_000_000_000
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes,
         "volume": [1.0] * len(closes)},
        index=[base + i * tf for i in range(len(closes))]).rename_axis("ts")


def _ohlc(rows):
    """rows: [(open, high, low, close), ...] → ts 인덱스 DataFrame (volume=1)."""
    tf = 3_600_000
    base = 1_700_000_000_000
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows],
         "volume": [1.0] * len(rows)},
        index=[base + i * tf for i in range(len(rows))],
    ).rename_axis("ts")


def _run_paper(strategy, df, capital=1000.0, name="p-long"):
    """df를 process_bar 봉마다 돌려 (paper_state, paper_trades) 반환.

    WHY 헬퍼화: 아래 3개 parity 테스트가 모두 동일한 루프 구조를 공유하므로
    중복 제거. 백테 엔진의 lookback 시작 인덱스를 strategy 속성에서 읽어
    하드코딩 오류 위험을 없앤다.
    """
    rk = make_run_key("BTC-USDT-SWAP", "1h", name)
    ctx = TickContext(session=None, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=strategy, capital=capital,
                      leverage=3, ct_val=0.01, lot_sz=1.0, fee_bps=5, slippage_bps=2,
                      run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy=name, equity=capital, day_start_equity=capital,
                    day_start_ts=0)
    lookback = ctx.strategy.lookback
    paper_trades = []
    for i in range(lookback, len(df)):
        t = int(df.index[i])
        window = df.iloc[i - lookback + 1: i + 1]
        bar = {"ts": t, "open": float(df.at[t, "open"]), "high": float(df.at[t, "high"]),
               "low": float(df.at[t, "low"]), "close": float(df.at[t, "close"])}
        st, trades = process_bar(ctx, st, bar, window, funding_events=[])
        paper_trades.extend(trades)
    return st, paper_trades


def _bt(strategy, df, capital=1000.0):
    return run_backtest(candles=df, strategy=strategy, capital=capital, ct_val=0.01,
                        lot_sz=1.0, leverage=3, fee_bps=5, slippage_bps=2,
                        funding_events=[], oos_split_ts=df.index[-1])


def _trade_key(t):
    """거래 비교용 튜플 (side/entry/exit/reason/pnl_net 6dp 반올림)."""
    return (t.side, round(t.entry, 6), round(t.exit, 6), t.reason, round(t.pnl_net, 6))


def test_paper_matches_backtest():
    # 동일 봉 시퀀스를 ①run_backtest 통째 ②process_bar 봉마다 → 거래·최종 equity 일치
    closes = [100.0, 100, 100, 90]   # 진입 후 급락 → 손절(끝에 flat)
    df = _candles(closes)
    bt = _bt(_LongOnce(), df)

    rk = make_run_key("BTC-USDT-SWAP", "1h", "p-long")
    ctx = TickContext(session=None, client=None, symbol="BTC-USDT-SWAP",
                      timeframe="1h", strategy=_LongOnce(), capital=1000.0,
                      leverage=3, ct_val=0.01, lot_sz=1.0, fee_bps=5, slippage_bps=2,
                      run_key=rk)
    st = PaperState(run_key=rk, symbol="BTC-USDT-SWAP", timeframe="1h",
                    strategy="p-long", equity=1000.0, day_start_equity=1000.0,
                    day_start_ts=0)
    lookback = ctx.strategy.lookback  # 엔진과 동일 시작 인덱스 보장(하드코딩 시 어긋날 위험)
    paper_trades = []
    for i in range(lookback, len(df)):
        t = int(df.index[i])
        window = df.iloc[i - lookback + 1: i + 1]
        bar = {"ts": t, "open": float(df.at[t, "open"]), "high": float(df.at[t, "high"]),
               "low": float(df.at[t, "low"]), "close": float(df.at[t, "close"])}
        st, trades = process_bar(ctx, st, bar, window, funding_events=[])
        paper_trades.extend(trades)

    # 거래 일치(side/entry/exit/reason/pnl_net)
    assert [_trade_key(t) for t in paper_trades] == [_trade_key(t) for t in bt.trades]
    # 최종 실현 equity 일치 (끝에 flat이므로 곡선 마지막 = 실현)
    assert abs(st.equity - bt.equity_curve[-1][1]) < 1e-6


# ─── 분할익절(partial-TP) parity ────────────────────────────────────────────

class _MultiTPLongOnce(IStrategy):
    """첫 진입 가능 시점에 long 1회(stop=price-5). 분할 익절 ladder 사용."""
    name = "p-long-tp"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("long", 1.0, price - 5.0, {})
        return Signal("hold", 0.0, None, {})


def test_paper_matches_backtest_partial_tp():
    """분할익절 시나리오: bar에서 TP1 체결(33% 부분 청산), 다음 bar에서 손절 전량.

    WHY 이 테스트가 crown-jewel: pending_fills가 봉을 넘어 누적되고 build_trade가
    가중평균 exit을 계산하는 경로가 백테와 페이퍼 양쪽에서 동일한지 검증.
    두 엔진이 다른 결과를 내면 페이퍼를 신뢰할 수 없음(backtest=live 불변식 위반).

    봉 구성:
      bar0, bar1  warmup (close=100, high=101, low=99)
      bar2        진입봉 (close=100 → entry=100.02 with 2bps buy slippage, stop=95)
                  TP1 ≈ 105.04, TP2 ≈ 110.06, TP3 ≈ 115.08
      bar3        TP1 봉 (high=106 ≥ tp1, low=100 > stop=95 → 부분 청산, stop 미발동)
      bar4        손절봉 (low=89 ≤ stop=95 → 잔여 전량 손절)
    """
    df = _ohlc([
        (100, 101, 99, 100),   # bar0 warmup
        (100, 101, 99, 100),   # bar1 warmup
        (100, 101, 99, 100),   # bar2 entry (close=100)
        (100, 106, 100, 100),  # bar3 TP1 hit (high=106 > ~105.04), low=100 > stop=95
        (90,  96,  89,  90),   # bar4 stop (low=89 <= stop=95)
    ])

    bt = _bt(_MultiTPLongOnce(), df)
    st, paper_trades = _run_paper(_MultiTPLongOnce(), df, name="p-long-tp")

    # 두 엔진 모두 정확히 1건의 복합 거래(tp1 + stop 가중평균)를 생성해야 함
    assert len(bt.trades) == 1, f"백테 거래 수 != 1: {len(bt.trades)}"
    assert len(paper_trades) == 1, f"페이퍼 거래 수 != 1: {len(paper_trades)}"

    # stop이 마지막 fill이므로 reason="stop", 분할 익절이 있었으므로 exit != entry
    assert bt.trades[0].reason == "stop"
    assert paper_trades[0].reason == "stop"

    # 거래 일치(side/entry/exit_weighted_avg/reason/pnl_net 6dp)
    assert _trade_key(paper_trades[0]) == _trade_key(bt.trades[0]), (
        f"parity 불일치: paper={_trade_key(paper_trades[0])}, bt={_trade_key(bt.trades[0])}")

    # 최종 equity 일치 (bar4에서 flat → 곡선 마지막 = 실현 equity)
    assert abs(st.equity - bt.equity_curve[-1][1]) < 1e-6, (
        f"equity 불일치: paper={st.equity}, bt={bt.equity_curve[-1][1]}")


# ─── confluence meta parity (BE트레일 + risk_mult + targets) ─────────────────

class _ConfluenceLikeLongOnce(IStrategy):
    """confluence 출력 모사: meta[targets]+risk_mult, be_trail_after_tp1=True.

    WHY 스텁: 실 ConfluenceStrategy로 거래를 유발하는 fixture는 까다로움.
    엔진의 targets 주입·risk_mult·BE트레일 경로가 백테=페이퍼 동일한지가 진짜 관심사이므로
    confluence 출력을 직접 내는 스텁으로 충분히 검증 가능.
    """
    name = "p-confl"
    be_trail_after_tp1 = True      # process_bar가 getattr로 읽어 엔진에 전달

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        if open_position is None and not self._entered:
            self._entered = True
            price = float(window["close"].iloc[-1])
            stop = price - 5.0
            return Signal("long", 0.5, stop,
                          {"risk_mult": 0.5,
                           "targets": [(price + 5.0, 0.5), (price + 12.0, 0.4)]})
        return Signal("hold", 0.0, None, {})


def test_paper_matches_backtest_confluence_meta():
    """confluence 경로(meta targets·risk_mult·BE트레일)가 백테=페이퍼 동일.

    봉 구성:
      bar0, bar1  warmup (close=100)
      bar2        진입봉 (close=100 → entry≈100.02, stop=95, risk_mult=0.5)
                  TP1=105 (50%), TP2=112 (40%)
      bar3        TP1봉 (high=106 ≥ TP1=105 → 부분청산 50%, BE이동 stop=entry≈100.02)
                  low=100 > stop=95(원래) → stop 미발동
      bar4        BE손절봉 (low=99 ≤ BE stop≈100.02 → 잔여 전량 손절)

    WHY be_trail_after_tp1 클래스 속성으로 충분: process_bar가
    getattr(ctx.strategy, 'be_trail_after_tp1', False)로 읽으므로
    인스턴스가 아닌 클래스 속성도 동작한다. T9 회귀 없음을 확인.
    """
    df = _ohlc([
        (100, 101, 99, 100),   # bar0 warmup
        (100, 101, 99, 100),   # bar1 warmup
        (100, 101, 99, 100),   # bar2 진입 (close=100, stop=95, tp1=105)
        (100, 106, 100, 100),  # bar3 TP1 체결 (high=106 ≥ 105), low=100 > stop=95
        (100, 101,  99, 100),  # bar4 BE 손절 (low=99 ≤ entry≈100.02)
    ])

    bt = _bt(_ConfluenceLikeLongOnce(), df)
    st, paper_trades = _run_paper(_ConfluenceLikeLongOnce(), df, name="p-confl")

    # 양쪽 모두 정확히 1건(부분익절+BE손절이 1건의 복합 Trade로 집계)
    assert len(bt.trades) == 1, f"백테 거래 수 != 1: {len(bt.trades)}"
    assert len(paper_trades) == 1, f"페이퍼 거래 수 != 1: {len(paper_trades)}"

    # TP1 부분청산이 있었으므로 마지막 fill은 stop(BE) → reason="stop"
    assert bt.trades[0].reason == "stop", f"bt reason={bt.trades[0].reason}"
    assert paper_trades[0].reason == "stop", f"paper reason={paper_trades[0].reason}"

    # 거래 일치(side/entry/exit_weighted_avg/reason/pnl_net 6dp)
    assert _trade_key(paper_trades[0]) == _trade_key(bt.trades[0]), (
        f"parity 불일치:\n  paper={_trade_key(paper_trades[0])}\n"
        f"  bt={_trade_key(bt.trades[0])}")

    # 최종 equity 일치 (bar4에서 flat → 곡선 마지막 = 실현 equity)
    assert abs(st.equity - bt.equity_curve[-1][1]) < 1e-6, (
        f"equity 불일치: paper={st.equity}, bt={bt.equity_curve[-1][1]}")


# ─── 숏 사이드 parity ────────────────────────────────────────────────────────

class _ShortOnce(IStrategy):
    """첫 진입 가능 시점에 short 1회(stop=price+5). 숏 parity 검증용."""
    name = "p-short"

    def __init__(self):
        self.timeframe = "1h"
        self.lookback = 2
        self._entered = False

    def generate_signal(self, window, open_position):
        price = float(window["close"].iloc[-1])
        if open_position is None and not self._entered:
            self._entered = True
            return Signal("short", 1.0, price + 5.0, {})
        return Signal("hold", 0.0, None, {})


def test_paper_matches_backtest_short():
    """숏 사이드 parity: 진입 → 손절(stop=price+5, high≥stop).

    WHY 이 테스트: 숏 슬리피지 방향(sell side → 아래로 불리, entry는 낮아짐)과
    PnL 부호(entry-exit)가 백테=페이퍼 양쪽에서 동일한지 검증.
    숏 경로가 롱과 다른 슬리피지/사이징/check_exits 분기를 통과하기 때문에
    별도 parity 테스트가 필요.

    봉 구성:
      bar0, bar1  warmup (close=100)
      bar2        진입봉 (close=100 → short entry=99.98 with 2bps sell slippage, stop=105)
      bar3        손절봉 (high=106 ≥ stop=105 → 전량 손절)
    """
    df = _ohlc([
        (100, 101, 99, 100),   # bar0 warmup
        (100, 101, 99, 100),   # bar1 warmup
        (100, 101, 99, 100),   # bar2 short entry (close=100, stop=105)
        (102, 106, 101, 102),  # bar3 stop-out (high=106 >= stop=105)
    ])

    bt = _bt(_ShortOnce(), df)
    st, paper_trades = _run_paper(_ShortOnce(), df, name="p-short")

    # 숏 포지션이 실제로 발생했는지 확인(진입 조건 충족)
    assert bt.trades, "백테에서 숏 거래가 없음 — 시나리오 설계 오류"
    assert paper_trades, "페이퍼에서 숏 거래가 없음 — parity 위반 가능"

    assert all(t.side == "short" for t in bt.trades)
    assert all(t.side == "short" for t in paper_trades)

    # 거래 수 일치
    assert len(paper_trades) == len(bt.trades), (
        f"숏 거래 수 불일치: paper={len(paper_trades)}, bt={len(bt.trades)}")

    # 거래 상세 일치(side/entry/exit/reason/pnl_net 6dp)
    assert [_trade_key(t) for t in paper_trades] == [_trade_key(t) for t in bt.trades], (
        f"숏 parity 불일치:\n  paper={[_trade_key(t) for t in paper_trades]}\n"
        f"  bt={[_trade_key(t) for t in bt.trades]}")

    # 최종 equity 일치
    assert abs(st.equity - bt.equity_curve[-1][1]) < 1e-6, (
        f"숏 equity 불일치: paper={st.equity}, bt={bt.equity_curve[-1][1]}")
