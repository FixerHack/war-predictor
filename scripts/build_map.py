"""Build site/dashboard/europe.json: projected SVG paths of the monitored countries.

Input: Natural Earth 1:50m countries as TopoJSON (public domain), e.g. world-atlas 2.0.2:
    curl -LO https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json
    uv run python scripts/build_map.py countries-50m.json

Shared borders are simplified once (on TopoJSON arcs), so neighbours never get gaps. The map
uses a Lambert azimuthal equal-area projection centred on Europe; shapes are clipped to the
frame, and each country gets a label point well inside it (pole of inaccessibility).
Run by hand when the map should change; the output is committed. Standard library only.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "site" / "dashboard" / "europe.json"

# ISO 3166 numeric (Natural Earth ids) -> our codes. Kosovo has no id: matched by name.
MONITORED = {
    "040": "AT", "056": "BE", "100": "BG", "191": "HR", "196": "CY", "203": "CZ", "208": "DK",
    "233": "EE", "246": "FI", "250": "FR", "276": "DE", "300": "GR", "348": "HU", "372": "IE",
    "380": "IT", "428": "LV", "440": "LT", "442": "LU", "470": "MT", "528": "NL", "616": "PL",
    "620": "PT", "642": "RO", "703": "SK", "705": "SI", "724": "ES", "752": "SE", "826": "GB",
    "578": "NO", "756": "CH", "352": "IS", "498": "MD", "688": "RS", "499": "ME", "807": "MK",
    "008": "AL", "070": "BA",
}  # fmt: skip
CONTEXT = {"804": "UA", "643": "RU", "112": "BY"}  # neighbours at war: hatched, never scored
BY_NAME = {"Kosovo": "XK", "N. Cyprus": "CY"}  # the island is shown as Cyprus
# Natural Earth draws Crimea as part of Russia; it is Ukraine (UN GA resolution 68/262).
# It is a separate polygon of Russia's MultiPolygon: moved to Ukraine by its centre.
CRIMEA = (32.3, 44.2, 36.8, 46.3)  # lon/lat box

LON0, LAT0 = 12.0, 53.0  # projection centre
FRAME = (-24.5, 34.5, 41.0, 71.2)  # lon/lat box the view must show (Iceland .. Cyprus)
WIDTH = 1000.0  # SVG units across the frame
SIMPLIFY = 0.35  # Douglas-Peucker tolerance, SVG units
MARGIN = 30.0  # keep this much outside the frame before clipping
# Label points the automatic search would put oddly (lon, lat).
LABEL_AT = {"RU": (37.5, 56.5), "UA": (31.5, 49.0), "NO": (9.5, 61.5), "FR": (2.5, 46.8),
            "GB": (-1.8, 52.8), "GR": (22.0, 39.6), "DK": (9.2, 56.1)}  # fmt: skip


def project(lon: float, lat: float) -> tuple[float, float]:
    lam, phi = math.radians(lon - LON0), math.radians(lat)
    phi0 = math.radians(LAT0)
    cos_c = math.sin(phi0) * math.sin(phi) + math.cos(phi0) * math.cos(phi) * math.cos(lam)
    k = math.sqrt(2.0 / max(1e-12, 1.0 + cos_c))
    x = k * math.cos(phi) * math.sin(lam)
    y = k * (math.cos(phi0) * math.sin(phi) - math.sin(phi0) * math.cos(phi) * math.cos(lam))
    return x, -y


def frame_box() -> tuple[float, float, float, float, float]:
    """Projected bounds of the lon/lat frame -> (x0, y0, x1, y1, scale to WIDTH)."""
    w, s, e, n = FRAME
    pts = [project(w + (e - w) * i / 50, lat) for i in range(51) for lat in (s, n)]
    pts += [project(lon, s + (n - s) * i / 50) for i in range(51) for lon in (w, e)]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    return x0, y0, x1, y1, WIDTH / (x1 - x0)


def decode_arcs(topo: dict, to_svg) -> list[list[tuple[float, float]]]:
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            pts.append(to_svg(*project(x * sx + tx, y * sy + ty)))
        arcs.append(simplify(pts, SIMPLIFY))
    return arcs


def simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative; keeps both ends (shared arc endpoints stay put)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        best, at = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = (
                abs(dy * (px - ax) - dx * (py - ay)) / norm
                if (dx or dy)
                else math.hypot(px - ax, py - ay)
            )
            if d > best:
                best, at = d, i
        if best > tol and at > 0:
            keep[at] = True
            stack += [(a, at), (at, b)]
    return [p for p, k in zip(pts, keep, strict=True) if k]


def ring(arcs: list, refs: list[int]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for ref in refs:
        pts = arcs[ref] if ref >= 0 else arcs[~ref][::-1]
        out.extend(pts if not out else pts[1:])
    return out


def polygons(geom: dict, arcs: list) -> list[list[list[tuple[float, float]]]]:
    if geom["type"] == "Polygon":
        return [[ring(arcs, r) for r in geom["arcs"]]]
    if geom["type"] == "MultiPolygon":
        return [[ring(arcs, r) for r in poly] for poly in geom["arcs"]]
    return []


def clip(points: list[tuple[float, float]], box: tuple[float, float, float, float]):
    """Sutherland-Hodgman against an axis-aligned box (fills only: edges on the box are fine)."""
    x0, y0, x1, y1 = box
    edges = [
        (lambda p: p[0] >= x0, lambda a, b: _at_x(a, b, x0)),
        (lambda p: p[0] <= x1, lambda a, b: _at_x(a, b, x1)),
        (lambda p: p[1] >= y0, lambda a, b: _at_y(a, b, y0)),
        (lambda p: p[1] <= y1, lambda a, b: _at_y(a, b, y1)),
    ]
    for inside, cross in edges:
        if not points:
            break
        src, points = points, []
        prev = src[-1]
        for cur in src:
            if inside(cur):
                if not inside(prev):
                    points.append(cross(prev, cur))
                points.append(cur)
            elif inside(prev):
                points.append(cross(prev, cur))
            prev = cur
    return points


def _at_x(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return (x, a[1] + t * (b[1] - a[1]))


def _at_y(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), y)


def area(r: list[tuple[float, float]]) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1], strict=True))


def inside(pt, rings) -> bool:
    x, y = pt
    hit = False
    for r in rings:
        for (ax, ay), (bx, by) in zip(r, r[1:] + r[:1], strict=True):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                hit = not hit
    return hit


def edge_distance(pt, rings) -> float:
    x, y = pt
    best = math.inf
    for r in rings:
        for (ax, ay), (bx, by) in zip(r, r[1:] + r[:1], strict=True):
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1e-12)))
            best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


def label_point(rings) -> tuple[float, float, float]:
    """(x, y, r): a point far from the edges of the polygon and that distance (coarse search)."""
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    best = (sum(xs) / len(xs), sum(ys) / len(ys), 0.0)
    span = (min(xs), min(ys), max(xs), max(ys))
    for steps in (24, 12, 12):
        x0, y0, x1, y1 = span
        for i in range(steps + 1):
            for j in range(steps + 1):
                pt = (x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * j / steps)
                if inside(pt, rings):
                    d = edge_distance(pt, rings)
                    if d > best[2]:
                        best = (pt[0], pt[1], d)
        w, h = (x1 - x0) / steps * 2, (y1 - y0) / steps * 2
        span = (best[0] - w, best[1] - h, best[0] + w, best[1] + h)
    return best


def in_crimea(r: list[tuple[float, float]], from_svg) -> bool:
    """The polygon's mean point, back in lon/lat, lies in the Crimea box."""
    mx = sum(p[0] for p in r) / len(r)
    my = sum(p[1] for p in r) / len(r)
    lon, lat = unproject(*from_svg(mx, my))
    w, s, e, n = CRIMEA
    return w <= lon <= e and s <= lat <= n


