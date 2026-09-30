# ruff: noqa: E501
import json
from types import SimpleNamespace

import pytest

from tension_index import storage
from tension_index.classifier import Classification, ClaudeClassifier, classify_rules
from tension_index.pipeline import classify_pending


def test_rules_staff_posture_and_reason():
    diff = (
        "@@ -1,2 +1,2 @@\n Keep informed.\n"
        "-Exercise increased caution.\n"
        "+On 23 January the Department ordered the departure of eligible family members "
        "due to the continued threat of Russian military action.\n"
    )
    c = classify_rules(diff, level_change=(0.2, 0.85))
    assert c.staff_posture == "ordered_departure"
    assert c.reason == "armed_conflict"
    assert c.change_type == "level_raised"
    assert c.quote.startswith("On 23 January")


def test_rules_ignore_removed_lines_and_detect_editorial():
    diff = "@@ -1 +1 @@\n-Embassy suspended operations due to armed conflict.\n+Phone: +48 22 000"
    c = classify_rules(diff)
    assert c.staff_posture == "unknown" and c.reason == "unknown"
    assert c.change_type == "editorial"


def test_rules_airspace_borders_terrorism():
    text = "Terrorists are likely to try to carry out attacks. The airspace is closed. Borders are closed."
    c = classify_rules(text)
    assert c.reason == "terrorism" and c.airspace == "closed" and c.borders_closed


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(payload: dict | None, stop_reason: str = "end_turn"):
    content = [SimpleNamespace(type="text", text=json.dumps(payload))] if payload else []
    messages = FakeMessages(SimpleNamespace(stop_reason=stop_reason, content=content))
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


PAYLOAD = {
    "reason": "military_threat", "change_type": "security_update", "level": "",
    "staff_posture": "authorized_departure", "airspace": "unknown", "borders_closed": False,
    "quote": "Family members may depart.", "summary_uk": "Дозволено виїзд родин.",
    "summary_en": "Family members may depart.",
}  # fmt: skip


async def test_claude_request_shape_and_merge(settings):
    client, messages = fake_client(PAYLOAD)
    claude = ClaudeClassifier(settings, client=client)
    fallback = Classification(change_type="level_raised")
    result = await claude.classify(
        publisher="us",
        country="PL",
        text="+x",
        level_before="2",
        level_after="3",
        fallback=fallback,
    )
    assert result.method == "claude" and result.staff_posture == "authorized_departure"
    assert result.change_type == "level_raised"  # structured direction kept
    call = messages.calls[0]
    assert call["model"] == settings.classifier_model
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["fallbacks"] == "default"


async def test_claude_refusal_and_cap_fall_back(settings):
    client, _ = fake_client(None, stop_reason="refusal")
    claude = ClaudeClassifier(settings, client=client)
    out = await claude.classify(
        publisher="us",
        country="PL",
        text="+x",
        level_before=None,
        level_after=None,
        fallback=Classification(reason="crime"),
    )
    assert out.method == "rules" and out.reason == "crime" and "refusal" in out.notes[0]
    claude.calls = settings.classifier_max_calls
    capped = await claude.classify(
        publisher="us",
        country="PL",
        text="+x",
        level_before=None,
        level_after=None,
        fallback=Classification(),
    )
    assert "cap" in capped.notes[0]


@pytest.mark.parametrize(
    "model,has_fallbacks", [("claude-haiku-4-5", False), ("claude-opus-5-5", True)]
)
async def test_fallbacks_only_for_supported_models(settings, model, has_fallbacks):
    settings.classifier_model = model
    client, messages = fake_client(PAYLOAD)
    await ClaudeClassifier(settings, client=client).classify(
        publisher="us",
        country="PL",
        text="+x",
        level_before=None,
        level_after=None,
        fallback=Classification(),
    )
    assert ("fallbacks" in messages.calls[0]) is has_fallbacks


async def test_classify_pending_rules_only(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        s1 = await storage.insert_snapshot(
            db, source="us", country="MD", url="u", text="Exercise increased caution.", level="2"
        )
        s2 = await storage.insert_snapshot(
            db,
            source="us",
            country="MD",
            url="u",
            text="Reconsider travel due to armed conflict in the region.",
            level="3",
        )
        await storage.insert_change(
            db,
            source="us",
            country="MD",
            prev_snapshot=s1,
            new_snapshot=s2,
            diff="LEVEL: 2 -> 3\n+Reconsider travel due to armed conflict in the region.",
        )
        await db.commit()
        stats = await classify_pending(db, settings, None)
        assert stats == {"changes": 1, "snapshots": 1, "claude": 0}
        change = await storage.get_classification(db, "change", 1)
        data = json.loads(change["payload"])
        assert data["change_type"] == "level_raised" and data["reason"] == "armed_conflict"
        # Idempotent.
        assert (await classify_pending(db, settings, None))["changes"] == 0
