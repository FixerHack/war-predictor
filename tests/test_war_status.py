# ruff: noqa: E501  (fixture mirrors long lines of the rendered page)
import httpx
import pytest

from tension_index import war_status

# Shape of the rendered page (MediaWiki wraps headings in <div class="mw-heading">).
HTML = """
<p>Intro <a href="/wiki/Poland" title="Poland">Poland</a> outside any section.</p>
<div class="mw-heading mw-heading2"><h2 id="Major_wars">Major wars (10,000 or more deaths in current or past year)</h2></div>
<table><tr><td><a href="/wiki/Russo-Ukrainian_war_(2022%E2%80%93present)">Russo-Ukrainian war</a></td>
<td><span class="flagicon"><img alt=""></span>&nbsp;<a href="/wiki/Ukraine" title="Ukraine">Ukraine</a></td></tr></table>
<div class="mw-heading mw-heading2"><h2 id="Minor_wars">Minor wars (1,000&#8211;9,999 deaths in current or past year)</h2></div>
<a href="/wiki/Syria" title="Syria">Syria</a>
<div class="mw-heading mw-heading2"><h2 id="Conflicts">Conflicts (100&#8211;999 deaths in current or past year)</h2></div>
<div class="mw-heading mw-heading3"><h3 id="Europe">Europe</h3></div>
<a href="/wiki/Moldova" title="Moldova">Moldova</a>
<div class="mw-heading mw-heading2"><h2 id="Skirmishes">Skirmishes and clashes (fewer than 100 deaths in current or past year)</h2></div>
<a href="/wiki/Kosovo" title="Kosovo">Kosovo</a>, <a href="/wiki/Serbia" title="Serbia">Serbia</a>,
<a href="/wiki/Bosnia_and_Herzegovina" title="Bosnia and Herzegovina">BiH</a>
<div class="mw-heading mw-heading2"><h2 id="See_also">See also</h2></div>
<a href="/wiki/Estonia" title="Estonia">Estonia</a>
"""


def test_curated_file_loads():
    statuses = war_status.load()
    assert len(statuses) == 38
    assert statuses["MD"].status == "frozen"
    assert statuses["PL"].borders_aggressor == ["BY", "RU"]
    assert statuses["FR"].status == "none"


@pytest.mark.parametrize(
    ("heading", "severity"),
    [
        ("Major wars (10,000 or more deaths in current or past year)", "war"),
        ("10,000 or more deaths in current or past year", "war"),
        ("Minor wars (1,000–9,999 deaths in current or past year)", "war"),
        ("Conflicts (100–999 deaths in current or past year)", "active"),
        ("100–999 deaths", "active"),
        ("Skirmishes and clashes (fewer than 100 deaths in current or past year)", "clashes"),
        ("Fewer than 100 deaths in current or past year", "clashes"),
        ("See also", None),
        ("Europe", None),
    ],
)
def test_section_severity(heading, severity):
    assert war_status.section_severity(heading) == severity


def test_parse_rendered_html_with_subsections():
    found = war_status.parse_wikipedia(HTML)
    # Moldova sits in an h3 "Europe" under the 100-999 section -> inherits "active".
    assert found == {"MD": "active", "XK": "clashes", "RS": "clashes", "BA": "clashes"}


def test_headings_diagnostics():
    hs = war_status.headings(HTML)
    assert [(h.level, h.severity) for h in hs] == [
        (2, "war"),
        (2, "war"),
        (2, "active"),
        (3, "active"),
        (2, "clashes"),
        (2, None),
    ]


def test_unrecognised_layout_fails_loudly():
    with pytest.raises(ValueError, match="no conflict sections"):
        war_status.parse_wikipedia('<h2>Background</h2><a title="Poland">x</a><h2>See also</h2>')


def test_mismatches_ignore_frozen_absent():
    curated = war_status.load()
    assert war_status.mismatches(curated, {}) == []
    diff = war_status.mismatches(curated, {"PL": "clashes"})
    assert diff == ["PL: curated=none, wikipedia=clashes"]


async def test_fetch_wikipedia_requests_rendered_html():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["page"] == war_status.WIKI_PAGE
        assert request.url.params["prop"] == "text"
        return httpx.Response(200, json={"parse": {"text": HTML}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert "Russo-Ukrainian" in await war_status.fetch_wikipedia(client)
