import pytest

from quantpilot.strategy.base import Signal, IStrategy


def test_signal_construction():
    s = Signal(side="long", confidence=0.8, suggested_stop=100.0, meta={"rsi": 25})
    assert s.side == "long"
    assert s.suggested_stop == 100.0
    assert s.meta["rsi"] == 25


def test_istrategy_is_abstract():
    with pytest.raises(TypeError):
        IStrategy()  # generate_signal 미구현 → 인스턴스화 불가
