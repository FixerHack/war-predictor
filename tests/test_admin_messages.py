from tension_index import collector, notify, storage


def test_admin_change_is_in_the_operator_language():
    render = notify.render_admin_change(
        "NL", "🇺🇸 State Department", "+Petty crime is common",
        {"uk": "Додано розділ про дрібну злочинність.", "en": "Added a petty crime section."},
    )  # fmt: skip
    uk = render("uk")
    assert "Нідерланди" in uk and "Додано розділ про дрібну злочинність." in uk
    assert "Added a petty crime" not in uk
    assert "<blockquote expandable>+Petty crime is common</blockquote>" in uk
    assert "Netherlands" in render("en")
    assert "класифікатор недоступний" in notify.render_admin_change("NL", "x", "+d")("uk")


def test_collector_failed_without_errors_says_why():
    text = notify.render_collector_failed("fr", 0, 0, [])("uk")
    assert "Збирач <b>fr</b>" in text and "Нічого не завантажено" in text
    text = notify.render_collector_failed("us", 2, 5, ["PL: TimeoutError"])("en")
    assert "Collector <b>us</b> failed (2 errors)" in text and "PL: TimeoutError" in text


async def test_send_admin_uses_the_language_chosen_in_the_bot(settings, monkeypatch):
    settings.telegram_bot_token, settings.telegram_chat_id = "123:abc", "42"
    sent = []

    async def fake_send(_settings, text):
        sent.append(text)
        return True

    monkeypatch.setattr(notify, "send", fake_send)
    render = notify.render_collector_failed("fr", 0, 0, [])
    await notify.send_admin(settings, render)  # unknown user: Ukrainian
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await storage.upsert_user(db, 42, lang="en")
    await notify.send_admin(settings, render)
    assert "Збирач" in sent[0] and "Collector" in sent[1]


async def test_source_without_due_countries_is_skipped(settings):
    # France does not advise on France: with only FR due there is nothing to fetch, and an
    # empty run must not be reported as a failed collector (no request is made either).
    results = await collector.collect_all(settings, sources=["fr"], countries=["FR"])
    assert results == []


def test_review_sheet():
    from tension_index.cli import review_sheet

    row = {"id": 7, "source": "us", "country": "NL", "detected_at": "2026-10-06T04:08:00+00:00",
           "diff": "+Petty crime is common.",
           "payload": '{"reason": "crime", "change_type": "security_update", "staff_posture": '
                      '"normal", "airspace": "unknown", "summary_uk": "Додано про крадіжки."}'}  # fmt: skip
    sheet = review_sheet([row])
    assert "## 1. NL · us · 2026-10-06T04:08 (зміна #7)" in sheet
    assert "причина: **crime**" in sheet and "Додано про крадіжки." in sheet
    assert "    +Petty crime is common." in sheet


def test_review_sheet_lists_a_repeated_edit_once():
    from tension_index.cli import review_sheet

    def row(i, country, line):
        return {"id": i, "source": "gov_uk", "country": country,
                "detected_at": "2026-10-07T21:10:00+00:00",
                "diff": f"@@ -1 +1 @@\n Terrorism in {country}\n-staying safe abroad\n+{line}",
                "payload": '{"reason": "terrorism", "change_type": "editorial"}'}  # fmt: skip

    sheet = review_sheet([row(3, "MK", "staying safe"), row(2, "ME", "staying safe"),
                          row(1, "AL", "new text")])  # fmt: skip
    assert "Перевірка класифікацій (2)" in sheet and "Та сама правка ще в: ME" in sheet
