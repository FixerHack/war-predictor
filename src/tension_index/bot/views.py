"""Pure rendering of bot screens: (text, keyboard). No I/O, easy to test."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from html import escape as _escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tension_index.bot.callbacks import CountryCb, LangCb, MenuCb, ViewCb
from tension_index.countries import COUNTRIES, get_country
from tension_index.i18n import t
from tension_index.storage import MAX_FOLLOWED
from tension_index.war_status import ICONS, WarStatus

# Telegram HTML needs only <, > and & escaped; quotes stay readable (Придністров'я).
escape = partial(_escape, quote=False)

LEVEL_ICONS = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴", "critical": "🟥"}
# Neighbours outside the monitored set, for the "borders" line.
EXTRA_NAMES = {
    "UA": ("Україна", "Ukraine"),
    "RU": ("Росія", "Russia"),
    "BY": ("Білорусь", "Belarus"),
}

Screen = tuple[str, InlineKeyboardMarkup]


@dataclass(slots=True)
class DashboardData:
    lang: str
    country: str
    notify: bool
    score: float | None
    level: str | None
    war: WarStatus
    changes_7d: int
    updated: str | None
    reasons: list[str] = field(default_factory=list)  # from explain.reasons()
    notes: list[str] = field(default_factory=list)  # flags and threshold events, explained
    map_url: str = ""  # the country on the public map
    digest: bool = False
    # other followed countries: (code, score or None, level or None, war status)
    others: list[tuple[str, float | None, str | None, str]] = field(default_factory=list)
    refresh_hours: float | None = None  # how often the country is re-checked (refresh.py)


def _flag(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def _name(code: str, lang: str) -> str:
    if code in COUNTRIES:
        return COUNTRIES[code].title(lang)
    uk, en = EXTRA_NAMES.get(code, (code, code))
    return uk if lang == "uk" else en


def bar(score: float, width: int = 10) -> str:
    filled = max(0, min(width, round(score)))
    return "▰" * filled + "▱" * (width - filled)


def language_screen() -> Screen:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data=LangCb(code="uk").pack()),
                InlineKeyboardButton(text="🇬🇧 English", callback_data=LangCb(code="en").pack()),
            ]
        ]
    )
    return t(None, "choose_lang"), kb


def country_screen(lang: str, followed: list[str] | None = None) -> Screen:
    """First choice (nothing followed yet: one tap opens the dashboard) or the follow list
    with ✅ marks and a Done button."""
    followed = followed or []
    countries = sorted(COUNTRIES.values(), key=lambda c: c.title(lang))
    buttons = [
        InlineKeyboardButton(
            text=f"{'✅ ' if c.code in followed else ''}{c.flag} {c.title(lang)}",
            callback_data=CountryCb(code=c.code).pack(),
        )
        for c in countries
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    if not followed:
        return t(lang, "choose_country"), InlineKeyboardMarkup(inline_keyboard=rows)
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_done"), callback_data=MenuCb(action="home").pack())]
    )
    text = t(lang, "choose_countries", max=MAX_FOLLOWED)
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def dashboard_screen(d: DashboardData) -> Screen:
    lang = d.lang
    country = get_country(d.country)
    lines = [
        f"<b>{t(lang, 'title')}</b>",
        "",
        f"{country.flag} <b>{escape(country.title(lang))}</b>",
    ]

    if d.score is None or d.level is None:
        lines.append(f"{t(lang, 'tension')}: {t(lang, 'calibrating')}")
    else:
        lines.append(
            f"{t(lang, 'tension')}: {LEVEL_ICONS[d.level]} <b>{d.score:.1f}</b> / 10 · "
            f"{t(lang, 'level_' + d.level)}"
        )
        lines.append(bar(d.score))
        lines.append(f"<i>{t(lang, 'mean_' + d.level)}</i>")
        if d.reasons:
            lines.append(f"<b>{t(lang, 'why')}:</b>")
            lines += [f"• {escape(r)}" for r in d.reasons]
        lines += [f"ℹ️ {escape(n)}" for n in d.notes]

    war = d.war
    lines.append(f"{t(lang, 'war_status')}: {ICONS[war.status]} {t(lang, 'war_' + war.status)}")
    if war.note(lang):
        lines.append(f"<i>{escape(war.note(lang))}</i>")
    neighbours = [f"{_flag(c)} {_name(c, lang)} ({t(lang, 'at_war')})" for c in war.borders_war]
    neighbours += [f"{_flag(c)} {_name(c, lang)}" for c in war.borders_aggressor]
    if neighbours:
        lines.append(f"{t(lang, 'borders')}: " + " · ".join(neighbours))
    lines.append(f"{t(lang, 'changes_7d')}: {d.changes_7d}")
    if d.others:
        lines += ["", f"<b>{t(lang, 'others')}:</b>"]
        for code, score, level, war in d.others:
            c = get_country(code)
            value = f"{LEVEL_ICONS[level]} {score:.1f}" if score is not None and level else "⏳"
            war_icon = f" {ICONS[war]}" if war != "none" else ""
            lines.append(f"{c.flag} {escape(c.title(lang))} · {value}{war_icon}")
    lines.append("")
    lines.append(f"🔔 {t(lang, 'notifications')}: {t(lang, 'on' if d.notify else 'off')}")
    lines.append(f"📰 {t(lang, 'digest')}: {t(lang, 'on' if d.digest else 'off')}")
    lines.append(f"🌐 {t(lang, 'language')}: {t(lang, 'lang_name')}")
    if d.updated:
        line = f"🕒 {t(lang, 'updated')}: {d.updated.replace('T', ' ')[:16]} UTC"
        if d.refresh_hours:
            line += " · " + (
                t(lang, "refresh_hourly")
                if d.refresh_hours <= 1
                else t(lang, "refresh_every", hours=f"{d.refresh_hours:g}")
            )
        lines.append(line)
    lines += ["", f"<i>{t(lang, 'disclaimer')}</i>"]

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_notify_on" if d.notify else "btn_notify_off"),
                    callback_data=MenuCb(action="notify").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_digest_on" if d.digest else "btn_digest_off"),
                    callback_data=MenuCb(action="digest").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_countries", n=len(d.others) + 1, max=MAX_FOLLOWED),
                    callback_data=MenuCb(action="country").pack(),
                ),
                InlineKeyboardButton(
                    text=t(lang, "btn_lang"), callback_data=MenuCb(action="lang").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_refresh"), callback_data=MenuCb(action="refresh").pack()
                ),
                InlineKeyboardButton(
                    text=t(lang, "btn_about"), callback_data=MenuCb(action="about").pack()
                ),
            ],
        ]
        + ([[InlineKeyboardButton(text=t(lang, "btn_map"), url=d.map_url)]] if d.map_url else [])
        + [
            [
                InlineKeyboardButton(
                    text=f"{get_country(code).flag} {get_country(code).title(lang)}",
                    callback_data=ViewCb(code=code).pack(),
                )
                for code, *_ in d.others[i : i + 2]
            ]
            for i in range(0, len(d.others), 2)
        ]
    )
    return "\n".join(lines), kb


def about_screen(lang: str) -> Screen:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_back"), callback_data=MenuCb(action="home").pack()
                )
            ]
        ]
    )
    return t(lang, "about"), kb
