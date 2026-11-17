import json
import re
from pathlib import Path

import pytest

from tension_index import explain, translate
from tension_index.classifier import Classification, ClaudeClassifier, classify_rules
from tension_index.countries import COUNTRIES
from tension_index.i18n import LOCALES, SITE_I18N, locale, site_catalog, t
from tension_index.languages import COUNTRY_LANGS, LANGUAGES, SOURCE, local_languages, normalize

ROOT = Path(__file__).resolve().parents[1]


def test_page_knows_the_same_languages():
    page = (ROOT / "site" / "dashboard" / "index.html").read_text(encoding="utf-8")
    block = re.search(r"const LANG_NAMES = \{(.*?)\};", page).group(1)
    assert dict(re.findall(r'(\w+): "([^"]+)"', block)) == LANGUAGES


def test_every_country_has_supported_languages():
    assert set(COUNTRY_LANGS) == set(COUNTRIES)
    assert all(lang in LANGUAGES for langs in COUNTRY_LANGS.values() for lang in langs)
    assert local_languages("BE") == ("nl", "fr", "de") and local_languages("GB") == ()


@pytest.mark.parametrize(
    ("raw", "lang"),
    [("pl-PL", "pl"), ("no", "nb"), ("nn", "nb"), ("sr-Latn", "sr"), ("ru", None), (None, None)],
)
def test_normalize_language_codes(raw, lang):
    assert normalize(raw) == lang


def test_site_sources_have_the_same_keys():
    uk, en = (json.loads((SITE_I18N / f"{x}.json").read_text(encoding="utf-8")) for x in SOURCE)
    assert set(translate.flatten(uk)) == set(translate.flatten(en))


def test_flatten_and_rebuild_keep_the_structure():
    tree = {"a": "A", "b": ["x", ["y", "z"]], "c": {"d": "D"}, "e": "LEVELS"}
    flat = translate.flatten(tree)
    assert flat == {"a": "A", "b.0": "x", "b.1.0": "y", "b.1.1": "z", "c.d": "D", "e": "LEVELS"}
    assert translate.rebuild(tree, {"b.1.0": "Y"}) == {
        "a": "A",
        "b": ["x", ["Y", "z"]],
        "c": {"d": "D"},
        "e": "LEVELS",
    }


def test_translations_keep_placeholders_and_tags():
    assert translate.valid("Countries ({n}/{max})", "Kraje ({n}/{max})")
    assert not translate.valid("Countries ({n}/{max})", "Kraje ({n})")
    assert not translate.valid("<b>Healthcheck FAIL</b>", "Kontrola FAIL")
    assert not translate.valid("Done", "  ")


def test_every_locale_file_is_valid():
    en, _, _ = translate.sources()
    for path in LOCALES.glob("*.json"):
        lang = path.stem
        assert lang in LANGUAGES and lang not in SOURCE, path
        flat, hashes = translate.load(path)
        assert set(flat) <= set(en), path
        for key, text in flat.items():
            assert translate.valid(en[key], text), (path, key)


def test_fallbacks_for_untranslated_languages(monkeypatch):
    monkeypatch.setattr("tension_index.i18n.locale", lambda lang: {})
    monkeypatch.setattr("tension_index.explain.locale", lambda lang: {})
    assert t("is", "disclaimer") == t("en", "disclaimer")
    assert t(None, "disclaimer") == t("uk", "disclaimer")
    assert explain.publisher_label("us", "is") == "🇺🇸 US State Dept"
    assert explain.kind_label("aviation:czib", "is") == "EASA conflict zone bulletin"


def test_site_catalog_carries_labels():
    uk = site_catalog("uk")
    assert uk["pub"]["us"] == "🇺🇸 Держдеп США" and uk["kind"]["aviation:czib"].startswith(
        "бюлетень"
    )
    assert site_catalog("en")["notice"] and site_catalog("en")["pub"]["news"] == "📰 News"
    locale.cache_clear()


async def test_claude_writes_summaries_in_the_country_languages(settings):
    import json as _json
    from types import SimpleNamespace

    payload = {
        "reason": "terrorism", "change_type": "security_update", "level": "", "staff_posture": "unknown",
        "airspace": "unknown", "borders_closed": False, "measure_reason": "unknown", "quote": "",
        "summary_uk": "Теракт.", "summary_en": "Attack.",
        "summaries_local": [{"lang": "pl", "text": "Zamach."}, {"lang": "de", "text": "Anschlag."}],
    }  # fmt: skip
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        content = [SimpleNamespace(type="text", text=_json.dumps(payload))]
        return SimpleNamespace(stop_reason="end_turn", content=content)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    result = await ClaudeClassifier(settings, client=client).classify(
        publisher="gov_uk", country="PL", text="+x", level_before=None, level_after=None,
        fallback=classify_rules("+x"),
    )  # fmt: skip
    assert result.summaries == {"pl": "Zamach."}  # German is not a language of Poland
    assert "Local languages: pl (Polish)" in str(calls[0]["messages"])
    assert Classification.from_json(result.to_json()).summaries == {"pl": "Zamach."}
