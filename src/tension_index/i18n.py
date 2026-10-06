"""User-facing strings for the bot (uk/en)."""

from __future__ import annotations

LANGS = ("uk", "en")
DEFAULT_LANG = "uk"

TEXTS: dict[str, dict[str, str]] = {
    "choose_lang": {
        "uk": "Оберіть мову · Choose your language",
        "en": "Оберіть мову · Choose your language",
    },
    "choose_country": {
        "uk": "Оберіть країну, за якою стежити:",
        "en": "Choose the country to follow:",
    },
    "title": {"uk": "Tension Index · панель", "en": "Tension Index · dashboard"},
    "tension": {"uk": "Напруга", "en": "Tension"},
    "calibrating": {
        "uk": "⏳ калібрування: даних ще недостатньо",
        "en": "⏳ calibrating: not enough data yet",
    },
    "war_status": {"uk": "Статус війни", "en": "War status"},
    "borders": {"uk": "Межує з", "en": "Borders"},
    "at_war": {"uk": "війна", "en": "at war"},
    "changes_7d": {"uk": "Зміни рекомендацій за 7 днів", "en": "Advisory changes, last 7 days"},
    "notifications": {"uk": "Сповіщення", "en": "Notifications"},
    "on": {"uk": "увімкнено", "en": "on"},
    "off": {"uk": "вимкнено", "en": "off"},
    "language": {"uk": "Мова", "en": "Language"},
    "lang_name": {"uk": "українська", "en": "English"},
    "updated": {"uk": "Оновлено", "en": "Updated"},
    "refresh_every": {"uk": "перевірка кожні {hours} год", "en": "checked every {hours} h"},
    "refresh_hourly": {"uk": "перевірка щогодини", "en": "checked hourly"},
    "disclaimer": {
        "uk": "Це індикатор стану сигналів, а не прогноз і не порада щодо виїзду.",
        "en": "This is an indicator of signals, not a forecast or advice to leave.",
    },
    "btn_notify_on": {"uk": "🔔 Сповіщення: увімк.", "en": "🔔 Notifications: on"},
    "btn_notify_off": {"uk": "🔕 Сповіщення: вимк.", "en": "🔕 Notifications: off"},
    "btn_country": {"uk": "🌍 Змінити країну", "en": "🌍 Change country"},
    "btn_countries": {"uk": "🌍 Країни ({n}/{max})", "en": "🌍 Countries ({n}/{max})"},
    "btn_done": {"uk": "✔️ Готово", "en": "✔️ Done"},
    "btn_digest_on": {"uk": "📰 Дайджест: увімк.", "en": "📰 Digest: on"},
    "btn_digest_off": {"uk": "📰 Дайджест: вимк.", "en": "📰 Digest: off"},
    "choose_countries": {
        "uk": "Позначте до {max} країн, за якими стежити. Натисніть ще раз, щоб прибрати.",
        "en": "Tick up to {max} countries to follow. Tap again to remove.",
    },
    "max_reached": {
        "uk": "Можна відстежувати до {max} країн",
        "en": "You can follow up to {max} countries",
    },
    "keep_one": {"uk": "Залиште хоча б одну країну", "en": "Keep at least one country"},
    "others": {"uk": "Також відстежуєте", "en": "Also following"},
    "digest": {"uk": "Дайджест", "en": "Digest"},
    "digest_title": {"uk": "📰 Щоденний підсумок", "en": "📰 Daily summary"},
    "digest_region": {
        "uk": "У регіоні найбільше зросла напруга: {items}",
        "en": "Largest rises in the region: {items}",
    },
    "digest_quiet": {
        "uk": "У регіоні без помітних змін.",
        "en": "No notable changes in the region.",
    },
    "btn_lang": {"uk": "🌐 English", "en": "🌐 Українська"},
    "btn_refresh": {"uk": "🔄 Оновити", "en": "🔄 Refresh"},
    "btn_about": {"uk": "ℹ️ Як рахується", "en": "ℹ️ How it works"},
    "btn_back": {"uk": "« Назад", "en": "« Back"},
    "about": {
        "uk": (
            "<b>Як рахується напруга</b>\n\n"
            "Шкала 0–10 зводить шість блоків сигналів: рекомендації урядів своїм громадянам "
            "і статус персоналу посольств, авіація і повітряний простір, внутрішні заходи "
            "країни, сигнали з боку агресора, медіа й аналітика, ринки.\n\n"
            "Важать причина (збройний конфлікт важить більше, ніж тероризм), кількість "
            "незалежних джерел, синхронність держав і відхилення від звичного рівня країни. "
            "Вирішальні події (виїзд персоналу посольств, закриття неба, мобілізація) "
            "гарантують мінімальний бал.\n\n"
            "🟢 0–2 базовий фон · 🟡 3–4 поодинокі зміни · 🟠 5–6 кілька блоків · "
            "🔴 7–8 виїзд персоналу, обмеження неба · 🟥 9–10 критичний рівень\n\n"
            "Статус війни показується окремо: шкала вимірює ескалацію, а не наявний конфлікт."
        ),
        "en": (
            "<b>How tension is scored</b>\n\n"
            "The 0–10 scale combines six signal blocks: governments' travel advice and embassy "
            "staff posture, aviation and airspace, the country's own emergency measures, "
            "signals from the aggressor side, media and analysis, markets.\n\n"
            "What counts: the stated reason (armed conflict weighs more than terrorism), the "
            "number of independent sources, several governments acting in sync, and deviation "
            "from the country's usual level. Decisive events (embassy staff departure, airspace "
            "closure, mobilisation) guarantee a minimum score.\n\n"
            "🟢 0–2 baseline · 🟡 3–4 isolated changes · 🟠 5–6 several blocks · "
            "🔴 7–8 staff departure, airspace limits · 🟥 9–10 critical\n\n"
            "War status is shown separately: the scale measures escalation, not an existing war."
        ),
    },
    "help": {
        "uk": "/start — панель\n/help — довідка",
        "en": "/start — dashboard\n/help — help",
    },
    # Neutral names, the same as on the map (colours are for the map only).
    "level_green": {"uk": "низький", "en": "low"},
    "level_yellow": {"uk": "помірний", "en": "moderate"},
    "level_orange": {"uk": "підвищений", "en": "elevated"},
    "level_red": {"uk": "високий", "en": "high"},
    "level_critical": {"uk": "критичний", "en": "critical"},
    "mean_green": {
        "uk": "Фон звичайний: ознак ескалації в джерелах немає.",
        "en": "Usual background: no signs of escalation in the sources.",
    },
    "mean_yellow": {
        "uk": "Поодинокі зміни, які варто відстежувати; загальної картини поки немає.",
        "en": "Isolated changes worth watching; no pattern yet.",
    },
    "mean_orange": {
        "uk": "Кілька незалежних сигналів одночасно або один сильний у ключовому блоці.",
        "en": "Several independent signals at once, or one strong signal in a key block.",
    },
    "mean_red": {
        "uk": "Сильні сигнали: виїзд персоналу посольств, закриття неба або узгоджене посилення "
        "рекомендацій кількома урядами.",
        "en": "Strong signals: embassy staff departure, airspace closure or several governments "
        "tightening their advice together.",
    },
    "mean_critical": {
        "uk": "Вирішальні події: наказ кількох урядів про виїзд персоналу, мобілізація, закрите небо.",
        "en": "Decisive events: ordered staff departure by several governments, mobilisation, "
        "closed airspace.",
    },
    "btn_map": {"uk": "🗺 Детальніше на карті", "en": "🗺 Details on the map"},
    "war_none": {"uk": "збройного конфлікту немає", "en": "no armed conflict"},
    "war_frozen": {
        "uk": "заморожений конфлікт / окупація частини території",
        "en": "frozen conflict / partial occupation",
    },
    "war_clashes": {"uk": "окремі збройні інциденти", "en": "sporadic armed clashes"},
    "war_active": {"uk": "збройний конфлікт", "en": "armed conflict"},
    "war_war": {"uk": "війна", "en": "war"},
    "kind_update": {"uk": "оновлення тексту рекомендації", "en": "advisory text update"},
    "flag_synchrony": {
        "uk": "{n} держав(и) посилили позицію за тиждень",
        "en": "{n} governments tightened their advice within a week",
    },
    "flag_isolated": {
        "uk": "зростання лише в цій країні, сусіди без змін (можливий політичний сигнал)",
        "en": "rise in this country only, neighbours unchanged (possibly a political signal)",
    },
    "flag_regional_escalation": {
        "uk": "одночасне зростання в регіоні",
        "en": "simultaneous rise across the region",
    },
    "flag_low_coverage": {
        "uk": "недостатньо свіжих даних для балу",
        "en": "not enough fresh data for a score",
    },
    "floor_hit": {
        "uk": "спрацювала порогова подія (мінімальний бал за правилами шкали)",
        "en": "a threshold event applies (minimum score by the scale rules)",
    },
    "why": {"uk": "Чому", "en": "Why"},
    "alert_score": {
        "uk": "{arrow} {flag} <b>{country}</b>: напруга {old} → <b>{new}</b> ({level})",
        "en": "{arrow} {flag} <b>{country}</b>: tension {old} → <b>{new}</b> ({level})",
    },
    "alert_change": {
        "uk": "🔔 {flag} <b>{country}</b>: змінилась рекомендація ({source})",
        "en": "🔔 {flag} <b>{country}</b>: travel advice changed ({source})",
    },
    # Operator messages (TELEGRAM_CHAT_ID), in the language the operator uses in the bot.
    "admin_diff": {
        "uk": "Що змінилось у тексті (мовою джерела):",
        "en": "Text diff (in the source's language):",
    },
    "admin_no_summary": {
        "uk": "Короткого опису немає: класифікатор недоступний.",
        "en": "No summary: the classifier is unavailable.",
    },
    "admin_collector_failed": {
        "uk": "❌ Збирач <b>{source}</b> не спрацював (помилок: {failed})",
        "en": "❌ Collector <b>{source}</b> failed ({failed} errors)",
    },
    "admin_nothing_fetched": {
        "uk": "Нічого не завантажено і помилок немає.",
        "en": "Nothing was fetched and there were no errors.",
    },
    "admin_health_fail": {"uk": "<b>Перевірка стану: FAIL</b>", "en": "<b>Healthcheck FAIL</b>"},
    "admin_war_check_failed": {
        "uk": "❌ Перевірка статусу війн не вдалася: {error}",
        "en": "❌ war-check failed: {error}",
    },
    "admin_war_review": {
        "uk": "⚠️ <b>Статус війн: перевірте config/conflicts.yaml</b>",
        "en": "⚠️ <b>War status: review config/conflicts.yaml</b>",
    },
}


def t(lang: str | None, key: str, **kwargs: object) -> str:
    entry = TEXTS[key]
    text = entry.get(lang or DEFAULT_LANG) or entry[DEFAULT_LANG]
    return text.format(**kwargs) if kwargs else text
