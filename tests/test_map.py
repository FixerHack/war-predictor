"""The map shapes (site/dashboard/europe.json, built by scripts/build_map.py)."""

import importlib.util
import json
import re
from pathlib import Path

from tension_index.countries import COUNTRIES

ROOT = Path(__file__).resolve().parents[1]
GEO = json.loads((ROOT / "site" / "dashboard" / "europe.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("build_map", ROOT / "scripts" / "build_map.py")
build_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_map)


def rings(d: str) -> list[list[tuple[float, float]]]:
    return [
        [tuple(map(float, p.split(","))) for p in sub.split("L")]
        for sub in re.findall(r"M([^Z]+)Z", d)
    ]


def owner(lon: float, lat: float) -> list[str]:
    x0, y0, _, _, scale = build_map.frame_box()
    px, py = build_map.project(lon, lat)
    pt = ((px - x0) * scale, (py - y0) * scale)
    shapes = {**GEO["countries"], **GEO["context"]}
    return [c for c, d in shapes.items() if any(build_map.inside(pt, [r]) for r in rings(d))]


def test_every_monitored_country_and_the_context_have_a_shape_and_a_label():
    assert set(GEO["countries"]) == set(COUNTRIES)
    assert set(GEO["context"]) == {"UA", "RU", "BY"}
    assert set(GEO["labels"]) == set(COUNTRIES) | {"UA", "RU", "BY"}
    assert GEO["viewBox"].startswith("0 0 1000 ")


def test_crimea_is_ukraine_and_cities_land_in_their_country():
    for lon, lat in (
        (34.10, 44.95),
        (33.52, 44.60),
        (36.47, 45.36),
    ):  # Simferopol, Sevastopol, Kerch
        assert owner(lon, lat) == ["UA"]
    assert owner(37.6, 55.75) == ["RU"]  # Moscow
    assert owner(21.16, 42.66) == ["XK"]  # Pristina
    assert owner(14.51, 35.90) == ["MT"]  # Valletta
    assert owner(33.40, 35.30) == ["CY"]  # the north of the island is shown as Cyprus


def test_grey_countries_are_named_and_dependencies_join_their_country():
    assert GEO["others"] and not set(GEO["others"]) & (set(COUNTRIES) | {"UA", "RU", "BY", "ZZ"})
    assert all(re.fullmatch(r"[A-Z]{2}", c) for c in GEO["others"])
    assert owner(-4.48, 54.15) == ["GB"]  # Douglas, Isle of Man
    assert owner(19.94, 60.10) == ["FI"]  # Mariehamn, Aland
    page = (ROOT / "site" / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "geo.others" in page and "geo.other}" not in page
