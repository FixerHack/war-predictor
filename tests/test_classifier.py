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
    assert c.staff_posture == "authorized_departure"  # families only: the step before staff
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
    assert call["model"] == claude.model == "claude-opus-5-5"  # provider default
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


def openrouter_settings(settings):
    settings.classifier_provider = "openrouter"
    settings.openrouter_api_key = "sk-or-test"
    return settings


async def test_openrouter_request_and_parsing(settings):
    import httpx

    s = openrouter_settings(settings)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        content = "```json\n" + json.dumps(PAYLOAD) + "\n```"
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        claude = ClaudeClassifier(s, client=client)
        out = await claude.classify(publisher="us", country="PL", text="+x", level_before=None,
                                    level_after=None, fallback=Classification())  # fmt: skip
    assert claude.model == "anthropic/claude-haiku-4.5"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-or-test"
    body = seen["body"]
    assert body["model"] == "anthropic/claude-haiku-4.5"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert out.method == "claude" and out.staff_posture == "authorized_departure"


async def test_openrouter_errors_fall_back_to_rules(settings):
    import httpx

    s = openrouter_settings(settings)
    transport = httpx.MockTransport(
        lambda r: httpx.Response(402, json={"error": {"message": "credits"}})
    )
    calls = []
    transport = httpx.MockTransport(
        lambda r: calls.append(1) or httpx.Response(402, json={"error": {"message": "credits"}})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        claude = ClaudeClassifier(s, client=client)
        for _ in range(3):  # no credits: one request, then rules for the rest of the run
            out = await claude.classify(
                publisher="us", country="PL", text="+x", level_before=None, level_after=None,
                fallback=Classification(reason="crime"),
            )  # fmt: skip
    assert len(calls) == 1 and not claude.available
    # Kept as a pending rules result, so the model gets the text on a later run.
    assert out.method == "rules_pending" and out.reason == "crime" and "HTTP 402" in out.notes[0]


async def test_openrouter_headlines(settings):
    import httpx

    from tension_index.classifier import classify_headlines

    s = openrouter_settings(settings)
    answer = {"items": [{"i": 0, "category": "domestic_emergency", "severity": 0.9},
                        {"i": 1, "category": "none", "severity": 0}]}  # fmt: skip
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}))  # fmt: skip
    async with httpx.AsyncClient(transport=transport) as client:
        labels = await classify_headlines(
            ClaudeClassifier(s, client=client), ["Poland closes border", "Football"]
        )
    assert labels == {0: ("domestic_emergency", 0.9), 1: ("none", 0.0)}


def test_make_classifier_needs_the_providers_key(settings):
    from tension_index.pipeline import make_classifier

    settings.classifier_provider = "openrouter"
    settings.anthropic_api_key = "sk-ant"
    assert make_classifier(settings) is None  # anthropic key alone is not enough
    settings.openrouter_api_key = "sk-or"
    assert make_classifier(settings).provider == "openrouter"


def test_usable_quote_drops_page_fragments():
    from tension_index.classifier import usable_quote

    assert usable_quote("3 pays") == ""
    assert usable_quote("Voir aussi") == ""
    quote = "Petty crime can occur,  especially in popular tourist locations."
    assert usable_quote(quote) == "Petty crime can occur, especially in popular tourist locations."


def test_full_page_with_bullets_is_not_read_as_a_diff():
    """Ukraine, 23 Jan 2022: the page has bullet and phone lines; rules must still see it."""
    page = (
        "Ukraine Related Calls\n+1-606-260-4379 (overseas)\n- Enroll in STEP\n"
        "On January 23, 2022, the Department of State authorized the voluntary departure of "
        "U.S. direct hire employees (USDH) and ordered the departure of eligible family members "
        "(EFM) from Embassy Kyiv due to the continued threat of Russian military action."
    )
    result = classify_rules(page)
    assert result.staff_posture == "authorized_departure"  # families ordered out = step before
    assert result.reason == "armed_conflict"


def test_staff_posture_wordings_2022():
    cases = {
        "On February 12, 2022, the Department of State ordered the departure of most U.S. direct "
        "hire employees from Embassy Kyiv.": "ordered_departure",
        "Some embassy staff and dependants are being withdrawn from Kyiv.": "authorized_departure",
        "Canada is temporarily suspending operations at its embassy in Kyiv.": "embassy_suspended",
        "We are relocating our embassy staff to Lviv.": "ordered_departure",
    }
    for text, posture in cases.items():
        assert classify_rules(text).staff_posture == posture, text


def test_routine_flight_notes_are_not_airspace_restrictions():
    routine = (
        "Check NOTAMs before flying drones. Flight restrictions apply near airports.",
        "The FAA has issued a NOTAM prohibiting U.S. civil aviation in Crimea.",
    )
    for text in routine:
        assert classify_rules(text).airspace == "unknown", text
    assert classify_rules("Moldova has closed parts of its airspace.").airspace == "restricted"
    assert classify_rules("The airspace is closed to civil flights.").airspace == "closed"


