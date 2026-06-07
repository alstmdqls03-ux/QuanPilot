"""앱 설정. 환경변수(.env) → pydantic-settings로 로드."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUANTPILOT_", env_file=".env", extra="ignore")

    exchange: str = "okx"
    db_path: str = "data/quantpilot.db"

    @property
    def db_url(self) -> str:
        """SQLAlchemy용 SQLite URL.

        WHY 분기 불필요: 'sqlite:///' + 경로 concat이 두 경우를 다 맞춘다.
        절대경로는 앞의 '/'가 더해져 슬래시 4개가 됨
        ('/tmp/x.db' → 'sqlite:////tmp/x.db'), 상대경로는 3개
        ('data/x.db' → 'sqlite:///data/x.db'). 별도 if 분기가 필요 없다.
        """
        return f"sqlite:///{self.db_path}"
