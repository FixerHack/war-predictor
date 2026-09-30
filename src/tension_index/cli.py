"""Command-line entry point: `uv run tension-index <command>`."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from html import escape
from pathlib import Path

import httpx

from tension_index import __version__, storage
from tension_index.config import get_settings
from tension_index.logging_setup import setup_logging

log = logging.getLogger("tension_index")


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


async def _init_db() -> int:
    settings = get_settings()
    async with storage.connect(settings.database_path) as db:
        version = await storage.migrate(db)
    print(f"Database ready: {settings.database_path} (schema v{version})")
    return 0


async def _collect(args: argparse.Namespace) -> int:
    from tension_index.collector import collect_all
    from tension_index.notify import broadcast_change, send
    from tension_index.sources import REGISTRY

    settings = get_settings()
    results = await collect_all(settings, sources=args.sources, countries=args.countries)
    for r in results:
        label = REGISTRY[r.source].label if r.source in REGISTRY else r.source
        for country, diff in r.changes:
            if args.notify:
                await send(
                    settings,
                    f"🔔 <b>{country}</b> · {escape(label)}: advisory changed\n"
                    f"<pre>{escape(diff[:3000])}</pre>",
                )
                await broadcast_change(settings, country, label, diff)
        if not r.ok and args.notify:
            await send(
                settings,
                f"❌ Collector <b>{escape(r.source)}</b> failed "
                f"({r.failed} errors)\n<pre>{escape(chr(10).join(r.errors[:5]))}</pre>",
            )
    return 0 if all(r.ok for r in results) else 2


async def _health(args: argparse.Namespace) -> int:
    from tension_index.health import Status, run_checks
    from tension_index.notify import send

    settings = get_settings()
    report = await run_checks(settings)
    print(
        json.dumps(report.as_dict(), indent=2, ensure_ascii=False)
        if args.json
        else report.as_text()
    )
    if report.status == Status.FAIL and args.notify:
        await send(settings, f"<b>Healthcheck FAIL</b>\n<pre>{escape(report.as_text())}</pre>")
    if report.status != Status.FAIL and settings.health_ping_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(settings.health_ping_url)
        except httpx.HTTPError as exc:
            log.warning("Dead-man ping failed: %s", exc)
    return int(report.status)


async def _war_check(args: argparse.Namespace) -> int:
    from tension_index import war_status
    from tension_index.collector import make_client
    from tension_index.notify import send

    settings = get_settings()
    try:
        async with make_client(settings) as client:
            html = await war_status.fetch_wikipedia(client)
        if args.headings:
            for h in war_status.headings(html):
                print(f"{'  ' * (h.level - 2)}h{h.level} [{h.severity or '-'}] {h.text}")
            return 0
        if args.explain:
            wanted = {c.upper() for c in args.explain}
            curated = war_status.load()
            for m in war_status.mentions(html):
                if m.country in wanted:
                    reason = curated[m.country].ignore_reason(m.conflict)
                    suffix = f"  (ignored: {reason})" if reason else ""
                    print(f"{m.country} [{m.severity}] {m.conflict or '?'}{suffix}")
                    print(f"    {m.column}: {m.cell[:300]}")
            return 0
        detected = war_status.parse_wikipedia(html, war_status.load())
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        print(f"war-check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        if args.notify:
            await send(settings, f"❌ war-check failed: {escape(str(exc))}")
        return 2
    diff = war_status.mismatches(war_status.load(), detected)
    mentioned = ", ".join(f"{code}={sev}" for code, sev in sorted(detected.items())) or "none"
    print(f"Monitored countries mentioned on Wikipedia: {mentioned}")
    print("\n".join(diff) or "No mismatches with Wikipedia")
    if diff and args.notify:
        await send(
            settings,
            "⚠️ <b>War status: review config/conflicts.yaml</b>\n<pre>"
            + escape("\n".join(diff))
            + "</pre>",
        )
    return 1 if diff else 0


async def _bot() -> int:
    from tension_index.bot.app import run_bot

    await run_bot(get_settings())
    return 0


def _roadmap(args: argparse.Namespace) -> int:
    from tension_index.roadmap import build

    build(Path(args.source), Path(args.out), plan_dir=Path(args.plan_dir))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tension-index", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create/migrate the SQLite database")

    p = sub.add_parser("collect", help="fetch advisories and record changes")
    p.add_argument("--sources", type=_csv, help="comma-separated source names (default: all)")
    p.add_argument("--countries", type=_csv, help="comma-separated ISO codes (default: all)")
    p.add_argument("--notify", action="store_true", help="send changes/failures to Telegram")

    p = sub.add_parser("health", help="run health checks (exit 0 OK, 1 WARN, 2 FAIL)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--notify", action="store_true", help="alert Telegram on FAIL")

    sub.add_parser("bot", help="run the Telegram bot (long polling)")

    p = sub.add_parser("war-check", help="compare config/conflicts.yaml with Wikipedia")
    p.add_argument("--notify", action="store_true", help="alert Telegram on mismatches")
    p.add_argument(
        "--headings", action="store_true", help="print page headings and parsed severity, then exit"
    )
    p.add_argument(
        "--explain", type=_csv, metavar="CODES", help="show where countries (e.g. FR,PL) are found"
    )

    p = sub.add_parser("roadmap", help="render PLAN.md + progress site from roadmap.yaml")
    p.add_argument("--source", default="roadmap/roadmap.yaml")
    p.add_argument("--out", default="_site")
    p.add_argument("--plan-dir", default=".")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "roadmap":
        sys.exit(_roadmap(args))
    setup_logging(get_settings().log_level)
    handlers = {
        "init-db": lambda: _init_db(),
        "collect": lambda: _collect(args),
        "health": lambda: _health(args),
        "bot": lambda: _bot(),
        "war-check": lambda: _war_check(args),
    }
    try:
        sys.exit(asyncio.run(handlers[args.command]()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
