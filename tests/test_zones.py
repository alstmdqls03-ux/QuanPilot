"""매물대: 피벗 군집 → 박스. 봉마감 이탈만 인정(휩소 무시), 이탈 후 역할 전환."""
import pandas as pd

from quantpilot.strategy.pivots import Pivot
from quantpilot.strategy.zones import (
    Zone, build_zones, first_zone_above, first_zone_below, touch_side)

HOUR = 3_600_000
T0 = 1_780_000_000_000


def _piv(i, price, kind):
    return Pivot(ts=T0 + i * HOUR, price=price, kind=kind,
                 confirmed_ts=T0 + (i + 2) * HOUR)


def test_build_zones_clusters_nearby_pivots():
    pivots = [_piv(0, 100.0, "L"), _piv(5, 101.0, "L"), _piv(9, 100.5, "L"),
              _piv(3, 130.0, "H")]
    zones = build_zones(pivots, atr_value=4.0, cluster_k=0.5, min_touches=2)
    assert len(zones) == 1                       # 100~101 군집만 (130은 1터치)
    z = zones[0]
    assert z.bottom == 100.0 and z.top == 101.0 and z.touches == 3


def test_zone_break_is_close_based_and_flips_role():
    pivots = [_piv(0, 100.0, "L"), _piv(5, 101.0, "L")]
    closes = pd.Series([102.0, 99.5],
                       index=[T0 + 10 * HOUR, T0 + 11 * HOUR])
    zones = build_zones(pivots, atr_value=4.0, cluster_k=0.5, min_touches=2,
                        closes=closes.iloc[:1])
    assert zones[0].broken_dir is None           # 종가 102 — 이탈 아님
    zones = build_zones(pivots, atr_value=4.0, cluster_k=0.5, min_touches=2,
                        closes=closes)           # 둘째 봉 종가 99.5 < bottom 100
    assert zones[0].broken_dir == "down"         # 하향 이탈 → 이후 저항


def test_touch_and_first_zone_queries():
    z_support = Zone(top=101.0, bottom=100.0, created_ts=T0, touches=2,
                     broken_dir=None)
    z_broken = Zone(top=121.0, bottom=120.0, created_ts=T0, touches=2,
                    broken_dir="down")           # 하향 이탈됨 → 저항 역할
    zones = [z_support, z_broken]
    # 위에서 내려와 상단 근접 → 지지 터치 (proximity = atr×0.25 = 1.0)
    assert touch_side(zones, price=101.5, atr_value=4.0, side="long") is z_support
    # 이탈된 박스는 지지가 아님
    assert touch_side([z_broken], price=120.5, atr_value=4.0, side="long") is None
    # 아래에서 올라와 저항(이탈된 박스 하단) 근접 → 숏 터치
    assert touch_side([z_broken], price=119.5, atr_value=4.0, side="short") is z_broken
    # G2/TP1용: 현재가 위/아래 첫 박스 경계
    assert first_zone_above(zones, price=110.0) == 120.0
    assert first_zone_below(zones, price=110.0) == 101.0
