"""Fix 1: 마지막 타깃 흡수가 의도적 러너를 삼키지 않아야 함.

WHY: confluence는 targets=[(tp1,0.5),(tp2,0.4)] (합 0.9, 10% 러너 의도)를 내는데,
수정 전엔 tp2가 '마지막 타깃'이라 남은 50% 전량을 흡수 → 러너가 사라짐.
수정 후: qty<=0일 때만 흡수(원 의도 = 1계약 round→0 구제). qty>0이면 보존.

/review Claude+Codex 확정.
"""
from quantpilot.backtest.engine import check_exits
from quantpilot.backtest.models import Position


# ─── 10계약, targets=[(p1,0.5),(p2,0.4)] ─────────────────────────────────────

def _pos_10ct(tp1, tp2):
    """10계약 롱 포지션, stop=90, TP1 tp1 (50%), TP2 tp2 (40%), 러너 10% 의도."""
    return Position(side="long", entry=100.0, contracts=10, stop=90.0,
                    targets_remaining=[(tp1, 0.5), (tp2, 0.4)],
                    opened_ts=0, original_contracts=10)


def test_runner_preserved_after_tp1():
    """TP1 히트봉: tp1 체결(5계약) 후 tp2 미달 → 러너 5계약 보존.

    WHY: 수정 전엔 tp1 체결봉에서 tp2(마지막)가 흡수 발동 안 함(tp2 미달이므로 hit=False).
    이 테스트는 tp1이 단독으로 체결될 때 포지션이 5계약(=original*0.5=int(round(10*0.5)))
    남아야 함을 단언.
    """
    pos = _pos_10ct(tp1=105.0, tp2=115.0)
    # high=106 → tp1=105 체결, tp2=115 미달
    bar = {"ts": 1, "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0}
    pos2, fills = check_exits(pos, bar, fee_bps=5.0, slippage_bps=0.0, ct_val=0.01)
    assert fills, "tp1 봉에서 fill이 없음"
    assert sum(f.contracts for f in fills) == 5, (
        f"tp1 체결 수량={sum(f.contracts for f in fills)} != 5")
    assert pos2 is not None, "tp1 단독 체결 후 포지션이 종료됨(러너가 사라짐)"
    assert pos2.contracts == 5, f"러너 보존 실패: pos2.contracts={pos2.contracts} != 5"


def test_runner_preserved_after_tp1_and_tp2_both_hit():
    """TP1+TP2 둘 다 닿는 봉: tp1=5·tp2=4 체결 후 pos.contracts==1 (러너 보존).

    WHY 핵심 회귀: 수정 전엔 tp2가 마지막 타깃이라 contracts_left(=5) 전량 흡수
    → pos.contracts==0이 되고 None 반환(포지션 종료). 러너 의도가 조용히 사라짐.
    수정 후: tp2의 qty=int(round(10*0.4))=4 그대로 처리, 잔여 1계약이 러너로 남음.
    """
    pos = _pos_10ct(tp1=105.0, tp2=112.0)
    # high=113 → tp1=105(hit), tp2=112(hit) 둘 다 닿는 봉
    bar = {"ts": 1, "open": 100.0, "high": 113.0, "low": 99.0, "close": 112.5}
    pos2, fills = check_exits(pos, bar, fee_bps=5.0, slippage_bps=0.0, ct_val=0.01)
    # tp1=5계약, tp2=4계약 체결
    assert len(fills) == 2, f"fills 수={len(fills)}, 2개(tp1+tp2) 기대"
    assert fills[0].contracts == 5, f"tp1 수량={fills[0].contracts} != 5"
    assert fills[1].contracts == 4, f"tp2 수량={fills[1].contracts} != 4"
    # 러너: 10 - 5 - 4 = 1계약 보존
    assert pos2 is not None, "러너가 있어야 하는데 포지션 종료됨"
    assert pos2.contracts == 1, (
        f"러너 보존 실패: pos2.contracts={pos2.contracts} != 1 "
        f"(수정 전: tp2가 마지막 타깃이라 5계약 전량 흡수됨)")


# ─── 1계약 사다리 — 마지막 타깃 흡수가 여전히 동작해야 함 ──────────────────────

def test_one_contract_ladder_last_target_still_absorbs():
    """1계약에서 모든 타깃이 round→0: 마지막 타깃이 잔량 흡수해 전량 체결.

    WHY: Fix 1은 qty<=0일 때만 흡수를 유지해야 함. qty=int(round(1*0.34))=0이므로
    조건을 만족 → 흡수 발동. 러너 보존 테스트와 직교적(qty>0 vs qty<=0 분기).
    """
    pos = Position(side="long", entry=100.0, contracts=1, stop=90.0,
                   targets_remaining=[(103.0, 0.33), (108.0, 0.33), (115.0, 0.34)],
                   opened_ts=0, original_contracts=1)
    # 셋 다 닿는 봉 (high=116)
    bar = {"ts": 1, "open": 100.0, "high": 116.0, "low": 99.0, "close": 115.5}
    pos2, fills = check_exits(pos, bar, fee_bps=5.0, slippage_bps=0.0, ct_val=0.01)
    assert fills, "1계약 사다리에서 fill이 없음"
    assert sum(f.contracts for f in fills) == 1, (
        f"1계약 전량 체결 실패: {sum(f.contracts for f in fills)} != 1")
    assert pos2 is None, "1계약 전량 체결 후 포지션이 남아 있음"
