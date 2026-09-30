"""Human-readable explanation of a score (for alerts, the bot dashboard and the site)."""

# ruff: noqa: E501

from __future__ import annotations

from tension_index.i18n import t

PUBLISHERS = {
    "us": ("🇺🇸 Держдеп США", "🇺🇸 US State Dept"),
    "gov_uk": ("🇬🇧 МЗС Великої Британії", "🇬🇧 UK FCDO"),
    "de": ("🇩🇪 МЗС Німеччини", "🇩🇪 German Foreign Office"),
    "ca": ("🇨🇦 Уряд Канади", "🇨🇦 Government of Canada"),
    "au": ("🇦🇺 Smartraveller (Австралія)", "🇦🇺 Smartraveller (Australia)"),
    "fr": ("🇫🇷 МЗС Франції", "🇫🇷 French Foreign Ministry"),
    "easa": ("✈️ EASA", "✈️ EASA"),
    "opensky": ("✈️ Авіатрафік (OpenSky)", "✈️ Air traffic (OpenSky)"),
    "gdelt": ("📰 Медіа (GDELT)", "📰 Media (GDELT)"),
    "news": ("📰 Новини", "📰 News"),
    "ecb": ("💶 Ринки (ЄЦБ)", "💶 Markets (ECB)"),
}
KINDS = {
    "advisory_level": ("рівень рекомендації", "advisory level"),
    "staff_posture:authorized_departure": ("дозволено виїзд персоналу посольства", "authorized departure of embassy staff"),
    "staff_posture:ordered_departure": ("наказано виїзд персоналу посольства", "ordered departure of embassy staff"),
    "staff_posture:embassy_suspended": ("посольство призупинило роботу", "embassy suspended operations"),
    "staff_posture:limited_consular_services": ("обмежені консульські послуги", "limited consular services"),
    "aviation:airspace_closed": ("повітряний простір закрито", "airspace closed"),
    "aviation:airspace_restricted": ("обмеження повітряного простору", "airspace restrictions"),
    "domestic:borders_closed": ("закриття кордонів", "border closures"),
    "aviation:czib": ("бюлетень EASA щодо зони конфлікту", "EASA conflict zone bulletin"),
    "aviation:traffic_drop": ("різке падіння авіатрафіку", "sharp drop in air traffic"),
    "domestic:emergency": ("надзвичайні заходи в країні", "emergency measures in the country"),
    "domestic:mobilisation": ("оголошено мобілізацію", "mobilisation declared"),
    "aggressor:military_threat": ("військова загроза з боку агресора", "military threat from the aggressor side"),
    "aggressor:hybrid_attack": ("гібридні атаки (дрони, саботаж, глушіння GPS)", "hybrid attacks (drones, sabotage, GPS jamming)"),
    "aggressor:armed_attack": ("збройний напад", "armed attack"),
    "aggressor:mfa_advisory": ("МЗС РФ/РБ радить своїм громадянам уникати країни", "RU/BY foreign ministry advises its citizens to avoid the country"),
    "media:escalation_news": ("новини про ескалацію", "news about escalation"),
    "media:gdelt_surge": ("сплеск уваги медіа до військової теми", "surge of military-related coverage"),
    "markets:spread_jump": ("стрибок спреду облігацій", "bond spread jump"),
    "markets:fx_drop": ("падіння курсу валюти", "currency drop"),
}  # fmt: skip


def publisher_label(publisher: str, lang: str) -> str:
    uk, en = PUBLISHERS.get(publisher, (publisher, publisher))
    return uk if lang == "uk" else en


def kind_label(kind: str, lang: str) -> str:
    if kind in KINDS:
        uk, en = KINDS[kind]
        return uk if lang == "uk" else en
    if kind.startswith("advisory_update"):
        return t(lang, "kind_update")
    return kind.split(":")[-1].replace("_", " ")


def flag_lines(flags: list[str], lang: str) -> list[str]:
    out = []
    for flag in flags:
        if flag.startswith("synchrony:"):
            out.append(t(lang, "flag_synchrony", n=flag.split(":")[1]))
        elif flag in ("isolated", "regional_escalation", "low_coverage"):
            out.append(t(lang, "flag_" + flag))
    return out


def reasons(payload: dict, lang: str, limit: int = 3) -> list[str]:
    """Top contributors as short lines: who says what, with a quote when available."""
    lines = []
    for c in payload.get("top", [])[:limit]:
        line = f"{publisher_label(c['publisher'], lang)}: {kind_label(c['kind'], lang)}"
        note = (c.get("note") or "").strip()
        if note:
            line += f" — «{note[:160]}»"
        lines.append(line)
    return lines


def explain(payload: dict, lang: str) -> str:
    parts = reasons(payload, lang) + flag_lines(payload.get("flags", []), lang)
    if payload.get("floors"):
        parts.append(t(lang, "floor_hit"))
    return "\n".join(f"• {p}" for p in parts)
