import httpx

from tension_index import war_status

WIKITEXT = """
Intro text.
== 10,000 or more deaths in current or past year ==
{| class="wikitable"
| [[Russo-Ukrainian War]] || {{flag|Ukraine}} {{flag|Russia}}
|}
== 1,000–9,999 deaths in current or past year ==
| Something || {{flagicon|Syria}} [[Syria]]
== 100–999 deaths in current or past year ==
| Unrest || {{flagcountry|Moldova}}
== Fewer than 100 deaths in current or past year ==
| Tensions || {{flag|Kosovo}} and [[Serbia|Serbian]] forces; {{flag|Poland}}
== See also ==
{{flag|Estonia}}
"""


def test_curated_file_loads():
    statuses = war_status.load()
    assert len(statuses) == 38
    assert statuses["MD"].status == "frozen"
    assert statuses["PL"].borders_aggressor == ["BY", "RU"]
    assert statuses["FR"].status == "none"


def test_parse_wikipedia_sections():
    found = war_status.parse_wikipedia(WIKITEXT)
    assert found == {"MD": "active", "XK": "clashes", "RS": "clashes", "PL": "clashes"}


def test_mismatches_ignore_frozen_absent():
    curated = war_status.load()
    assert war_status.mismatches(curated, {}) == []
    diff = war_status.mismatches(curated, {"PL": "clashes"})
    assert diff == ["PL: curated=none, wikipedia=clashes"]


async def test_fetch_wikipedia():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["page"] == war_status.WIKI_PAGE
        return httpx.Response(200, json={"parse": {"wikitext": WIKITEXT}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert "Russo-Ukrainian" in await war_status.fetch_wikipedia(client)


def test_unrecognised_layout_fails_loudly():
    import pytest

    with pytest.raises(ValueError, match="no conflict sections"):
        war_status.parse_wikipedia("== Background ==\n{{flag|Poland}}\n== See also ==\n")
