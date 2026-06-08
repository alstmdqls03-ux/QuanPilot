"""페이퍼 거래 로그·리포트를 초보자 친화적으로 포맷팅하는 표시 레이어(순수 함수).

WHY 분리: 손익(net = gross - fee - funding)·리스크 계산은 engine·store가 소유한다.
여기는 '이미 확정된 숫자'를 사람이 한눈에 읽게(이익/손실 라벨, 읽기 쉬운 시간/가격,
한국어 사유, 누적 요약) 바꾸기만 한다. 순수 함수라 DB 없이 단위 테스트 가능.
"""
from __future__ import annotations

from datetime import datetime, timezone

# 청산 사유(영문 코드) → 한국어. tp1/tp2/tp3는 prefix로 묶어 '분할익절'로.
_REASON_KR = {
    "exit_signal": "RSI중립복귀",
    "stop": "손절",
    "panic": "비상정지",
}


def reason_kr(reason: str) -> str:
    """청산 사유를 한국어로. 미지의 사유는 정보 손실 방지를 위해 원문 그대로 노출."""
    if reason.startswith("tp"):
        return "분할익절"
    return _REASON_KR.get(reason, reason)


def side_kr(side: str) -> str:
    """long→롱(오르면 이익), short→숏(내리면 이익)."""
    return "롱" if side == "long" else "숏"


def fmt_money(x: float) -> str:
    """손익을 '+$32.80' / '-$8.50'로. 부호를 통화기호 앞에 둬 이익/손실이 즉시 보이게."""
    sign = "+" if x >= 0 else "-"
    return f"{sign}${abs(x):,.2f}"


def fmt_ts(ms: int) -> str:
    """유닉스 ms → 'MM-DD HH:MM' (UTC). 거래소·캔들 ts가 UTC라 UTC로 표기(혼동 방지)."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")


def fmt_price(x: float) -> str:
    """가격 천단위 콤마. BTC처럼 큰 값(≥100)은 정수, 저가 코인(<100)은 소수 유지."""
    if abs(x) >= 100:
        return f"{x:,.0f}"
    return f"{x:,.4f}".rstrip("0").rstrip(".")


def _outcome_mark(pnl_net: float) -> str:
    if pnl_net > 0:
        return "✅ 이익"
    if pnl_net < 0:
        return "❌ 손실"
    return "➖ 본전"


def fmt_trade_line(t) -> str:
    """한 거래를 사람이 읽는 한 줄로.

    예) '✅ 이익  +$32.80  숏 4계약  62,586 → 61,704  RSI중립복귀  06-07 13:00'

    WHY pnl_net 부호로 판정: 이익/손실은 수수료·funding까지 반영된 최종 순손익의
    부호. 사용자가 체감하는 '실제 번 돈'과 일치한다(gross로 판정하면 비용 누락).
    """
    return (
        f"{_outcome_mark(t.pnl_net)}  {fmt_money(t.pnl_net)}  "
        f"{side_kr(t.side)} {t.contracts}계약  "
        f"{fmt_price(t.entry)} → {fmt_price(t.exit)}  "
        f"{reason_kr(t.reason)}  {fmt_ts(t.closed_ts)}"
    )


def summarize_trades(trades) -> str:
    """청산 완료 거래들의 누적 요약 한 줄.

    예) '2건  ✅ 2  ❌ 0  확정손익 +$48.09  승률 100%'

    WHY '확정손익'이라 명시: 미실현(열린 포지션 평가손익)은 거래 로그에 없으므로
    이 합계는 '청산 완료' 기준이다. paper-status의 미실현 포함 equity와 다를 수
    있음을 사용자가 혼동하지 않게 라벨로 구분.
    """
    n = len(trades)
    wins = sum(1 for t in trades if t.pnl_net > 0)
    losses = sum(1 for t in trades if t.pnl_net < 0)
    realized = sum(t.pnl_net for t in trades)
    win_rate = (wins / n * 100.0) if n else 0.0
    return (
        f"{n}건  ✅ {wins}  ❌ {losses}  "
        f"확정손익 {fmt_money(realized)}  승률 {win_rate:.0f}%"
    )
