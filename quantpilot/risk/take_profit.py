"""분할 익절 타겟 생성. 사용자 원래 구상 '적정 비율로 분할 익절'."""
from __future__ import annotations


def build_targets(entry: float, stop: float, side: str,
                  r_multiples: list[float] | None = None,
                  fractions: list[float] | None = None) -> list[tuple[float, float]]:
    """R-배수 기반 분할 익절 타겟 리스트.

    R = |entry - stop|. target = entry ± R×r (long은 위, short은 아래).
    반환: [(price, fraction), ...]  fraction은 진입 수량 대비 청산 비율.
    """
    r_multiples = r_multiples or [1.0, 2.0, 3.0]
    fractions = fractions or [0.33, 0.33, 0.34]
    if len(r_multiples) != len(fractions):
        raise ValueError("r_multiples와 fractions 길이가 다름")
    r = abs(entry - stop)
    sign = 1.0 if side == "long" else -1.0
    return [(entry + sign * r * rr, frac) for rr, frac in zip(r_multiples, fractions)]
