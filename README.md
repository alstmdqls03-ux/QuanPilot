# QuantPilot — Week 1: 데이터 수집

OKX 시장 데이터(가격 캔들 + funding rate)를 로컬 SQLite에 적재하는 CLI.
Week 1은 public 데이터만 쓰므로 **API 키가 필요 없습니다**.

## 설치
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## 사용
```bash
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 1h --days 365
quantpilot collect --symbol BTC-USDT-SWAP --timeframe 15m --days 365
quantpilot collect-funding --symbol BTC-USDT-SWAP --days 365
quantpilot status
```

수집은 idempotent 증분입니다 — 다시 실행하면 새 데이터만 이어붙고 중복은 무시됩니다.

## 테스트
```bash
pytest             # 빠른 단위 테스트 (fixture 기반)
pytest -m live     # 실제 OKX 연결 확인 (인터넷 필요, 수동)
```

## 설계
- Spec: `docs/superpowers/specs/2026-06-07-week1-data-foundation-design.md`
- Plan: `docs/superpowers/plans/2026-06-07-week1-data-foundation.md`
