"""claude-gateway serve | mcp | check."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from claude_gateway.config import Settings
from claude_gateway.runner import GatewayError, Runner


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="claude-gateway", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="HTTP API + MCP over HTTP")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    sub.add_parser("mcp", help="MCP over stdio (for a local MCP client)")
    check = sub.add_parser("check", help="send one prompt through the CLI and print the result")
    check.add_argument("prompt", nargs="?", default="Reply with the word OK.")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    settings = Settings.from_env()

    if args.command == "serve":
        import uvicorn

        from claude_gateway.api import create_app

        settings.host = args.host or settings.host
        settings.port = args.port or settings.port
        try:
            app = create_app(settings)
        except ValueError as exc:
            sys.exit(f"claude-gateway: {exc}")
        uvicorn.run(app, host=settings.host, port=settings.port)
    elif args.command == "mcp":
        from claude_gateway.mcp_server import build_mcp

        asyncio.run(build_mcp(Runner(settings)).run_stdio_async())
    else:
        try:
            result = asyncio.run(Runner(settings).run(args.prompt))
        except GatewayError as exc:
            sys.exit(f"{exc.kind}: {exc.message}")
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
