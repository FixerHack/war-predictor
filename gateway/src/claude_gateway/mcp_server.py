"""MCP server: one tool, `ask_claude`, for any MCP client (Claude Desktop, IDEs, agents)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from claude_gateway.runner import GatewayError, Runner


def build_mcp(runner: Runner) -> MCPServer:
    mcp = MCPServer(
        name="claude-gateway",
        instructions=(
            "Ask a Claude model (through Claude Code on the gateway's machine) to answer a prompt. "
            "Pass json_schema to get a JSON object that matches it."
        ),
    )

    @mcp.tool()
    async def ask_claude(
        prompt: str,
        system: str = "",
        model: str = "",
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Answer `prompt` with a Claude model. `system` replaces the default instructions,
        `model` is an alias such as haiku, sonnet or opus (empty = the gateway default),
        `json_schema` makes the answer a JSON object in `structured`."""
        try:
            result = await runner.run(
                prompt, system=system or None, model=model or None, json_schema=json_schema
            )
        except GatewayError as exc:
            return {"error": exc.kind, "message": exc.message}
        return result.as_dict()

    return mcp
