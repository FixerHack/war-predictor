# ruff: noqa: E501
from datetime import UTC, datetime

from tension_index import storage
from tension_index.classifier import classify_rules
from tension_index.explain import explain, reasons
from tension_index.notify import render_change, render_score
from tension_index.pipeline import (
    active_signals,
    classify_pending,
    derive_advisory_signals,
    parse_when,
    score_all,
)
from tension_index.runner import score_alerts
from tension_index.scoring import ScoreResult

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


async def seed(
    db,
    *,
    source="us",
    country="MD",
    level="4",
    text="Do not travel due to armed conflict. The embassy ordered the departure of staff.",
):
    await storage.migrate(db)
    sid = await storage.insert_snapshot(
        db,
        source=source,
        country=country,
        url="u",
        text=text,
        level=level,
        source_updated="2026-01-15T00:00:00Z",
    )
    await db.commit()
    return sid


def test_parse_when_formats():
    assert parse_when("2026-01-15T00:00:00Z").year == 2026
    assert parse_when("Mon, 01 Sep 2026 10:00:00 GMT").month == 9
    assert parse_when("1767225600000").year == 2026  # epoch ms
    assert parse_when("2026-09-01 10:00:00").day == 1
    assert parse_when("garbage") is None and parse_when(None) is None


async def test_advisory_to_signals(settings):
    async with storage.connect(settings.database_path) as db:
        await seed(db)
        await classify_pending(db, settings, None)
        assert await derive_advisory_signals(db) == 2
        signals = await active_signals(db, NOW)
    kinds = {s.kind: s for s in signals}
    assert (
        kinds["advisory_level"].strength == 0.85
        and kinds["advisory_level"].reason == "armed_conflict"
    )
    assert "staff_posture:ordered_departure" in kinds
    # Baseline snapshot: dated by source_updated, not "now" (no fake synchrony).
    assert kinds["advisory_level"].observed_at.month == 1


async def test_superseded_version_is_deactivated(settings):
    async with storage.connect(settings.database_path) as db:
        s1 = await seed(db)
        await classify_pending(db, settings, None)
        await derive_advisory_signals(db)
        s2 = await storage.insert_snapshot(
            db, source="us", country="MD", url="u", text="Exercise normal precautions.", level="1"
        )
        await storage.insert_change(
            db,
            source="us",
            country="MD",
            prev_snapshot=s1,
            new_snapshot=s2,
            diff="LEVEL: 4 -> 1\n+Exercise normal precautions.",
        )
        await db.commit()
        await classify_pending(db, settings, None)
        await derive_advisory_signals(db)
        signals = await active_signals(db, datetime.now(UTC))
    assert [s.kind for s in signals if s.state] == ["advisory_level"]
    assert signals[0].strength == 0.0


async def test_score_all_needs_coverage_then_publishes(settings):
    async with storage.connect(settings.database_path) as db:
        await seed(db)
        await classify_pending(db, settings, None)
        await derive_advisory_signals(db)
        updates = await score_all(db, NOW)
        # No collector has run: only the country with a decisive event gets a score.
        assert [u.country for u in updates if u.result.score is not None] == ["MD"]

        # Only advisories covered: decisive events still publish, the rest waits.
        run = await storage.start_run(db, "us")
        await storage.finish_run(db, run, ok=True, fetched=1, changed=0, failed=0)
        updates = await score_all(db, datetime.now(UTC))
        md = next(u for u in updates if u.country == "MD")
        assert md.result.score >= 7.0 and "low_coverage" in md.result.flags  # departure floor
        assert md.previous == 7.0  # stored by the first run
        assert next(u for u in updates if u.country == "PL").result.score is None

        from tension_index import pipeline

        pipeline.SOURCE_BLOCKS.update(opensky_fake="aviation", gdelt_fake="media")
        try:
            for source in ("opensky_fake", "gdelt_fake"):
                run = await storage.start_run(db, source)
                await storage.finish_run(db, run, ok=True, fetched=1, changed=0, failed=0)
            updates = await score_all(db, datetime.now(UTC))
        finally:
            for key in ("opensky_fake", "gdelt_fake"):
                del pipeline.SOURCE_BLOCKS[key]
    assert next(u for u in updates if u.country == "PL").result.score == 0.0
    md = next(u for u in updates if u.country == "MD")
    assert md.previous is not None and "low_coverage" not in md.result.flags


def test_explain_and_alert_rendering():
    payload = ScoreResult(
        country="MD",
        score=7.4,
        level="red",
        raw=0.5,
        blocks={},
        flags=["synchrony:3", "short_history"],
        floors=["staff_posture:authorized_departure"],
        top=[],
    ).as_dict()
    payload["top"] = [
        {
            "block": "advisories",
            "publisher": "us",
            "kind": "staff_posture:authorized_departure",
            "value": 0.9,
            "note": "Family members may depart.",
        }
    ]
    text = explain(payload, "uk")
    assert (
        "Держдеп США: дозволено виїзд персоналу посольства — «Family members may depart.»" in text
    )
    assert "3 держав(и) посилили позицію" in text and "порогова подія" in text
    assert reasons(payload, "en")[0].startswith("🇺🇸 US State Dept: authorized departure")
    msg = render_score("MD", 5.2, payload)("uk")
    assert "5.2 → <b>7.4</b> (високий)" in msg and "Молдова" in msg and "не прогноз" in msg


def test_change_alert_prefers_summary():
    render = render_change(
        "PL",
        "🇺🇸 State Department",
        "+raw diff",
        {"uk": "Рівень підвищено.", "en": "Level raised."},
        "Reconsider travel.",
    )
    assert "Рівень підвищено." in render("uk") and "raw diff" not in render("uk")
    assert "<pre>+raw diff</pre>" in render_change("PL", "x", "+raw diff", None, "")("en")


