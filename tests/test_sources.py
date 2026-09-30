# ruff: noqa: E501
"""Offline tests for advisory sources (payload shapes follow the documented formats)."""

import httpx
import pytest

from tension_index.countries import get_country
from tension_index.sources import REGISTRY, SourceFormatError
from tension_index.sources.au import AuSource, level_from_text
from tension_index.sources.ca import CaSource
from tension_index.sources.de import DeSource
from tension_index.sources.fr import FrSource
from tension_index.sources.us import UsSource


def client(routes: dict[str, object]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, body in routes.items():
            if str(request.url).startswith(prefix):
                if isinstance(body, str | bytes):
                    return httpx.Response(200, content=body)
                return httpx.Response(200, json=body)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_registry_publishers_match_weights():
    from tension_index.scoring import load_config

    assert set(REGISTRY) <= set(load_config()["advisory_levels"])


async def test_de():
    index = {
        "response": {
            "lastModified": 1,
            "contentList": ["1", "2"],
            "1": {
                "countryCode": "PL",
                "title": "Polen: Reise- und Sicherheitshinweise",
                "warning": False,
                "partialWarning": False,
                "situationWarning": False,
            },
            "2": {"countryCode": "MD", "warning": False, "partialWarning": True},
        }
    }
    detail = {
        "response": {
            "2": {
                "countryCode": "MD",
                "warning": False,
                "partialWarning": True,
                "content": "<h2>Sicherheit</h2><p>Von Reisen nach Transnistrien wird abgeraten.</p>",
            }
        }
    }
    routes = {
        "https://www.auswaertiges-amt.de/opendata/travelwarning/2": detail,
        "https://www.auswaertiges-amt.de/opendata/travelwarning": index,
    }
    async with client(routes) as c:
        src = DeSource(c)
        await src.prepare()
        adv = await src.fetch(get_country("MD"))
    assert adv.level == "partial_warning"
    assert "Transnistrien" in adv.text
    assert not src.supports(get_country("DE"))


async def test_de_bad_format():
    async with client({"https://www.auswaertiges-amt.de": {"unexpected": 1}}) as c:
        with pytest.raises(SourceFormatError):
            await DeSource(c).prepare()


async def test_ca():
    payload = {
        "metadata": {},
        "data": {
            "PL": {
                "country-iso": "PL",
                "advisory-state": 0,
                "has-regional-advisory": 0,
                "date-published": {"date": "2026-09-01 10:00:00"},
                "eng": {
                    "name": "Poland",
                    "url-slug": "poland",
                    "advisory-text": "Take normal security precautions",
                    "recent-updates": "<p>Editorial change.</p>",
                },
            },
            "MD": {
                "country-iso": "MD",
                "advisory-state": 1,
                "has-regional-advisory": 1,
                "eng": {
                    "name": "Moldova",
                    "url-slug": "moldova",
                    "advisory-text": "Exercise a high degree of caution",
                },
            },
        },
    }
    async with client({"https://data.international.gc.ca": payload}) as c:
        src = CaSource(c)
        await src.prepare()
        pl = await src.fetch(get_country("PL"))
        md = await src.fetch(get_country("MD"))
    assert pl.level == "normal" and pl.url == "https://travel.gc.ca/destinations/poland"
    assert "Editorial change." in pl.text
    assert md.level == "high_caution" and "Regional advisories" in md.text


async def test_au_tolerant_parsing():
    payload = [
        {
            "title": "Poland",
            "url": "/destinations/europe/poland",
            "overall_advice_level": "Exercise normal safety precautions",
            "summary": "<p>Exercise normal safety precautions in Poland.</p>",
        },
        {
            "title": "Moldova",
            "advice_level": "Reconsider your need to travel",
            "summary": "<p>Do not travel to Transnistria.</p>",
        },
    ]
    async with client({"https://www.smartraveller.gov.au": payload}) as c:
        src = AuSource(c)
        await src.prepare()
        pl = await src.fetch(get_country("PL"))
        md = await src.fetch(get_country("MD"))
    assert pl.level == "1" and pl.url.startswith("https://www.smartraveller.gov.au/destinations")
    # The overall level field wins over "do not travel" for a region in the text.
    assert md.level == "3"
    assert level_from_text("Do not travel") == "4"


US_FEED = b"""<?xml version="1.0"?><rss><channel>
<item><title>Poland - Level 1: Exercise Normal Precautions</title>
<link>https://travel.state.gov/poland.html</link><pubDate>Mon, 01 Sep 2026</pubDate>
<description>&lt;p&gt;Exercise normal precautions in Poland.&lt;/p&gt;</description>
<category domain="Country-Tag">PL</category><category domain="Threat-Level">Level 1</category></item>
<item><title>Czechia - Level 2: Exercise Increased Caution</title><link>x</link>
<description>&lt;p&gt;Terrorism.&lt;/p&gt;</description></item>
</channel></rss>"""


async def test_us():
    async with client({"https://travel.state.gov": US_FEED}) as c:
        src = UsSource(c)
        await src.prepare()
        pl = await src.fetch(get_country("PL"))
        cz = await src.fetch(get_country("CZ"))  # matched by title alias, no tag
        with pytest.raises(SourceFormatError):
            await src.fetch(get_country("EE"))
    assert pl.level == "1" and pl.text == "Exercise normal precautions in Poland."
    assert cz.level == "2"


async def test_fr_uses_main_content():
    page = "<html><nav>Menu Accueil</nav><main><h1>Pologne</h1><p>Vigilance normale.</p></main><footer>x</footer></html>"
    async with client({"https://www.diplomatie.gouv.fr": page}) as c:
        adv = await FrSource(c).fetch(get_country("PL"))
    assert adv.text == "Pologne\nVigilance normale." and adv.level is None
    assert not FrSource(c).supports(get_country("FR"))


def test_fr_alerts_text_drops_page_furniture():
    from tension_index.sources.fr import alerts_text

    page = """Voir le fil d’Ariane
Accueil
Pologne
Conseils aux voyageurs
Dernière mise à jour le : 16 septembre 2026
Information toujours valable à la date du jour
Imprimer
Vous voyagez à l'étranger ?
Pour recevoir des alertes, inscrivez-vous sur Fil d'Ariane.
S'inscrire sur Fil d'Ariane
Donnez-nous votre avis
Aidez-nous à améliorer notre service en répondant à notre enquête.
Répondre à l'enquête utilisateurs
Fermer
Pologne –Vigilance renforcée aux frontières
Des contrôles sont en place."""
    assert (
        alerts_text(page)
        == "Pologne –Vigilance renforcée aux frontières\nDes contrôles sont en place."
    )


async def test_us_does_not_confuse_fips_and_iso_codes():
    feed = b"""<rss><channel>
<item><title>Seychelles - Level 1: Exercise Normal Precautions</title><link>s</link>
<description>x</description><category domain="Country-Tag">SE</category></item>
<item><title>Sweden - Level 2: Exercise Increased Caution</title><link>w</link>
<description>y</description><category domain="Country-Tag">SW</category></item>
<item><title>Bosnia-Herzegovina - Level 2: Exercise Increased Caution</title><link>b</link>
<description>z</description><category domain="Country-Tag">BK</category></item>
<item><title>Iceland Travel Advisory</title><link>i</link>
<description>Level 1</description><category domain="Country-Tag">IC</category></item>
</channel></rss>"""
    async with client({"https://travel.state.gov": feed}) as c:
        src = UsSource(c)
        await src.prepare()
        se = await src.fetch(get_country("SE"))
        ba = await src.fetch(get_country("BA"))
        iceland = await src.fetch(get_country("IS"))  # no name match: FIPS "IC", not ISO "IS"
    assert se.title.startswith("Sweden") and se.level == "2"
    assert ba.title.startswith("Bosnia")
    assert iceland.title == "Iceland Travel Advisory"
