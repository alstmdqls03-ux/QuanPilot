"""앱 설정. 환경변수(.env) → pydantic-settings로 로드."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUANTPILOT_", env_file=".env", extra="ignore")

    exchange: str = "okx"
    db_path: str = "data/quantpilot.db"

    @property
    def db_url(self) -> str:
        """SQLAlchemy용 URL.

        WHY 절대경로 처리: SQLite는 절대경로 앞에 슬래시가 하나 더 붙음.
        '/tmp/x.db' → 'sqlite:////tmp/x.db', 'data/x.db' → 'sqlite:///data/x.db'.
        """
        if self.db_path.startswith("/"):
            return f"sqlite:///{self.db_path}"
        return f"sqlite:///{self.db_path}"
