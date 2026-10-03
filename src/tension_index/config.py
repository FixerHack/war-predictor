"""Application settings, loaded from environment variables and `.env`."""

import sys
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    # Classifier: "anthropic" (direct) or "openrouter". Empty model = provider default
    # (anthropic: claude-opus-5-5, openrouter: anthropic/claude-haiku-4.5).
    # claude_code: the local `claude` CLI (Claude Code, signed in with a Claude subscription)
    # gateway: a claude-gateway service (github.com/FixerHack/claude-gateway) at GATEWAY_URL
    classifier_provider: Literal["anthropic", "openrouter", "claude_code", "gateway"] = "anthropic"
    classifier_model: str = ""
    classifier_effort: str = "low"  # Anthropic API only; empty for models without effort
    classifier_max_calls: int = 60  # per run; beyond it rules are used (spend guard)
    claude_code_bin: str = "claude"  # path or name of the Claude Code CLI
    # Public map; the bot links each country to <url>#<code>
    dashboard_url: str = "https://fixerhack.github.io/war-predictor/dashboard/"
    classifier_concurrency: int = 4  # model calls in parallel
    gateway_url: str = ""  # e.g. http://127.0.0.1:8787
    gateway_token: str = ""

    # Sources skipped by the regular cycle (comma-separated). Australia's site does not
    # answer automated requests (tested 2026-09-30); `probe au` still works.
    disabled_sources: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["au"])

    database_path: Path = Path("data/tension.sqlite3")

    http_timeout_seconds: float = 30.0
    http_user_agent: str = "TensionIndexBot/0.1 (+https://github.com/FixerHack/war-predictor)"

    health_max_collect_age_hours: float = 8.0
    health_min_free_disk_mb: int = 500
    health_ping_url: str = ""

    log_level: str = "INFO"

    @model_validator(mode="before")
    @classmethod
    def _model_in_provider(cls, data: object) -> object:
        """Accept a model id put into CLASSIFIER_PROVIDER by mistake (e.g.
        "anthropic/claude-haiku-4.5"): an OpenRouter-style id means provider openrouter."""
        if not isinstance(data, dict):
            return data
        provider = str(data.get("classifier_provider") or "").strip()
        if "/" in provider:
            sys.stderr.write(
                f"warning: CLASSIFIER_PROVIDER={provider!r} looks like a model id; using "
                f"CLASSIFIER_PROVIDER=openrouter"
                + ("" if data.get("classifier_model") else f" and CLASSIFIER_MODEL={provider}")
                + ". Fix .env to silence this.\n"
            )
            data = {**data, "classifier_provider": "openrouter"}
            if not data.get("classifier_model"):
                data["classifier_model"] = provider
        elif provider:
            data = {**data, "classifier_provider": provider.lower().replace("-", "_")}
        return data

    @field_validator("disabled_sources", mode="before")
    @classmethod
    def _split_names(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

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


def settings_error_text(exc: Exception) -> str:
    """One readable line per invalid .env setting (instead of a pydantic traceback)."""
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return str(exc)
    lines = ["Invalid settings in .env (or environment):"]
    for err in exc.errors():
        name = ".".join(str(x) for x in err["loc"]).upper()
        lines.append(f"  {name} = {err.get('input')!r}: {err['msg']}")
    lines.append("See .env.example for the expected values.")
    return "\n".join(lines)
