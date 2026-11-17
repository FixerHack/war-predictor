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


async def test_export_time_is_the_latest_score(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await storage.insert_score(db, "PL", 1.0, "green", json.dumps({"raw": 0.1}))
        async with db.execute("SELECT MAX(computed_at) FROM scores") as cur:
            computed = (await cur.fetchone())[0]
        later = datetime.now(UTC) + timedelta(hours=3)
        assert (await build(db, now=later))["generated_at"] == computed


def test_reasons_are_cut_at_a_word_boundary():
    from tension_index.explain import shorten

    text = "Франція рекомендує посилену обережність на кордонах Польщі " * 5
    short = shorten(text)
    assert len(short) <= 160 and short.endswith("…") and not short.endswith(" …")
    assert short[:-1] == text[: len(short) - 1]  # nothing invented, only cut
    assert shorten("short") == "short"


async def test_chronicle_lists_advice_signals_and_score_moves(settings, tmp_path):
    from tension_index.classifier import Classification
    from tension_index.export import chronicle, chronicles, write_chronicles
    from tension_index.scoring import Signal

    now = datetime.now(UTC)
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        s1 = await storage.insert_snapshot(db, source="gov_uk", country="PL", url="u", text="A")
        s2 = await storage.insert_snapshot(db, source="gov_uk", country="PL", url="u", text="B")
        cid = await storage.insert_change(db, source="gov_uk", country="PL", prev_snapshot=s1,
                                          new_snapshot=s2, diff="+B")  # fmt: skip
        cls = Classification(reason="terrorism", change_type="security_update", method="claude",
                             summary_uk="Теракт у Кракові.", summary_en="Attack in Kraków.")  # fmt: skip
        await storage.save_classification(db, ref_type="change", ref_id=cid, country="PL",
                                          publisher="gov_uk", method="claude", payload=cls.to_json())  # fmt: skip
        quiet = await storage.insert_change(db, source="gov_uk", country="PL", prev_snapshot=s2,
                                            new_snapshot=s1, diff="+A")  # fmt: skip
        await storage.save_classification(db, ref_type="change", ref_id=quiet, country="PL",
            publisher="gov_uk", method="claude",
            payload=Classification(change_type="editorial", method="claude").to_json())  # fmt: skip
        await storage.upsert_signal(db, Signal(country="PL", block="aggressor",
            kind="aggressor:mfa_advisory", strength=0.8, publisher="ru_media", observed_at=now,
            tier=2, confirmed=True, reason="military_threat", note="МИД рекомендует воздержаться"),
            "ru_media-mfa:x")  # fmt: skip
        await db.execute(
            "INSERT INTO scores (country, computed_at, score, level, payload) VALUES "
            "('PL', ?, 0.0, 'green', '{}'), ('PL', ?, 5.5, 'orange', '{}')",
            ((now - timedelta(days=1)).isoformat(), now.isoformat()),
        )
        await db.commit()
        events = await chronicle(db, "PL", now + timedelta(minutes=1))
        assert write_chronicles(await chronicles(db), tmp_path / "chronicle") == 38
    types = [e["type"] for e in events]
    assert sorted(types) == ["advice", "score", "signal"]  # the editorial change is left out
    advice = next(e for e in events if e["type"] == "advice")
    assert (
        advice["text"]["uk"] == "Теракт у Кракові." and advice["counted"] is False
    )  # no signal yet
    assert next(e for e in events if e["type"] == "score")["to"] == 5.5
    assert json.loads((tmp_path / "chronicle" / "PL.json").read_text())["country"] == "PL"
