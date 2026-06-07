"""OKX ccxt 래퍼. 거래소 통신과 응답 정규화만 담당 (DB 모름).

WHY 래퍼: ccxt 호출을 한 군데로 모으면 (1) OKX 네이티브 심볼↔통합 심볼
변환, (2) 일시적 네트워크 오류 재시도, (3) 거래소 교체를 여기 한 곳에서 처리.
"""
from __future__ import annotations

import time

import ccxt

# 일시적이라 재시도하면 풀리는 오류들 (spec section 8: 종류 A).
# WHY 이 둘만: NetworkError는 타임아웃/일시 단절, RateLimitExceeded는 429.
# 나머지(BadSymbol 등)는 사람이 고쳐야 하므로 재시도 안 함.
_RETRYABLE = (ccxt.NetworkError, ccxt.RateLimitExceeded)


class OKXClient:
    def __init__(self, ccxt_client=None):
        """ccxt_client 주입 가능(테스트는 가짜 주입). 없으면 실제 ccxt 생성."""
        if ccxt_client is None:
            # WHY enableRateLimit: ccxt가 요청 간격을 자동 조절. Week 1엔 직접
            # 토큰버킷 불필요. public 엔드포인트라 API 키도 불필요.
            ccxt_client = ccxt.okx({"enableRateLimit": True})
        self._ccxt = ccxt_client
        self._markets: dict | None = None
        self._id_to_unified: dict[str, str] = {}

    def _retry(self, fn, attempts: int = 4, base_delay: float = 1.0):
        """fn()을 호출하되 일시적 오류면 backoff 후 재시도.

        WHY backoff(1s→2s→4s): 빠르게 다시 때리면 거래소가 더 오래 막음.
        attempts번 모두 실패하면 마지막 예외를 올려 호출부가 알게 함
        (증분 설계라 재실행하면 마지막 저장 ts부터 자동 재개).
        """
        for i in range(attempts):
            try:
                return fn()
            except _RETRYABLE:
                if i == attempts - 1:
                    raise
                time.sleep(base_delay * (2 ** i))

    def load_markets(self) -> dict:
        """마켓 로드 + OKX id → 통합 심볼 매핑 구축."""
        self._markets = self._retry(self._ccxt.load_markets)
        # WHY 매핑: 우리는 'BTC-USDT-SWAP'(네이티브 id)로 다루지만
        # ccxt 호출엔 'BTC/USDT:USDT'(통합 심볼)가 필요.
        self._id_to_unified = {
            m["id"]: unified for unified, m in self._markets.items()
        }
        return self._markets

    def resolve_symbol(self, okx_symbol: str) -> str:
        """'BTC-USDT-SWAP'(네이티브) → 'BTC/USDT:USDT'(ccxt 통합)."""
        if not self._id_to_unified:
            raise RuntimeError("load_markets()를 먼저 호출해야 함")
        try:
            return self._id_to_unified[okx_symbol]
        except KeyError:
            raise ValueError(
                f"심볼 '{okx_symbol}'를 OKX에서 못 찾음. "
                f"네이티브 id 예: BTC-USDT-SWAP"
            )

    def fetch_ohlcv(self, okx_symbol: str, timeframe: str,
                    since_ms: int, limit: int = 100) -> list[dict]:
        """OHLCV 1배치를 정규화된 dict 리스트로 반환."""
        unified = self.resolve_symbol(okx_symbol)
        raw = self._retry(
            lambda: self._ccxt.fetch_ohlcv(unified, timeframe, since=since_ms, limit=limit)
        )
        # ccxt 반환: [ts, open, high, low, close, volume]
        return [
            {"ts": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]}
            for r in raw
        ]

    def fetch_funding(self, okx_symbol: str, since_ms: int,
                      limit: int = 100) -> list[dict]:
        """funding rate 이력 1배치를 정규화된 dict 리스트로 반환."""
        unified = self.resolve_symbol(okx_symbol)
        raw = self._retry(
            lambda: self._ccxt.fetch_funding_rate_history(unified, since=since_ms, limit=limit)
        )
        return [{"ts": r["timestamp"], "funding_rate": r["fundingRate"]} for r in raw]
