# ruff: noqa: E501  (fixture mirrors long lines of the rendered page)
import httpx
import pytest

from tension_index import war_status


# Shape of the rendered page (MediaWiki wraps headings in <div class="mw-heading">).
def link(name: str) -> str:
    return f'<a href="/wiki/{name.replace(" ", "_")}" title="{name}">{name}</a>'


def flag(name: str) -> str:
    return f'<span class="flagicon"><img alt=""></span>&nbsp;{link(name)}'


def table(*rows: str) -> str:
    head = (
        "<tr><th>Start of conflict</th><th>Conflict</th><th>Continent</th>"
        "<th>Location</th><th>Deaths</th></tr>"
    )
    return f'<table class="wikitable sortable"><tbody>{head}{"".join(rows)}</tbody></table>'


# Shape of the rendered page: h2 "List of current wars and conflicts" with h3 death-toll
# sections, each holding a wikitable (Location column, rowspans for continents).
HTML = f"""
<div class="mw-heading mw-heading2"><h2 id="Criteria">Criteria</h2></div>
<p>{link("Poland")} mentioned in the intro.</p>
<div class="mw-heading mw-heading2"><h2 id="List">List of current wars and conflicts</h2></div>
<div class="mw-heading mw-heading3"><h3>Major wars (10,000 or more combat-related deaths in current or previous year)</h3></div>
{
    table(
        f'<tr><td>2022</td><td>{link("Russo-Ukrainian war")}</td><td rowspan="2">Europe</td>'
        f"<td>{flag('Ukraine')}<br>{flag('Russia')}</td><td>100000</td></tr>",
        f"<tr><td>2011</td><td>{link('Syrian civil war')} (belligerents: {flag('France')})</td>"
        f"<td>{flag('Syria')}</td><td>20000</td></tr>",
    )
}
<div class="mw-heading mw-heading3"><h3>Minor wars (1,000&#8211;9,999 combat-related deaths in current or previous year)</h3></div>
{table()}
<div class="mw-heading mw-heading3"><h3>Conflicts (100&#8211;999 combat-related deaths in current or previous year)</h3></div>
{
    table(
        f"<tr><td>2012</td><td>Mali War, supported by {flag('France')}</td><td>Africa</td>"
        f"<td>{flag('Mali')}</td><td>900</td></tr>",
        f"<tr><td>1992</td><td>Transnistria incidents</td><td>Europe</td>"
        f"<td>{flag('Moldova')}</td><td>150</td></tr>",
    )
}
<div class="mw-heading mw-heading3"><h3>Skirmishes and clashes (fewer than 100 combat-related deaths in current and previous year)</h3></div>
{
    table(
        f'<tr><td>1998</td><td>Kosovo–Serbia tensions</td><td rowspan="2">Europe</td>'
        f"<td>{flag('Kosovo')}<br>{flag('Serbia')}</td><td>5</td></tr>",
        f"<tr><td>2024</td><td>New Caledonia unrest</td><td>{flag('France')} (New Caledonia)</td><td>13</td></tr>",
    )
}
<div class="mw-heading mw-heading2"><h2>Conflict deaths in the 2020s</h2></div>
<div class="mw-heading mw-heading3"><h3>Deaths by country</h3></div>
<table class="wikitable"><tr><th>Country</th></tr><tr><td>{flag("Estonia")}</td></tr></table>
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


def test_only_location_column_counts():
    found = war_status.parse_wikipedia(HTML)
    # France as a belligerent (Syria, Mali) is ignored; its overseas unrest is in Location.
    # The rowspanned "Europe" cell must not shift the Location column of the next row.
    assert found == {"MD": "active", "XK": "clashes", "RS": "clashes", "FR": "clashes"}


def test_explain_mentions():
    fr = [m for m in war_status.mentions(HTML) if m.country == "FR"]
    assert len(fr) == 1
    assert fr[0].conflict == "New Caledonia unrest" and fr[0].column == "location"
    assert fr[0].cell == "France (New Caledonia)"


def test_table_without_location_column_is_scanned_whole():
    html = (
        "<h3>Conflicts (100–999 deaths)</h3>"
        '<table class="wikitable"><tr><th>Conflict</th><th>Where</th></tr>'
        f"<tr><td>Something</td><td>{flag('Latvia')}</td></tr></table>"
    )
    assert [(m.country, m.column) for m in war_status.mentions(html)] == [("LV", "*")]


def test_headings_diagnostics():
    hs = war_status.headings(HTML)
    assert [(h.level, h.severity) for h in hs] == [
        (2, None),
        (2, None),
        (3, "war"),
        (3, "war"),
        (3, "active"),
        (3, "clashes"),
        (2, None),
        (3, None),
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


def test_reviewed_conflicts_are_ignored():
    curated = war_status.load()
    assert curated["FR"].ignore_reason("Brazilian drug war").startswith("French Guiana")
    html = (
        "<h3>Conflicts (100–999 deaths)</h3>"
        '<table class="wikitable"><tr><th>Start of conflict</th><th>Conflict</th><th>Location</th></tr>'
        f"<tr><td>1992</td><td>Brazilian drug war</td><td>{flag('Brazil')} {flag('France')} (French Guiana)</td></tr>"
        f"<tr><td>2025</td><td>Something new</td><td>{flag('Latvia')}</td></tr></table>"
    )
    assert war_status.parse_wikipedia(html) == {"FR": "active", "LV": "active"}
    assert war_status.parse_wikipedia(html, curated) == {"LV": "active"}
