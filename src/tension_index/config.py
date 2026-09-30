"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    anthropic_api_key: str = ""
    # Classifier model; cheaper option: claude-haiku-4-5 (then set CLASSIFIER_EFFORT="")
    classifier_model: str = "claude-opus-5-5"
    classifier_effort: str = "low"
    classifier_max_calls: int = 60  # per run; beyond it rules are used (spend guard)

    database_path: Path = Path("data/tension.sqlite3")

    http_timeout_seconds: float = 30.0
    http_user_agent: str = "TensionIndexBot/0.1 (+https://github.com/FixerHack/war-predictor)"

    health_max_collect_age_hours: float = 8.0
    health_min_free_disk_mb: int = 500
    health_ping_url: str = ""

    log_level: str = "INFO"

    @field_validator("telegram_admin_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(" ", "").split(",") if part]
        if isinstance(value, int):
            return [value]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