async def test_pending_rules_results_go_to_the_model_later(settings):
    """Texts classified by rules while the model was out of credits are retried."""
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await storage.insert_snapshot(
            db, source="us", country="MD", url="u", text="Reconsider travel.", level="3"
        )
        await db.commit()
        pending = classify_rules("Reconsider travel.")
        pending.method = "rules_pending"
        await storage.save_classification(
            db, ref_type="snapshot", ref_id=1, country="MD", publisher="us",
            method=pending.method, payload=pending.to_json(),
        )  # fmt: skip

        async def classify(**kw):
            return Classification(reason="armed_conflict", method="claude")

        out_of_credits = SimpleNamespace(available=False, classify=classify)
        assert (await classify_pending(db, settings, out_of_credits))["snapshots"] == 0
        model = SimpleNamespace(available=True, classify=classify)
        assert (await classify_pending(db, settings, model))["claude"] == 1
        row = await storage.get_classification(db, "snapshot", 1)
    assert row["method"] == "claude"


def fake_claude_cli(tmp_path, body: str, code: int = 0):
    """A stand-in for the `claude` binary: records its arguments and stdin, prints `body`."""
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/args"\n'
        f'cat > "{tmp_path}/stdin"\n'
        f"cat <<'JSON'\n{body}\nJSON\n"
        f"exit {code}\n"
    )
    script.chmod(0o755)
    return str(script)


async def test_claude_code_provider_uses_the_local_cli(settings, tmp_path):
    from tension_index.pipeline import make_classifier

    answer = {"reason": "armed_conflict", "change_type": "staff_posture", "level": "",
              "staff_posture": "ordered_departure", "airspace": "unknown", "borders_closed": False,
              "measure_reason": "armed_conflict", "quote": "Staff ordered to leave.",
              "summary_uk": "Персонал відкликано.", "summary_en": "Staff ordered out."}  # fmt: skip
    body = json.dumps(
        {"type": "result", "is_error": False, "result": "", "structured_output": answer}
    )
    s = settings.model_copy(update={"classifier_provider": "claude_code",
                                    "claude_code_bin": fake_claude_cli(tmp_path, body)})  # fmt: skip
    claude = make_classifier(s)
    assert claude is not None and claude.model == "haiku"
    out = await claude.classify(publisher="us", country="MD", text="Staff ordered to leave.",
                                level_before=None, level_after="4", fallback=Classification())  # fmt: skip
    assert out.method == "claude" and out.staff_posture == "ordered_departure"
    args = (tmp_path / "args").read_text().splitlines()
    assert args[:3] == ["-p", "--output-format", "json"]
    assert args[args.index("--tools") + 1] == "" and "--no-session-persistence" in args
    assert "Staff ordered to leave." in (tmp_path / "stdin").read_text()


async def test_claude_code_not_logged_in_stops_the_run(settings, tmp_path):
    body = json.dumps(
        {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}
    )
    s = settings.model_copy(update={"classifier_provider": "claude_code",
                                    "claude_code_bin": fake_claude_cli(tmp_path, body, code=1)})  # fmt: skip
    claude = ClaudeClassifier(s)
    out = await claude.classify(publisher="us", country="MD", text="x", level_before=None,
                                level_after=None, fallback=Classification(reason="crime"))  # fmt: skip
    assert out.method == "rules_pending" and not claude.available


async def test_model_calls_run_in_parallel(settings, tmp_path):
    import time

    from tension_index.pipeline import classify_with_model

    answer = {"reason": "unknown", "change_type": "none", "level": "", "staff_posture": "unknown",
              "airspace": "unknown", "borders_closed": False, "measure_reason": "unknown",
              "quote": "", "summary_uk": "", "summary_en": ""}  # fmt: skip
    body = json.dumps({"is_error": False, "result": "", "structured_output": answer})
    script = fake_claude_cli(tmp_path, body)
    slow = tmp_path / "slow"
    slow.write_text(f'#!/bin/sh\nsleep 1\nexec {script} "$@"\n')
    slow.chmod(0o755)
    s = settings.model_copy(update={"classifier_provider": "claude_code", "claude_code_bin": str(slow),
                                    "classifier_concurrency": 4})  # fmt: skip
    jobs = [({"publisher": "us", "country": "PL", "text": "x", "level_before": None,
              "level_after": None}, Classification()) for _ in range(4)]  # fmt: skip
    started = time.monotonic()
    results = await classify_with_model(ClaudeClassifier(s), jobs)
    assert [r.method for r in results] == ["claude"] * 4
    assert time.monotonic() - started < 3.5  # 4 calls of 1 s each, side by side


async def test_gateway_provider(settings):
    import httpx

    answer = {"reason": "military_threat", "change_type": "none", "level": "",
              "staff_posture": "unknown", "airspace": "unknown", "borders_closed": False,
              "measure_reason": "unknown", "quote": "", "summary_uk": "", "summary_en": ""}  # fmt: skip
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"text": "", "structured": answer})

    s = settings.model_copy(update={"classifier_provider": "gateway", "gateway_url": "http://gw:8787/",
                                    "gateway_token": "tok"})  # fmt: skip
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        claude = ClaudeClassifier(s, client=client)
        out = await claude.classify(publisher="us", country="PL", text="x", level_before=None,
                                    level_after=None, fallback=Classification())  # fmt: skip
    assert out.method == "claude" and out.reason == "military_threat"
    assert seen["url"] == "http://gw:8787/v1/complete" and seen["auth"] == "Bearer tok"
    assert seen["body"]["model"] == "haiku" and "json_schema" in seen["body"]