def test_score_alerts_threshold():
    from tension_index.pipeline import ScoreUpdate

    def upd(prev, new):
        return ScoreUpdate("PL", prev, ScoreResult("PL", new, "green", 0, {}))

    assert len(score_alerts([upd(None, 5), upd(2.0, 2.9), upd(2.0, 3.0), upd(6, None)])) == 1


async def _change(db, prev, new, country="MD"):
    cid = await storage.insert_change(
        db, source="us", country=country, prev_snapshot=prev, new_snapshot=new, diff="d"
    )
    cls = classify_rules("x")
    cls.change_type = "security_update"
    await storage.save_classification(
        db, ref_type="change", ref_id=cid, country=country, publisher="us", method="rules",
        payload=cls.to_json(),
    )  # fmt: skip
    return cid


async def test_flapping_changes_are_not_events(settings):
    from datetime import timedelta

    from tension_index.pipeline import flapping_changes

    async with storage.connect(settings.database_path) as db:
        a1 = await seed(db, text="Version A.")
        b1 = await seed(db, text="Version B.")
        a2 = await seed(db, text="Version A.")
        flap_1, flap_2 = await _change(db, a1, b1), await _change(db, b1, a2)
        # A real change elsewhere, never undone.
        x1 = await seed(db, country="EE", text="Calm.")
        x2 = await seed(db, country="EE", text="Staff ordered to leave.")
        real = await _change(db, x1, x2, country="EE")
        await db.commit()

        assert await flapping_changes(db, timedelta(days=7)) == {flap_1, flap_2}
        await derive_advisory_signals(db)
        events = [s for s in await active_signals(db, datetime.now(UTC)) if not s.state]
        assert [(s.country, s.kind) for s in events] == [("EE", "advisory_update:security_update")]
        assert real not in await flapping_changes(db, timedelta(days=7))


async def test_claude_summary_becomes_ukrainian_note(settings):
    async with storage.connect(settings.database_path) as db:
        sid = await seed(db, text="Do not travel due to armed conflict.")
        cls = classify_rules("Do not travel due to armed conflict.")
        cls.method, cls.quote = "claude", "Do not travel due to armed conflict."
        cls.summary_uk = "США радять не їхати через збройний конфлікт."
        await storage.save_classification(
            db, ref_type="snapshot", ref_id=sid, country="MD", publisher="us", method="claude",
            payload=cls.to_json(),
        )  # fmt: skip
        await derive_advisory_signals(db)
        [level] = [s for s in await active_signals(db, NOW) if s.kind == "advisory_level"]
    assert level.note_uk == "США радять не їхати через збройний конфлікт."
    payload = {"top": [{"publisher": "us", "kind": "advisory_level", "note": level.note,
                        "note_uk": level.note_uk}]}  # fmt: skip
    assert reasons(payload, "uk")[0].endswith("— США радять не їхати через збройний конфлікт.")
    assert reasons(payload, "en")[0].endswith("«Do not travel due to armed conflict.»")


async def test_volcanic_ash_airspace_closure_is_not_a_security_signal(settings):
    """Italy, September 2026: France reported an airspace sector closed by Etna ash."""
    async with storage.connect(settings.database_path) as db:
        sid = await seed(
            db, source="fr", country="IT", level=None, text="Etna ash closed a sector."
        )
        # ... and a restriction re-read as ash is switched off again (Italy stayed at 5.0).
        for reason, expected in (
            ("natural_disaster", 0),
            ("armed_conflict", 1),
            ("natural_disaster", 0),
        ):
            cls = classify_rules("x")
            cls.airspace, cls.reason, cls.method = "restricted", reason, "claude"
            await storage.save_classification(
                db, ref_type="snapshot", ref_id=sid, country="IT", publisher="fr",
                method="claude", payload=cls.to_json(),
            )  # fmt: skip
            await derive_advisory_signals(db)
            aviation = [s for s in await active_signals(db, NOW) if s.block == "aviation"]
            assert len(aviation) == expected, reason


def test_covid_measures_in_a_conflict_advisory_are_not_security_signals():
    from tension_index.pipeline import advisory_state_signals
    from tension_index.scoring import load_config

    text = (
        "Do not travel to areas near the border due to the Nagorno-Karabakh conflict.\n"
        "Due to COVID-19 the airspace is closed and the embassy has limited consular services."
    )
    cls = classify_rules(text)
    assert cls.airspace == "closed" and cls.measure_reason == "health"
    cls.reason = "armed_conflict"  # the advice as a whole (as the model reads it)
    base = {"country": "AZ", "publisher": "gov_uk", "observed_at": NOW, "reason": cls.reason,
            "state": True, "note": ""}  # fmt: skip
    kinds = [s.kind for s in advisory_state_signals(load_config(), cls, "none", base)]
    assert kinds == ["advisory_level"]


def test_staff_departure_for_an_unspecified_security_reason_counts():
    """Israel, October 2023: "due to the unpredictable security situation" -> unknown."""
    from tension_index.pipeline import advisory_state_signals
    from tension_index.scoring import load_config

    cls = classify_rules("x")
    cls.staff_posture, cls.reason, cls.measure_reason = (
        "authorized_departure",
        "terrorism",
        "unknown",
    )
    base = {"country": "IL", "publisher": "us", "observed_at": NOW, "reason": cls.reason,
            "state": True, "note": ""}  # fmt: skip
    kinds = [s.kind for s in advisory_state_signals(load_config(), cls, "3", base)]
    assert "staff_posture:authorized_departure" in kinds
