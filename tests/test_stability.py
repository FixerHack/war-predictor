import json
from datetime import UTC, datetime, timedelta

import httpx

from tension_index import storage
from tension_index.collector import RunResult
from tension_index.extra import stability

NOW = datetime.now(UTC)


def _rss(*titles: str) -> bytes:
    items = "".join(
        f"<item><title>{t}</title><link>https://x/{i}</link><pubDate>"
        f"{NOW.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
        for i, t in enumerate(titles)
    )
    return f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'.encode()


class FakeClaude:
    """Labels like Claude would: by index, with translated titles for non-none items."""

    available = True
    stopped = ""

    def __init__(self, labels: dict[int, tuple[str, float]]):
        self.labels, self.prompts = labels, []

    async def _call(self, system, user, schema, max_tokens):
        self.prompts.append((system, user))
        items = [
            {"i": i, "category": cat, "severity": sev, "title_uk": f"uk {i}", "title_en": f"en {i}"}
            for i, (cat, sev) in self.labels.items()
        ]
        return json.dumps({"items": items}), ""


def test_every_monitored_country_has_a_national_feed():
    from tension_index.countries import COUNTRIES

    feeds = stability.load_feeds()
    assert set(feeds) == set(COUNTRIES)
    assert all(
        f["tier"] in (2, 3) and f["url"].startswith("https://") for fs in feeds.values() for f in fs
    )


async def test_headlines_labelled_scored_and_turned_into_signals(settings):
    rss = _rss(
        "Rząd blokuje sankcje wobec Rosji",  # 0: pro-aggressor decision
        "Szef sztabu generalnego odwołany",  # 1: security purge
        "Mecz Polska - Holandia",  # 2: none
    )
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=rss))
    claude = FakeClaude(
        {0: ("pro_aggressor_policy", 1.0), 1: ("security_purge", 0.5), 2: ("none", 0.0)}
    )
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        result = RunResult(source="national")
        async with httpx.AsyncClient(transport=transport) as client:
            await stability.fetch_headlines(db, client, ["PL"], result)
        assert result.fetched == 1 and result.changed == 3
        assert await stability.label_headlines(db, claude, ["PL"]) == 3
        assert "Poland" in claude.prompts[0][0] and "0. Rząd blokuje" in claude.prompts[0][1]

        scored = await stability.stability_score(db, "PL", NOW)
        cats = [e["category"] for e in scored["events"]]
        assert sorted(cats) == ["pro_aggressor_policy", "security_purge"]
        # rmf24 is a private outlet (tier 3) and alone: half weight until a second one confirms.
        assert all(not e["confirmed"] for e in scored["events"])
        assert 0 < scored["score"] < 10

        await stability.derive_signals(db, ["PL"], NOW)
        async with db.execute(
            "SELECT kind, tier, confirmed, note_uk FROM signals WHERE publisher = 'national'"
        ) as cur:
            rows = {r["kind"]: dict(r) for r in await cur.fetchall()}
        assert set(rows) == {"domestic:pro_aggressor_policy", "domestic:security_purge"}
        assert (
            rows["domestic:pro_aggressor_policy"]["tier"] == 3
            and rows["domestic:pro_aggressor_policy"]["note_uk"] == "uk 0"
        )


async def test_a_public_broadcaster_counts_alone_and_a_second_outlet_confirms(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        rows = [
            ("https://a/1", "PL", "tvp", 2, "A", NOW.isoformat(), "armed_unmarked", 0.8),
            ("https://b/1", "HU", "telex", 3, "B", NOW.isoformat(), "pro_aggressor_policy", 1.0),
            (
                "https://b/2",
                "HU",
                "hvg",
                3,
                "C",
                (NOW - timedelta(days=1)).isoformat(),
                "pro_aggressor_policy",
                0.5,
            ),
        ]
        for url, country, feed, tier, title, published, category, severity in rows:
            await db.execute(
                "INSERT INTO national_items (url, country, feed, tier, title, published, seen_at, "
                "classified, category, severity) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (url, country, feed, tier, title, published, published, category, severity),
            )
        await db.commit()
        pl = await stability.stability_score(db, "PL", NOW)
        hu = await stability.stability_score(db, "HU", NOW)
    assert pl["events"][0]["confirmed"] and all(e["confirmed"] for e in hu["events"])
    assert pl["score"] > 0 and hu["score"] > 0


async def test_no_claude_means_nothing_is_labelled(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        assert await stability.label_headlines(db, None, ["PL"]) == 0
        assert (await stability.stability_score(db, "PL", NOW)) == {"score": 0.0, "events": []}


async def test_one_event_in_several_headlines_counts_once(settings):
    async def score(n: int) -> float:
        async with storage.connect(settings.database_path) as db:
            await storage.migrate(db)
            await db.execute("DELETE FROM national_items")
            for i in range(n):
                await db.execute(
                    "INSERT INTO national_items (url, country, feed, tier, title, published, seen_at, "
                    "classified, category, severity) VALUES (?, 'HU', 'telex', 2, 't', ?, ?, 1, "
                    "'security_purge', 1.0)",
                    (f"https://x/{i}", NOW.isoformat(), NOW.isoformat()),
                )
            await db.commit()
            return (await stability.stability_score(db, "HU", NOW))["score"]

    assert await score(3) == await score(1) > 0
