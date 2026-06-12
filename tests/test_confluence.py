"""confluence 전략: 점수 합산 + G2/V1 게이트 + risk_mult/targets meta."""
import pandas as pd

from quantpilot.strategy.confluence import ConfluenceStrategy

HOUR = 3_600_000
T0 = 1_780_000_000_000


def make_df(closes, lows=None, highs=None):
    # WHY open=직전 종가: 봉 몸통(close vs open)이 방향을 갖게 해 _one_way(V1) 검증이
    # 의미를 갖는다. 검출기(pivots/zones/divergence/fib)는 high/low/close만 쓰고 open은
    # 안 보므로 open 변경은 그쪽 결과에 영향 없음.
    idx = [T0 + i * HOUR for i in range(len(closes))]
    lows = lows or [c - 1.0 for c in closes]
    highs = highs or [c + 1.0 for c in closes]
    opens = [closes[0]] + list(closes[:-1])
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": [1.0] * len(closes)},
                        index=idx)


def long_setup_df():
    """매물대 지지(이중 바닥) + LL/HL 다이버전스가 겹치는 합성 롱 셋업.

    구조: 100 횡보 → 1차 하락 저점 88(가파름=RSI 깊은 과매도) → 반등 96(피벗 확정) →
    2차 하락 저점 87.5(LL, 완만=RSI HL) → 반등 95(다이버전스 컨펌) → 지지 박스(87.5~88)
    재터치(마지막 봉 ≈88.2). 두 바닥이 ATR×0.5 안에 군집해 매물대를 이룸.
    마지막 20봉은 반등(상승)+짧은 리테스트(하락)라 _one_way(일방 하락) 미발동.
    """
    def ramp(a, b, n):
        return [a + (b - a) * k / n for k in range(1, n + 1)]
    closes = ([100.0] * 20
              + ramp(100, 88, 12)        # 1차 하락 → 88 (가파름)
              + ramp(88, 96, 12)         # 반등 → 96 (1차 L 피벗 확정: +8 > ATR×3)
              + ramp(96, 87.6, 12)       # 2차 하락 → 87.6 (LL, 완만)
              + ramp(87.6, 95, 15)       # 반등 → 95 (2차 L 피벗 확정·다이버전스 컨펌)
              + ramp(95, 87.7, 11))      # 리테스트 → 87.7 (지지 박스 재터치)
    # WHY 꼬리 ±0.5: 매물대는 저가(피벗) 기준이라, 꼬리가 넓으면 종가가 존에서 멀어지고
    # 너무 좁으면 ATR이 작아져 두 바닥이 군집 임계(ATR×0.5)를 못 넘는다. ±0.5가 두 조건
    # (존 상단이 종가에 근접 S1 터치 + 두 바닥 군집)을 동시에 만족하고, 리테스트 저가가
    # 다이버전스 앵커를 안 깨 F1 폐기도 피한다. 최종 점수 5(S1+S2+S5), 계열 3.
    lows = [c - 0.5 for c in closes]
    highs = [c + 0.5 for c in closes]
    return make_df(closes, lows=lows, highs=highs)


def test_long_entry_with_score_and_meta():
    df = long_setup_df()
    strat = ConfluenceStrategy(timeframe="1h", lookback=len(df))
    sig = strat.generate_signal(df, None)
    assert sig.side == "long"
    m = sig.meta
    assert m["score"] >= 4 and m["families"] >= 2
    assert m["risk_mult"] in (0.5, 1.0)
    assert sig.suggested_stop is not None and sig.suggested_stop < df["close"].iloc[-1]
    assert [f for _, f in m["targets"]] == [0.5, 0.4]      # 잔여 10% 러너
    assert all(p > df["close"].iloc[-1] for p, _ in m["targets"])  # 이익 방향


def test_hold_when_position_open():
    df = long_setup_df()
    strat = ConfluenceStrategy(timeframe="1h", lookback=len(df))
    assert strat.generate_signal(df, object()).side == "hold"


def test_g2_rr_gate_blocks_entry():
    df = long_setup_df()
    strat = ConfluenceStrategy(timeframe="1h", lookback=len(df), rr_min=50.0)
    sig = strat.generate_signal(df, None)
    assert sig.side == "hold"
    assert sig.meta.get("blocked") == "G2"


def test_v1_one_way_filter_blocks():
    # 점수와 무관하게, 직전 20봉 일방 하락이면 역추세 롱 차단 — 내부 메서드로 직접 검증
    closes = [200.0 - 3.0 * i for i in range(60)]
    df = make_df(closes)
    strat = ConfluenceStrategy(timeframe="1h", lookback=len(df))
    assert strat._one_way(df, "long") is True
    assert strat._one_way(df, "short") is False
    assert strat.generate_signal(df, None).side == "hold"   # 어떤 이유로든 진입 없음


def test_score_below_threshold_holds():
    df = make_df([100.0] * 60)
    strat = ConfluenceStrategy(timeframe="1h", lookback=60)
    assert strat.generate_signal(df, None).side == "hold"


def test_warmup_holds():
    df = make_df([100.0] * 30)
    strat = ConfluenceStrategy(timeframe="1h")               # 기본 lookback 200
    assert strat.generate_signal(df, None).side == "hold"


def test_confluence_lookahead_free():
    """i봉까지의 window로 낸 신호가 재계산해도 동일(상태 없음·과거 데이터만)."""
    df = long_setup_df()
    strat = ConfluenceStrategy(timeframe="1h", lookback=80)
    n = len(df)
    sides = {}
    for i in range(80, n + 1):
        sides[i] = strat.generate_signal(df.iloc[:i], None).side
    for i in range(80, n + 1, 3):
        again = ConfluenceStrategy(timeframe="1h", lookback=80)
        assert again.generate_signal(df.iloc[:i], None).side == sides[i]
