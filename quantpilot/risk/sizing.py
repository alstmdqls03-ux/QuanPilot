"""per-trade 위험 기반 포지션 사이징 (OKX ctVal 반영, invariant 강제)."""
from __future__ import annotations

from dataclasses import dataclass


class InsufficientCapitalError(Exception):
    """위험 예산으로 최소 1계약도 못 살 때."""


@dataclass
class SizingResult:
    contracts: int
    notional_usd: float
    max_loss_usd: float
    clamped_by_leverage: bool


def calculate_position_size(
    capital: float, risk_pct: float, entry: float, stop: float,
    ct_val: float, lot_sz: float, leverage: int = 3, fee_bps: float = 5.0,
) -> SizingResult:
    """위험 예산(capital×risk_pct) 안에서 계약 수를 계산.

    Invariant(강제 assert): max_loss + fee ≤ capital × risk_pct × 1.02.
    1계약 손실 = price_distance × ct_val. 레버리지 상한으로 notional 클램프.
    """
    risk_amount = capital * risk_pct
    price_distance = abs(entry - stop)
    if price_distance <= 0:
        raise InsufficientCapitalError("entry와 stop이 같음(거리 0)")

    # WHY 수수료를 위험예산에 포함: 1계약 비용 = 손절손실 + 왕복수수료.
    #   risk_amount를 (손실+수수료)로 나눠야 'max_loss + fee ≤ 위험예산'이 보장됨.
    #   (수수료를 빼먹으면 실제 위험이 5%를 초과한다.)
    per_contract_loss = price_distance * ct_val
    per_contract_fee = entry * ct_val * (fee_bps / 10000.0) * 2  # 진입+청산
    per_contract_cost = per_contract_loss + per_contract_fee
    raw = risk_amount / per_contract_cost

    max_notional = capital * leverage
    max_by_lev = max_notional / (entry * ct_val)
    clamped = raw > max_by_lev
    contracts_f = min(raw, max_by_lev)

    # 정수 계약, lot_sz 배수로 라운드다운
    contracts = int(contracts_f // lot_sz * lot_sz)
    if contracts <= 0:
        raise InsufficientCapitalError(
            f"위험예산 {risk_amount:.2f}로 1계약 못 삼 (1계약 비용 {per_contract_cost:.4f})"
        )

    notional = contracts * entry * ct_val
    max_loss = contracts * per_contract_loss
    fee_estimate = contracts * per_contract_fee

    # 손절 손실 + 왕복 수수료가 위험예산을 넘지 않음 (위로 위반 금지)
    assert max_loss + fee_estimate <= capital * risk_pct + 1e-6, (
        f"sizing invariant 위반: max_loss+fee={max_loss+fee_estimate}, target={capital*risk_pct}"
    )
    return SizingResult(
        contracts=contracts, notional_usd=notional,
        max_loss_usd=max_loss, clamped_by_leverage=clamped,
    )
