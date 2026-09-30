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
        for country, diff, _ in r.changes:
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


async def _run(args: argparse.Namespace) -> int:
    from tension_index.runner import run_cycle, score_alerts

    report = await run_cycle(get_settings(), notify=args.notify)
    for r in report.results:
        print(f"{r.source}: fetched={r.fetched} changed={r.changed} failed={r.failed} ok={r.ok}")
    print(f"classified: {report.classified}")
    scored = [u for u in report.updates if u.result.score is not None]
    print(f"scores: {len(scored)}/{len(report.updates)} published", end="")
    if len(scored) < len(report.updates):
        print(" (the rest: not enough fresh data yet)", end="")
    print(f"; alerts: {len(score_alerts(report.updates))}")
    for u in sorted(scored, key=lambda u: -(u.result.score or 0))[:10]:
        print(f"  {u.country} {u.result.score:>4} {u.result.level} {' '.join(u.result.flags)}")
    return 0 if report.ok else 2


async def _export(args: argparse.Namespace) -> int:
    from tension_index.export import build, write

    settings = get_settings()
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        data = await build(db)
    write(data, Path(args.out))
    published = sum(1 for c in data["countries"].values() if c["score"] is not None)
    print(f"exported {published}/{len(data['countries'])} published scores -> {args.out}")
    return 0


async def _digest() -> int:
    from tension_index.digest import send_digests

    print(f"digests sent: {await send_digests(get_settings())}")
    return 0


async def _classify() -> int:
    from tension_index.pipeline import classify_pending, make_classifier

    settings = get_settings()
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        claude = make_classifier(settings)
        if claude is None:
            print("ANTHROPIC_API_KEY not set: keyword rules only")
        stats = await classify_pending(db, settings, claude)
    print(
        f"classified changes={stats['changes']} snapshots={stats['snapshots']} "
        f"(claude={stats['claude']})"
    )
    return 0


def _history_db(args: argparse.Namespace) -> Path:
    return Path(args.db)


async def _history(args: argparse.Namespace) -> int:
    from tension_index.collector import make_client
    from tension_index.history import load_episode, load_episodes

    episodes = load_episodes()
    ids = list(episodes) if args.episode == "all" else [args.episode]
    async with make_client(get_settings()) as client, storage.connect(_history_db(args)) as db:
        for eid in ids:
            stats = await load_episode(db, client, episodes[eid])
            print(f"{eid}: versions stored per publisher {stats}")
    return 0


async def _backtest(args: argparse.Namespace) -> int:
    from tension_index.backtest import classify_history, replay
    from tension_index.history import load_episodes
    from tension_index.pipeline import make_classifier

    settings = get_settings()
    episodes = load_episodes()
    ids = list(episodes) if args.episode == "all" else [args.episode]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - one-off CLI setup
    failed = 0
    async with storage.connect(_history_db(args)) as db:
        await storage.migrate(db)
        claude = make_classifier(settings) if args.claude else None
        await classify_history(db, claude)
        for eid in ids:
            report = await replay(db, episodes[eid])
            (out / f"{eid}.md").write_text(report.markdown(), encoding="utf-8")
            (out / f"{eid}.csv").write_text(report.csv(), encoding="utf-8")
            ok, detail = report.verdict()
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'} {eid}: {detail} -> {out / (eid + '.md')}")
    return 1 if failed else 0


async def _probe_news() -> int:
    from tension_index.collector import make_client
    from tension_index.extra.news import load_config, parse_feed

    bad = 0
    async with make_client(get_settings()) as client:
        for feed in load_config()["feeds"]:
            try:
                response = await client.get(feed["url"])
                items = parse_feed(response.content) if response.is_success else []
                detail = f"HTTP {response.status_code} items={len(items)}"
            except Exception as exc:  # report every feed, whatever breaks
                items, detail = [], f"{type(exc).__name__}: {str(exc)[:80]}"
            bad += not items
            print(f"{'OK ' if items else 'BAD'} {feed['name']:<18} {detail}")
            if items:
                print(f"    e.g. {items[0][0][:90]}")
    return 2 if bad else 0


async def _probe(args: argparse.Namespace) -> int:
    """Show what a source really returns, to fix a parser after an API/layout change."""
    from tension_index.collector import make_client
    from tension_index.countries import get_country
    from tension_index.extra import PROBE_URLS
    from tension_index.sources import REGISTRY

    if args.source == "news":
        return await _probe_news()
    if args.source in PROBE_URLS:
        async with make_client(get_settings()) as client:
            response = await client.get(PROBE_URLS[args.source])
            print(f"HTTP {response.status_code} {response.url} ({len(response.text)} bytes)")
            print(response.text[: args.bytes])
        return 0 if response.is_success else 2
    if args.source not in REGISTRY:
        known = ", ".join([*REGISTRY, *PROBE_URLS])
        print(f"unknown source {args.source!r}; known: {known}", file=sys.stderr)
        return 2
    async with make_client(get_settings()) as client:
        source = REGISTRY[args.source](client)
        status = 0
        try:
            await source.prepare()
            advisory = await source.fetch(get_country(args.country))
            print(f"OK level={advisory.level!r} title={advisory.title!r} url={advisory.url}")
            print(f"text ({len(advisory.text)} chars):\n{advisory.text[:800]}\n")
        except Exception as exc:
            print(f"FAILED: {type(exc).__name__}: {exc}\n")
            status = 2
        for url, body in source.raw.items():
            print(f"--- raw {url} ({len(body)} bytes)\n{body[: args.bytes]}\n")
    return status


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

    sub.add_parser("classify", help="classify new changes and current advisories")
    sub.add_parser("digest", help="send the daily summary to users with the digest on")

    p = sub.add_parser("export", help="write the public dashboard data (scores.json)")
    p.add_argument("--out", default="_site/dashboard/scores.json")

    p = sub.add_parser("history", help="load archived advisories (Wayback) for an episode")
    p.add_argument("--episode", default="all", help="id from config/episodes.yaml or 'all'")
    p.add_argument("--db", default="data/history.sqlite3")

    p = sub.add_parser("backtest", help="replay the scale on archived episodes")
    p.add_argument("--episode", default="all")
    p.add_argument("--db", default="data/history.sqlite3")
    p.add_argument("--out", default="reports/backtest")
    p.add_argument("--claude", action="store_true", help="classify with Claude (API key)")

    p = sub.add_parser("run", help="full cycle: collect, classify, score, notify")
    p.add_argument("--notify", action="store_true", help="send alerts to Telegram")

    p = sub.add_parser("probe", help="show a source's raw response and parsed result")
    p.add_argument("source")
    p.add_argument("--country", default="PL")
    p.add_argument("--bytes", type=int, default=3000, help="raw bytes to print per response")

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
        "probe": lambda: _probe(args),
        "classify": lambda: _classify(),
        "run": lambda: _run(args),
        "digest": lambda: _digest(),
        "export": lambda: _export(args),
        "history": lambda: _history(args),
        "backtest": lambda: _backtest(args),
    }
    try:
        sys.exit(asyncio.run(handlers[args.command]()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
