"""Machine translation of the interface into the languages of languages.py.

Sources (written by hand, uk + en): the site texts (site/dashboard/i18n/{uk,en}.json), the bot
texts (i18n.TEXTS), source and event labels (explain.PUBLISHERS / KINDS) and country names.
`tension-index translate` sends the English texts (Ukrainian alongside for context) to Claude
in batches and writes src/tension_index/locales/<lang>.json. Only new or changed texts are
sent again: each translation remembers a hash of its English source. A translation that
loses a placeholder ({n}) or an HTML tag is rejected, and English is shown instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import Counter
from pathlib import Path

from tension_index.languages import ENGLISH_NAMES, LANGUAGES, SOURCE

log = logging.getLogger(__name__)

BATCH_CHARS = 1000  # long paragraphs: each batch must finish within one model call
PARALLEL = 4
TOKENS = re.compile(r"\{[a-z_]+\}|<[^>]+>")
SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "text": {"type": "string"}},
                "required": ["key", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
PROMPT = """You translate the interface of Tension Index, a public indicator of escalation \
signals for 38 European countries, from English into {language}. People read it on their \
phones to understand the situation in their country.

Rules:
- Precise, calm and neutral; never more alarming than the English. The index is an indicator \
of signals, never a forecast, prediction or probability: keep that wording exact.
- Keep placeholders such as {{n}} or {{hours}} and HTML tags exactly as they are.
- Keep emoji, flags, numbers, URLs and names of organisations and services (EASA, OpenSky, \
GDELT, ECB, FCDO, NATO, RULAC, Telegram) as they are.
- Countries, governments and ministries: their usual names in {language}.
- Buttons and labels stay short. Ukrainian is given for context only; translate the English.
Return every key exactly once."""


def flatten(node: object, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        out: dict[str, str] = {}
        for key, value in node.items():
            out |= flatten(value, f"{prefix}{key}.")
        return out
    if isinstance(node, list):
        out = {}
        for i, value in enumerate(node):
            out |= flatten(value, f"{prefix}{i}.")
        return out
    return {prefix[:-1]: node} if isinstance(node, str) and node else {}


def rebuild(template: object, flat: dict[str, str], prefix: str = "") -> object:
    """The template's structure with translated strings where there are any."""
    if isinstance(template, dict):
        return {k: rebuild(v, flat, f"{prefix}{k}.") for k, v in template.items()}
    if isinstance(template, list):
        return [rebuild(v, flat, f"{prefix}{i}.") for i, v in enumerate(template)]
    return flat.get(prefix[:-1], template) if isinstance(template, str) else template


def sources() -> tuple[dict[str, str], dict[str, str], dict]:
    """(English, Ukrainian) flat catalogs and the English site tree (structure template)."""
    from tension_index import explain
    from tension_index.countries import COUNTRIES
    from tension_index.i18n import SITE_I18N, TEXTS

    site = {
        lang: json.loads((SITE_I18N / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in SOURCE
    }
    cats = {}
    for i, lang in enumerate(SOURCE):
        flat = {f"site.{k}": v for k, v in flatten(site[lang]).items()}
        flat |= {f"bot.{k}": v[lang] for k, v in TEXTS.items()}
        flat |= {f"pub.{k}": v[i] for k, v in explain.PUBLISHERS.items()}
        flat |= {f"kind.{k}": v[i] for k, v in explain.KINDS.items()}
        flat |= {
            f"country.{c}": (x.name_uk if lang == "uk" else x.name) for c, x in COUNTRIES.items()
        }
        cats[lang] = flat
    return cats["en"], cats["uk"], site["en"]


def digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def valid(english: str, translated: str) -> bool:
    return bool(translated.strip()) and Counter(TOKENS.findall(english)) == Counter(
        TOKENS.findall(translated)
    )


def batches(keys: list[str], en: dict[str, str]) -> list[list[str]]:
    out, cur, size = [], [], 0
    for key in keys:
        if cur and size + len(en[key]) > BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(key)
        size += len(en[key])
    return out + ([cur] if cur else [])


def load(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """(flat translations, their source hashes) of an existing locale file."""
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    flat = {f"site.{k}": v for k, v in flatten(data.get("site", {})).items()}
    for section in ("bot", "pub", "kind", "country"):
        flat |= {f"{section}.{k}": v for k, v in data.get(section, {}).items()}
    return flat, data.get("_source", {})


def save(path: Path, flat: dict[str, str], hashes: dict[str, str], site_template: dict) -> None:
    site = {k[5:]: v for k, v in flat.items() if k.startswith("site.")}
    data: dict = {"_source": dict(sorted(hashes.items())), "site": rebuild(site_template, site)}
    for section in ("bot", "pub", "kind", "country"):
        data[section] = {
            k[len(section) + 1 :]: v for k, v in sorted(flat.items()) if k.startswith(f"{section}.")
        }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


async def translate_lang(
    claude, lang: str, out_dir: Path, parallel: int = PARALLEL
) -> dict[str, int]:
    en, uk, site_template = sources()
    path = out_dir / f"{lang}.json"
    flat, hashes = load(path)
    todo = [k for k, v in en.items() if hashes.get(k) != digest(v) or k not in flat]
    stats = {"kept": len(en) - len(todo), "translated": 0, "rejected": 0}
    system = PROMPT.format(language=ENGLISH_NAMES[lang])
    slots = asyncio.Semaphore(max(1, parallel))  # low on a shared subscription

    async def one(keys: list[str]) -> None:
        payload = [{"key": k, "en": en[k], "uk": uk.get(k, "")} for k in keys]
        async with slots:
            text, problem = await claude._call(
                system, json.dumps(payload, ensure_ascii=False), SCHEMA, 8192
            )
        if text is None:
            log.warning("%s: batch of %d failed: %s", lang, len(keys), problem)
            return
        try:
            items = json.loads(text)["items"]
        except (ValueError, KeyError, TypeError):
            log.warning("%s: unparseable batch", lang)
            return
        for item in items:
            key, value = item.get("key"), item.get("text", "")
            if key not in en or key not in keys:
                continue
            if valid(en[key], value):
                flat[key], hashes[key] = value, digest(en[key])
                stats["translated"] += 1
            else:
                stats["rejected"] += 1

    await asyncio.gather(*(one(b) for b in batches(todo, en)))
    # Drop keys whose English source is gone.
    flat = {k: v for k, v in flat.items() if k in en}
    hashes = {k: v for k, v in hashes.items() if k in en}
    save(path, flat, hashes, site_template)
    return stats


def targets(requested: list[str] | None) -> list[str]:
    langs = requested or [lang for lang in LANGUAGES if lang not in SOURCE]
    unknown = [lang for lang in langs if lang not in LANGUAGES or lang in SOURCE]
    if unknown:
        raise ValueError(f"not a target language: {', '.join(unknown)}")
    return langs