def unproject(x: float, y: float) -> tuple[float, float]:
    """Inverse of project() (spherical Lambert azimuthal equal-area)."""
    y = -y
    rho = math.hypot(x, y)
    if rho < 1e-12:
        return LON0, LAT0
    c = 2 * math.asin(min(1.0, rho / 2))
    phi0 = math.radians(LAT0)
    lat = math.asin(math.cos(c) * math.sin(phi0) + y * math.sin(c) * math.cos(phi0) / rho)
    lon = math.radians(LON0) + math.atan2(
        x * math.sin(c), rho * math.cos(phi0) * math.cos(c) - y * math.sin(phi0) * math.sin(c)
    )
    return math.degrees(lon), math.degrees(lat)


def path(polys) -> str:
    out = []
    for rings in polys:
        for r in rings:
            pts = [f"{x:.1f},{y:.1f}" for x, y in r]
            dedup = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
            if len(dedup) >= 3:
                out.append("M" + "L".join(dedup) + "Z")
    return "".join(out)


def main(src: Path) -> None:
    topo = json.loads(src.read_text(encoding="utf-8"))
    x0, y0, x1, y1, scale = frame_box()

    def to_svg(x: float, y: float) -> tuple[float, float]:
        return (x - x0) * scale, (y - y0) * scale

    def from_svg(x: float, y: float) -> tuple[float, float]:
        return x / scale + x0, y / scale + y0

    width, height = WIDTH, (y1 - y0) * scale
    box = (-MARGIN, -MARGIN, width + MARGIN, height + MARGIN)
    arcs = decode_arcs(topo, to_svg)

    shapes: dict[str, list] = {}
    other = []
    for geom in topo["objects"]["countries"]["geometries"]:
        code = MONITORED.get(geom.get("id")) or CONTEXT.get(geom.get("id"))
        code = code or BY_NAME.get(geom["properties"]["name"])
        clipped = []
        for poly in polygons(geom, arcs):
            rings = [clip(r, box) for r in poly]
            if rings and len(rings[0]) >= 3 and abs(area(rings[0])) > 0.05:
                clipped.append([r for r in rings if len(r) >= 3])
        if not clipped:
            continue
        if code == "RU":
            crimea = [p for p in clipped if in_crimea(p[0], from_svg)]
            if len(crimea) != 1:
                sys.exit(f"expected Crimea as one polygon of Russia, found {len(crimea)}")
            shapes.setdefault("UA", []).extend(crimea)
            clipped = [p for p in clipped if p is not crimea[0]]
        if code:
            shapes.setdefault(code, []).extend(clipped)
        else:
            other.extend(clipped)

    missing = set(MONITORED.values()) | set(CONTEXT.values()) | {"XK"}
    missing -= set(shapes)
    if missing:
        sys.exit(f"missing countries: {sorted(missing)}")

    labels = {}
    for code, polys in shapes.items():
        if code in LABEL_AT:
            pt = to_svg(*project(*LABEL_AT[code]))
            home = next((p for p in polys if inside(pt, p)), None)
            if home is None:
                sys.exit(f"label point of {code} is outside the country")
            labels[code] = [round(pt[0], 1), round(pt[1], 1), round(edge_distance(pt, home), 1)]
            continue
        biggest = max(polys, key=lambda p: abs(area(p[0])))
        x, y, r = label_point(biggest)
        labels[code] = [round(x, 1), round(y, 1), round(r, 1)]

    data = {
        "source": "Natural Earth 1:50m (public domain) via world-atlas 2.0.2",
        "viewBox": f"0 0 {width:.0f} {height:.0f}",
        "countries": {c: path(shapes[c]) for c in sorted(shapes) if c not in CONTEXT.values()},
        "context": {c: path(shapes[c]) for c in sorted(CONTEXT.values())},
        "other": path(other),
        "labels": dict(sorted(labels.items())),
    }
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT}: {OUT.stat().st_size // 1024} KB, {len(data['countries'])} countries")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
