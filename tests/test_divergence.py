"""RSI 다이버전스: 확정 피벗 2개 비교 + 유효 구간(30/70) + 컨펌·폐기(F1)."""
import pandas as pd

from quantpilot.strategy.divergence import Divergence, detect_divergence
from quantpilot.strategy.pivots import Pivot

HOUR = 3_600_000
T0 = 1_780_000_000_000


def _l(i, price):
    return Pivot(ts=T0 + i * HOUR, price=price, kind="L",
                 confirmed_ts=T0 + (i + 2) * HOUR)


def _h(i, price):
    return Pivot(ts=T0 + i * HOUR, price=price, kind="H",
                 confirmed_ts=T0 + (i + 2) * HOUR)


def _rsi(pairs, n=40):
    """ts→rsi 시리즈. pairs=[(bar_idx, rsi값)], 나머지 50."""
    idx = [T0 + i * HOUR for i in range(n)]
    s = pd.Series(50.0, index=idx)
    for i, v in pairs:
        s.iloc[i] = v
    return s


def _lows(pairs, n=40):
    idx = [T0 + i * HOUR for i in range(n)]
    s = pd.Series(1e9, index=idx)        # 기본 = 재이탈 없음 (롱용: 저가가 절대 하향돌파 안 함)
    for i, v in pairs:
        s.iloc[i] = v
    return s


def _highs(pairs, n=40):
    idx = [T0 + i * HOUR for i in range(n)]
    s = pd.Series(0.0, index=idx)        # 기본 = 재이탈 없음 (숏용: 고가가 절대 상향돌파 안 함)
    for i, v in pairs:
        s.iloc[i] = v
    return s


def test_bullish_divergence_confirmed():
    pivots = [_l(5, 100.0), _h(10, 120.0), _l(20, 95.0)]   # LL
    rsi = _rsi([(5, 25.0), (20, 28.0)])                     # HL, 28<=30 유효구간
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 23 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert isinstance(d, Divergence) and d.confirmed
    assert d.anchor.price == 95.0


def test_divergence_discarded_on_reentry():  # F1
    pivots = [_l(5, 100.0), _h(10, 120.0), _l(20, 95.0)]
    rsi = _rsi([(5, 25.0), (20, 28.0)])
    lows = _lows([(24, 94.0)])           # 24번 봉 저가가 95 재이탈
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 25 * HOUR,
                          lows=lows, highs=None, extreme=30.0)
    assert d is None


def test_divergence_requires_extreme_zone():
    pivots = [_l(5, 100.0), _l(20, 95.0)]
    rsi = _rsi([(5, 33.0), (20, 35.0)])  # 35 > 30 → 과매도 밖 → 무효
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 23 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert d is None


def test_double_divergence_flag():
    pivots = [_l(3, 105.0), _l(12, 100.0), _l(22, 95.0)]   # LL 연속 2쌍
    rsi = _rsi([(3, 22.0), (12, 25.0), (22, 28.0)])         # HL 연속
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 25 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert d is not None and d.double


def test_not_confirmed_before_pivot_confirmation():
    pivots = [_l(5, 100.0), _l(20, 95.0)]   # 둘째 피벗 confirmed_ts = 22번 봉
    rsi = _rsi([(5, 25.0), (20, 28.0)])
    d = detect_divergence(pivots, rsi, side="long", now_ts=T0 + 21 * HOUR,
                          lows=_lows([]), highs=None, extreme=30.0)
    assert d is None


def test_bearish_divergence_mirror():
    pivots = [_h(5, 100.0), _l(10, 80.0), _h(20, 105.0)]   # HH
    rsi = _rsi([(5, 75.0), (20, 72.0)])                     # LH, 72>=70 유효
    d = detect_divergence(pivots, rsi, side="short", now_ts=T0 + 23 * HOUR,
                          lows=None, highs=_highs([]), extreme=70.0)
    assert d is not None and d.anchor.price == 105.0


def test_extreme_is_required_kwarg():
    import inspect
    from quantpilot.strategy.divergence import detect_divergence as _dd
    sig = inspect.signature(_dd)
    assert sig.parameters["extreme"].default is inspect.Parameter.empty
