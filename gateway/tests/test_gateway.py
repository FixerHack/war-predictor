import json

import httpx
import pytest

from claude_gateway.api import create_app
from claude_gateway.config import Settings
from claude_gateway.runner import GatewayError, Runner

TOKEN = "test-token"


def fake_cli(tmp_path, body: dict | str, code: int = 0, sleep: float = 0) -> str:
    """A stand-in for `claude`: saves its arguments and stdin, prints `body`."""
    out = body if isinstance(body, str) else json.dumps(body)
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/args"\n'
        f'cat > "{tmp_path}/stdin"\n'
        f'echo "$MAX_THINKING_TOKENS" > "{tmp_path}/thinking"\n'
        + (f"sleep {sleep}\n" if sleep else "")
        + f"cat <<'JSON'\n{out}\nJSON\nexit {code}\n"
    )
    script.chmod(0o755)
    return str(script)


OK = {
    "type": "result", "is_error": False, "result": "Hello!", "total_cost_usd": 0.001,
    "usage": {"input_tokens": 12, "output_tokens": 3},
    "modelUsage": {"claude-haiku-4-5-20251001": {}},
}  # fmt: skip


def app_for(tmp_path, body=OK, **kw):
    settings = Settings(tokens=[TOKEN], claude_bin=fake_cli(tmp_path, body, **kw))
    return create_app(settings)


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gw",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )  # fmt: skip


async def test_complete_runs_the_cli_without_tools_or_session(tmp_path):
    async with client(app_for(tmp_path)) as c:
        r = await c.post("/v1/complete", json={"prompt": "Hi", "system": "Be brief."})
    assert r.status_code == 200
    data = r.json()
    assert data["text"] == "Hello!" and data["model"] == "claude-haiku-4-5-20251001"
    assert data["input_tokens"] == 12 and data["cost_usd"] == 0.001
    args = (tmp_path / "args").read_text().splitlines()
    assert args[:3] == ["-p", "--output-format", "json"]
    assert args[args.index("--tools") + 1] == "" and "--no-session-persistence" in args
    assert args[args.index("--system-prompt") + 1] == "Be brief."
    assert args[args.index("--model") + 1] == "haiku"
    assert (tmp_path / "stdin").read_text() == "Hi"
    assert (tmp_path / "thinking").read_text().strip() == "0"


async def test_json_schema_gives_structured_output(tmp_path):
    body = {**OK, "result": "", "structured_output": {"level": 3}}
    schema = {"type": "object", "properties": {"level": {"type": "integer"}}, "required": ["level"]}
    async with client(app_for(tmp_path, body)) as c:
        r = await c.post("/v1/complete", json={"prompt": "Rate it", "json_schema": schema})
    assert r.json()["structured"] == {"level": 3}
    args = (tmp_path / "args").read_text().splitlines()
    assert json.loads(args[args.index("--json-schema") + 1]) == schema


async def test_tokens_are_required(tmp_path):
    app = app_for(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c:
        assert (await c.get("/health")).status_code == 200  # no token needed
        assert (await c.post("/v1/complete", json={"prompt": "x"})).status_code == 401
        wrong = await c.post("/v1/complete", json={"prompt": "x"}, headers={"x-api-key": "nope"})
        assert wrong.status_code == 401
        right = await c.post("/v1/complete", json={"prompt": "x"}, headers={"x-api-key": TOKEN})
        assert right.status_code == 200


def test_an_open_gateway_does_not_start():
    with pytest.raises(ValueError, match="GATEWAY_TOKENS"):
        Settings().check()
    with pytest.raises(ValueError, match="127.0.0.1"):
        Settings(allow_no_auth=True, host="0.0.0.0").check()
    Settings(allow_no_auth=True).check()


async def test_openai_compatible(tmp_path):
    async with client(app_for(tmp_path)) as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "sonnet",
            "messages": [{"role": "system", "content": "Be brief."},
                         {"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
        })  # fmt: skip
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"] == {"role": "assistant", "content": "Hello!"}
    assert data["usage"]["total_tokens"] == 15
    args = (tmp_path / "args").read_text().splitlines()
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--system-prompt") + 1] == "Be brief."


async def test_anthropic_compatible_with_a_conversation(tmp_path):
    async with client(app_for(tmp_path)) as c:
        r = await c.post("/v1/messages", json={
            "model": "haiku", "max_tokens": 100, "system": "Be brief.",
            "messages": [{"role": "user", "content": "Hi"},
                         {"role": "assistant", "content": "Hello"},
                         {"role": "user", "content": "And now?"}],
        })  # fmt: skip
    data = r.json()
    assert data["type"] == "message" and data["content"][0]["text"] == "Hello!"
    prompt = (tmp_path / "stdin").read_text()
    assert "User: Hi" in prompt and "Assistant: Hello" in prompt and "User: And now?" in prompt


async def test_errors_map_to_http_statuses(tmp_path):
    cases = [
        ({"is_error": True, "result": "Not logged in · Please run /login"}, 503, "not_logged_in"),
        ({"is_error": True, "result": "Claude usage limit reached"}, 429, "usage_limit"),
        ({"is_error": True, "result": "something broke"}, 502, "claude_error"),
    ]
    for body, status, kind in cases:
        async with client(app_for(tmp_path, body, code=1)) as c:
            r = await c.post("/v1/complete", json={"prompt": "x"})
        assert (r.status_code, r.json()["error"]["type"]) == (status, kind)
    async with client(app_for(tmp_path)) as c:
        assert (
            await c.post("/v1/chat/completions", json={"messages": [], "stream": True})
        ).status_code == 400
        assert (await c.post("/v1/complete", json={"prompt": "  "})).status_code == 400


async def test_timeout_and_model_allow_list(tmp_path):
    runner = Runner(
        Settings(tokens=[TOKEN], timeout=0.5, claude_bin=fake_cli(tmp_path, OK, sleep=2))
    )
    with pytest.raises(GatewayError) as err:
        await runner.run("x")
    assert err.value.status == 504
    strict = Runner(Settings(tokens=[TOKEN], allowed_models=["haiku"]))
    with pytest.raises(GatewayError, match="not allowed"):
        strict.resolve_model("opus")


async def test_mcp_over_http(tmp_path):
    app = app_for(tmp_path)
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    async with app.router.lifespan_context(app), client(app) as c:
        init = await c.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}},
        })  # fmt: skip
        assert init.status_code == 200, init.text
        tools = await c.post("/mcp", headers=headers,
                             json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})  # fmt: skip
        assert [t["name"] for t in tools.json()["result"]["tools"]] == ["ask_claude"]
        call = await c.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "ask_claude", "arguments": {"prompt": "Hi"}},
        })  # fmt: skip
    assert "Hello!" in json.dumps(call.json()["result"])
