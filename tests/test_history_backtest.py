# ruff: noqa: E501
from datetime import date

import httpx

from tension_index import storage
from tension_index.backtest import classify_history, replay
from tension_index.history import (
    Episode,
    level_from_page,
    load_episode,
    load_episodes,
    pick_captures,
)

UA = Episode("ua-test", "UA", date(2021, 12, 1), date(2022, 2, 28), date(2022, 2, 24),
             {"us": "https://travel.state.gov/ua.html", "gov_uk": "https://www.gov.uk/ua"},
             {"min_score": 7, "before_event_days": 1})  # fmt: skip


def test_episodes_config():
    episodes = load_episodes()
    assert episodes["ukraine-2022"].event == date(2022, 2, 24)
    assert episodes["france-2016-control"].expect == {"max_score": 4.9}


def test_level_from_page():
    assert level_from_page("us", "Ukraine - Level 4: Do Not Travel. Reconsider travel ...") == "4"
    uk = "The FCDO advises against all travel to the whole of Ukraine. It also advises against all but essential travel to Crimea"
    assert level_from_page("gov_uk", uk) == "avoid_all_travel_to_whole_country"
    assert level_from_page("gov_uk", "Normal travel.") == "none"
    assert (
        level_from_page("ca", "Ukraine - AVOID ALL TRAVEL. Avoid non-essential travel to X")
        == "avoid_all"
    )
    assert level_from_page("de", "Es besteht keine Reisewarnung.") == "none"


def test_pick_captures_dense_near_event():
    rows = [[f"202112{d:02d}000000", "u"] for d in range(1, 32)] + [
        [f"202202{d:02d}000000", "u"] for d in range(1, 28)
    ]
    picked = [ts[:8] for ts, _ in pick_captures(rows, UA)]
    assert "20211201" in picked and "20211202" not in picked  # sparse early
    assert {"20220220", "20220221", "20220222"} <= set(picked)  # daily near the event


PAGES = {
    "20211201000000": {"us": "Ukraine - Level 2: Exercise Increased Caution due to crime and civil unrest.",
                       "gov_uk": "Normal travel advice for Ukraine."},
    "20220124000000": {"us": "Ukraine - Level 4: Do Not Travel due to the increased threats of Russian military action. "
                             "On January 23, the Department ordered the departure of eligible family members.",
                       "gov_uk": "Normal travel advice for Ukraine."},
    "20220213000000": {"us": "Ukraine - Level 4: Do Not Travel due to the increased threats of Russian military action. "
                             "On January 23, the Department ordered the departure of eligible family members.",
                       "gov_uk": "The FCDO advises against all travel to the whole of Ukraine due to the threat of Russian military action. "
                                 "British nationals should leave now. The embassy ordered the departure of staff."},
}  # fmt: skip


def wayback(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    publisher = "us" if "state.gov" in url else "gov_uk"
    if url.startswith("https://web.archive.org/cdx"):
        rows = [["timestamp", "original"]] + [[ts, request.url.params["url"]] for ts in PAGES]
        return httpx.Response(200, json=rows)
    ts = url.split("/web/")[1][:14]
    return httpx.Response(200, text=f"<html><main><p>{PAGES[ts][publisher]}</p></main></html>")


async def test_load_and_replay_ukraine(tmp_path, settings):
    async with storage.connect(tmp_path / "history.sqlite3") as db:
        async with httpx.AsyncClient(transport=httpx.MockTransport(wayback)) as client:
            stats = await load_episode(db, client, UA, pause=0)
        assert stats == {"us": 2, "gov_uk": 2}  # unchanged versions are skipped
        await classify_history(db, None)
        report = await replay(db, UA)
    assert report.days[0].score < 3
    assert report.first_reaching(7) == date(2022, 1, 24)  # ordered departure (US)
    # Currently the surge bonus alone lifts one government's ordered departure to 9+;
    # the scale definition wants several governments for "critical" (tuning task S8.3).
    assert report.first_reaching(9) <= date(2022, 2, 13)
    last = report.days[-1]
    assert last.top == [
        "us:staff_posture:ordered_departure",
        "gov_uk:staff_posture:ordered_departure",
    ]
    ok, detail = report.verdict()
    assert ok and "31 days before" in detail
    assert "PASS" in report.markdown() and report.csv().startswith("date,score")


async def test_control_episode_stays_low(tmp_path):
    fr = Episode(
        "fr", "FR", date(2016, 1, 1), date(2016, 1, 31), None, {"us": "u"}, {"max_score": 4.9}
    )
    async with storage.connect(tmp_path / "h.sqlite3") as db:
        await storage.migrate(db)
        await storage.insert_snapshot(db, source="us", country="FR", url="u", level="2",
                                      text="France - Level 2: Exercise Increased Caution due to terrorism.",
                                      fetched_at="2015-12-01T00:00:00+00:00")  # fmt: skip
        await db.commit()
        await classify_history(db, None)
        report = await replay(db, fr)
    ok, detail = report.verdict()
    assert ok and report.max_score < 3


async def test_wayback_get_retries_timeouts_and_busy_answers():
    from tension_index.history import wayback_get

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await wayback_get(client, "https://web.archive.org/x", backoff=0)
    assert response.text == "ok" and len(calls) == 3
