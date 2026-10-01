# ruff: noqa: E501
import json
from datetime import UTC, datetime, timedelta

from tension_index import storage
from tension_index.explain import KINDS
from tension_index.export import build, write
from tension_index.extra.news import load_config as feeds_config


async def test_export_shape(settings, tmp_path):
    now = datetime.now(UTC)
    payload = {"raw": 0.5, "flags": ["isolated"], "floors": [],
               "top": [{"block": "aviation", "publisher": "easa", "kind": "aviation:czib", "value": 0.8, "note": "CZIB"}]}  # fmt: skip
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        for days, score in ((100, 1.0), (3, 2.0), (0, 5.2)):
            await db.execute(
                "INSERT INTO scores (country, computed_at, score, level, payload) VALUES ('MD', ?, ?, 'orange', ?)",
                ((now - timedelta(days=days)).isoformat(), score, json.dumps(payload)),
            )
        await db.commit()
        data = await build(db, now)
    md = data["countries"]["MD"]
    assert md["score"] == 5.2 and md["level"] == "orange" and md["war"]["status"] == "frozen"
    assert len(md["history"]) == 2  # older than 90 days is dropped
    assert md["reasons"]["uk"] == ["✈️ EASA: бюлетень EASA щодо зони конфлікту — «CZIB»"]
    assert md["flags"]["en"][0].startswith("rise in this country only")
    assert data["countries"]["PL"]["score"] is None and data["countries"]["PL"]["history"] == []
    contributor = md["contributors"][0]
    assert (
        contributor["kind"]["en"] == "EASA conflict zone bulletin" and contributor["value"] == 0.8
    )
    assert md["raw"] == 0.5 and md["flag_keys"] == ["isolated"] and md["signals"] == []
    out = tmp_path / "d" / "scores.json"
    write(data, out)
    assert json.loads(out.read_text())["countries"]["MD"]["name"]["uk"] == "Молдова"


def test_every_signal_kind_has_a_label():
    kinds = {c["kind"] for c in feeds_config()["categories"].values()}
    kinds |= {
        "aviation:czib",
        "aviation:traffic_drop",
        "media:gdelt_surge",
        "markets:spread_jump",
        "markets:fx_drop",
    }
    assert kinds <= set(KINDS)


async def test_export_has_context_neighbours(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        data = await build(db)
    ua = data["context"]["UA"]
    assert ua["status"] == "war" and ua["role"] == "at_war" and ua["name"]["uk"] == "Україна"
    assert data["context"]["BY"]["role"] == "aggressor_ally" and "UA" not in data["countries"]
