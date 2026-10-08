import httpx

from tension_index import storage
from tension_index.extra import ru_mfa


def _rss(*titles: str) -> bytes:
    items = "".join(
        f"<item><title>{t}</title><link>https://x/{i}</link></item>" for i, t in enumerate(titles)
    )
    return f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'.encode()


def test_advice_headlines_filter():
    items = [
        ("МИД рекомендовал россиянам воздержаться от поездок в Латвию", "l1", None),
        ("В МИД предупредили о возможных инцидентах из-за действий ЕС", "l2", None),  # no country
        ("МИД Латвии вызвал российского дипломата", "l3", None),  # someone else's ministry
        ("Туристы в Латвии жалуются на погоду", "l4", None),  # no ministry
    ]
    found = ru_mfa.advice_headlines(items, "tass.ru")
    assert [a["url"] for a in found] == ["l1"] and found[0]["domain"] == "tass.ru"


async def test_collect_two_outlets_confirm(settings):
    advice = "МИД России не рекомендует поездки в Литву"

    def handler(request):
        host = request.url.host
        if host == "lenta.ru":
            return httpx.Response(503)
        if host in ("tass.ru", "ria.ru"):
            return httpx.Response(200, content=_rss(advice, "Погода в Москве"))
        return httpx.Response(200, content=_rss("Новости спорта"))

    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            result = await ru_mfa.collect_ru_mfa(db, c, settings)
        assert result.ok and result.fetched == 4 and result.failed == 1 and result.changed == 1
        async with db.execute(
            "SELECT country, publisher, confirmed, tier FROM signals WHERE kind = 'aggressor:mfa_advisory'"
        ) as cur:
            assert [tuple(r) for r in await cur.fetchall()] == [("LT", "ru_media", 1, 2)]
