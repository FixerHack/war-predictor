import httpx

from tension_index.countries import get_country
from tension_index.sources.base import html_to_text
from tension_index.sources.gov_uk import GovUkSource, parse

PAYLOAD = {
    "title": "Poland travel advice",
    "public_updated_at": "2026-09-01T10:00:00Z",
    "details": {
        "alert_status": [],
        "parts": [
            {"title": "Warnings and insurance", "slug": "warnings", "body": "<p>No warnings.</p>"},
            {
                "title": "Safety",
                "slug": "safety",
                "body": "<h2>Crime</h2><ul><li>Pickpockets</li></ul>",
            },
        ],
    },
}


def test_html_to_text():
    assert html_to_text("<p>One</p><ul><li>Two</li><li>Three</li></ul>") == "One\nTwo\nThree"


def test_parse():
    adv = parse("PL", "poland", PAYLOAD)
    assert adv.url == "https://www.gov.uk/foreign-travel-advice/poland"
    assert adv.level == "none"
    assert "## Safety\nCrime\nPickpockets" in adv.text


def test_parse_alert_status():
    payload = {**PAYLOAD, "details": {**PAYLOAD["details"], "alert_status": ["b", "a"]}}
    assert parse("PL", "poland", payload).level == "a,b"


async def test_fetch_uses_content_api():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adv = await GovUkSource(client).fetch(get_country("PL"))
    assert seen == ["https://www.gov.uk/api/content/foreign-travel-advice/poland"]
    assert adv.country == "PL"


def test_uk_itself_not_supported():
    assert not GovUkSource(None).supports(get_country("GB"))  # type: ignore[arg-type]
