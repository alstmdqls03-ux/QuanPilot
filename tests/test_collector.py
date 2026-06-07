from quantpilot.data.collector import drop_unclosed


def test_drop_unclosed_removes_forming_candle():
    tf_ms = 3_600_000  # 1h
    now = 1_700_007_200_000  # 두 번째 봉이 막 열린 시점(아직 안 닫힘)
    rows = [
        {"ts": 1_700_000_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": 1_700_003_600_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": 1_700_007_200_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ]
    kept = drop_unclosed(rows, tf_ms, now)
    # 마지막 봉(ts=...7_200_000)은 ts+tf(...10_800_000) > now 라서 미완성 → 제거.
    # 첫 두 봉은 닫혔으므로 유지.
    assert [r["ts"] for r in kept] == [1_700_000_000_000, 1_700_003_600_000]


def test_drop_unclosed_keeps_all_when_old():
    tf_ms = 3_600_000
    now = 1_800_000_000_000  # 충분히 미래 → 전부 닫힘
    rows = [{"ts": 1_700_000_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    assert len(drop_unclosed(rows, tf_ms, now)) == 1
