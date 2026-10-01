"""Run one request through the local Claude Code CLI (`claude -p`).

Each request is a fresh, tool-less, unsaved session in an empty temporary directory, so no
project files, CLAUDE.md, MCP servers or shell access are involved: the CLI is used as a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass

from claude_gateway.config import Settings

log = logging.getLogger(__name__)

# Errors the caller cannot fix by retrying with other input.
_AUTH_WORDS = ("not logged in", "/login", "invalid api key", "oauth", "authentication")
_LIMIT_WORDS = ("usage limit", "limit reached", "rate limit", "credit")


class GatewayError(Exception):
    """A request the gateway could not serve; `status` is the HTTP status to answer with."""

    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


@dataclass(slots=True)
class Result:
    text: str
    structured: dict | list | None
    model: str
    duration_ms: int
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None

    def as_dict(self) -> dict:
        return asdict(self)


class Runner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._slots = asyncio.Semaphore(settings.concurrency)

    def resolve_model(self, model: str | None) -> str:
        model = (model or self.settings.default_model).strip()
        allowed = self.settings.allowed_models
        if allowed and model not in allowed:
            raise GatewayError(
                400, "invalid_request", f"model {model!r} is not allowed; use one of {allowed}"
            )
        return model

    async def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        json_schema: dict | None = None,
        time_limit: float | None = None,
    ) -> Result:
        if not prompt.strip():
            raise GatewayError(400, "invalid_request", "prompt is empty")
        if len(prompt) + len(system or "") > self.settings.max_prompt_chars:
            raise GatewayError(413, "invalid_request", "prompt is too long")
        model = self.resolve_model(model)
        args = [
            self.settings.claude_bin, "-p",
            "--output-format", "json",
            "--system-prompt", system or self.settings.default_system,
            "--model", model,
            "--tools", "",
            "--disallowedTools", "mcp__*",
            "--no-session-persistence",
        ]  # fmt: skip
        if json_schema is not None:
            args += ["--json-schema", json.dumps(json_schema)]
        env = dict(os.environ)
        if not self.settings.thinking:
            env["MAX_THINKING_TOKENS"] = "0"
        limit = min(time_limit or self.settings.timeout, self.settings.timeout)
        async with self._slots:
            started = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="claude-gateway-") as cwd:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    )  # fmt: skip
                except OSError as exc:
                    raise GatewayError(
                        503, "unavailable", f"cannot start {args[0]!r}: {exc}"
                    ) from exc
                try:
                    out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), limit)
                except TimeoutError as exc:
                    proc.kill()
                    await proc.wait()
                    raise GatewayError(504, "timeout", f"no answer in {limit:.0f} s") from exc
            elapsed = int((time.monotonic() - started) * 1000)
        result = parse_output(proc.returncode, out, err, model, elapsed)
        log.info("claude %s: %d ms, %s tokens out", model, elapsed, result.output_tokens)
        return result


def parse_output(code: int | None, out: bytes, err: bytes, model: str, elapsed_ms: int) -> Result:
    """The CLI's `--output-format json` object -> Result, or a GatewayError."""
    try:
        data = json.loads(out.decode("utf-8", "replace") or "{}")
    except ValueError:
        data = {}
    text = str(data.get("result") or "")
    if code != 0 or data.get("is_error") or not data:
        detail = (text or err.decode("utf-8", "replace")).strip()[:500] or f"exit code {code}"
        low = detail.lower()
        if any(w in low for w in _AUTH_WORDS):
            raise GatewayError(503, "not_logged_in", f"Claude Code is not signed in: {detail}")
        if any(w in low for w in _LIMIT_WORDS):
            raise GatewayError(429, "usage_limit", detail)
        raise GatewayError(502, "claude_error", detail)
    usage = data.get("usage") or {}
    models = list((data.get("modelUsage") or {}).keys())
    return Result(
        text=text,
        structured=data.get("structured_output"),
        model=models[0] if models else model,
        duration_ms=elapsed_ms,
        cost_usd=data.get("total_cost_usd"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )
