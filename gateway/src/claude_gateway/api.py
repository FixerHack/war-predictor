"""HTTP API.

- POST /v1/complete          our own simple format (prompt, system, model, json_schema)
- POST /v1/chat/completions  OpenAI-compatible (non-streaming), for existing OpenAI clients
- POST /v1/messages          Anthropic-compatible (non-streaming), for existing Anthropic clients
- /mcp                       MCP over streamable HTTP (tool `ask_claude`)
- GET  /health               no auth; whether the CLI is installed

Every route except /health needs `Authorization: Bearer <token>` (or `x-api-key: <token>`).
"""

from __future__ import annotations

import contextlib
import hmac
import json
import shutil
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from claude_gateway import __version__
from claude_gateway.config import Settings
from claude_gateway.mcp_server import build_mcp
from claude_gateway.runner import GatewayError, Result, Runner


class CompleteRequest(BaseModel):
    prompt: str
    system: str | None = None
    model: str | None = None
    json_schema: dict[str, Any] | None = None
    timeout: float | None = Field(default=None, gt=0)


def _text(content: Any) -> str:
    """Message content as plain text: a string, or a list of text parts (both APIs)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, dict):
                raise GatewayError(
                    400, "invalid_request", f"unsupported content part {part.get('type')!r}"
                )
        return "\n".join(parts)
    return str(content or "")


def _transcript(messages: list[dict]) -> str:
    """Several turns -> one prompt; a single user turn is passed as is."""
    turns = [(m.get("role", "user"), _text(m.get("content"))) for m in messages]
    if len(turns) == 1 and turns[0][0] == "user":
        return turns[0][1]
    lines = [f"{role.capitalize()}: {text}" for role, text in turns]
    return "Conversation so far:\n\n" + "\n\n".join(lines) + "\n\nAnswer as the assistant."


def _schema_from_openai(body: dict) -> dict | None:
    fmt = body.get("response_format") or {}
    if fmt.get("type") == "json_schema":
        return (fmt.get("json_schema") or {}).get("schema")
    return None


def _answer_text(result: Result) -> str:
    return (
        json.dumps(result.structured, ensure_ascii=False)
        if result.structured is not None
        else result.text
    )


def create_app(settings: Settings | None = None, runner: Runner | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.check()
    runner = runner or Runner(settings)
    mcp = build_mcp(runner)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        # Access is controlled by the token below; the gateway may sit behind any host name.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="claude-gateway", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if request.url.path == "/health" or settings.allow_no_auth:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        token = token or request.headers.get("x-api-key", "").strip()
        if not any(hmac.compare_digest(token, t) for t in settings.tokens):
            return JSONResponse(
                {"error": {"type": "unauthorized", "message": "missing or wrong token"}}, 401
            )
        return await call_next(request)

    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, exc: GatewayError):
        return JSONResponse({"error": {"type": exc.kind, "message": exc.message}}, exc.status)

    @app.get("/health")
    async def health():
        return {"ok": shutil.which(settings.claude_bin) is not None, "version": __version__}

    @app.post("/v1/complete")
    async def complete(req: CompleteRequest):
        result = await runner.run(req.prompt, system=req.system, model=req.model,
                                  json_schema=req.json_schema, time_limit=req.timeout)  # fmt: skip
        return result.as_dict()

    @app.post("/v1/chat/completions")
    async def openai_chat(request: Request):
        body = await request.json()
        if body.get("stream"):
            raise GatewayError(400, "invalid_request", "streaming is not supported")
        messages = body.get("messages") or []
        system = "\n\n".join(
            _text(m.get("content")) for m in messages if m.get("role") in ("system", "developer")
        )
        turns = [m for m in messages if m.get("role") not in ("system", "developer")]
        if not turns:
            raise GatewayError(400, "invalid_request", "messages has no user turn")
        result = await runner.run(_transcript(turns), system=system or None, model=body.get("model"),
                                  json_schema=_schema_from_openai(body))  # fmt: skip
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": result.model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": _answer_text(result)}}],
            "usage": {"prompt_tokens": result.input_tokens or 0,
                      "completion_tokens": result.output_tokens or 0,
                      "total_tokens": (result.input_tokens or 0) + (result.output_tokens or 0)},
        }  # fmt: skip

    @app.post("/v1/messages")
    async def anthropic_messages(request: Request):
        body = await request.json()
        if body.get("stream"):
            raise GatewayError(400, "invalid_request", "streaming is not supported")
        system = _text(body.get("system")) if body.get("system") else None
        schema = ((body.get("output_config") or {}).get("format") or {}).get("schema")
        result = await runner.run(_transcript(body.get("messages") or []), system=system,
                                  model=body.get("model"), json_schema=schema)  # fmt: skip
        return {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "model": result.model,
            "content": [{"type": "text", "text": _answer_text(result)}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": result.input_tokens or 0,
                      "output_tokens": result.output_tokens or 0},
        }  # fmt: skip

    app.mount("/", mcp_app)  # serves /mcp; the routes above take precedence
    return app
