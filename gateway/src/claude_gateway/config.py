"""Settings from environment variables (GATEWAY_*); see .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_SYSTEM = (
    "You are a helpful assistant answering requests from another program. "
    "Answer directly, without asking follow-up questions."
)


def _list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    tokens: list[str] = field(default_factory=list)  # accepted bearer tokens
    allow_no_auth: bool = False  # only for a gateway bound to 127.0.0.1 on a trusted machine
    host: str = "127.0.0.1"
    port: int = 8787
    claude_bin: str = "claude"
    concurrency: int = 4  # `claude -p` processes at once
    timeout: float = 120.0  # seconds per request
    default_model: str = "haiku"
    allowed_models: list[str] = field(default_factory=list)  # empty = any
    max_prompt_chars: int = 200_000
    default_system: str = DEFAULT_SYSTEM
    thinking: bool = False  # extended thinking in the CLI (slower)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        s = cls()
        s.tokens = _list(e.get("GATEWAY_TOKENS", ""))
        s.allow_no_auth = e.get("GATEWAY_ALLOW_NO_AUTH", "") == "1"
        s.host = e.get("GATEWAY_HOST", s.host)
        s.port = int(e.get("GATEWAY_PORT", s.port))
        s.claude_bin = e.get("GATEWAY_CLAUDE_BIN", s.claude_bin)
        s.concurrency = max(1, int(e.get("GATEWAY_CONCURRENCY", s.concurrency)))
        s.timeout = float(e.get("GATEWAY_TIMEOUT", s.timeout))
        s.default_model = e.get("GATEWAY_DEFAULT_MODEL", s.default_model)
        s.allowed_models = _list(e.get("GATEWAY_ALLOWED_MODELS", ""))
        s.max_prompt_chars = int(e.get("GATEWAY_MAX_PROMPT_CHARS", s.max_prompt_chars))
        s.default_system = e.get("GATEWAY_DEFAULT_SYSTEM", s.default_system)
        s.thinking = e.get("GATEWAY_THINKING", "") == "1"
        return s

    def check(self) -> None:
        """Refuse to start an open gateway: it spends the subscription of whoever is logged in."""
        if not self.tokens and not self.allow_no_auth:
            raise ValueError(
                "GATEWAY_TOKENS is empty: set at least one token "
                "(or GATEWAY_ALLOW_NO_AUTH=1 for a local-only gateway)"
            )
        if self.allow_no_auth and self.host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("GATEWAY_ALLOW_NO_AUTH=1 is only allowed with GATEWAY_HOST=127.0.0.1")
