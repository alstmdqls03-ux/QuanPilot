from quantpilot.config import Settings


def test_default_db_path():
    s = Settings()
    assert s.db_path == "data/quantpilot.db"
    assert s.db_url == "sqlite:///data/quantpilot.db"


def test_env_override(monkeypatch):
    monkeypatch.setenv("QUANTPILOT_DB_PATH", "/tmp/custom.db")
    s = Settings()
    assert s.db_path == "/tmp/custom.db"
    assert s.db_url == "sqlite:////tmp/custom.db"
