"""OpenStreetMap street-level data via the free Overpass API: lamps, open places, help points, remote land."""
from __future__ import annotations
import math
from collections import defaultdict
import httpx

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def build_query(s: float, w: float, n: float, e: float) -> str:
    bb = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    return f"""[out:json][timeout:25];
(
 node["highway"="street_lamp"]{bb};
 node["amenity"~"^(police|hospital|clinic|fire_station|pharmacy|restaurant|cafe|fast_food|bar|pub|fuel|cinema|atm|bank|marketplace|school|college|university)$"]{bb};
 node["shop"~"^(convenience|supermarket|mall|department_store)$"]{bb};
 node["highway"="bus_stop"]{bb};
 way["amenity"~"^(police|hospital|clinic)$"]{bb};
 way["landuse"~"^(industrial|construction|quarry|landfill|cemetery|forest)$"]{bb};
 way["natural"~"^(wood|scrub)$"]{bb};
 way["leisure"~"^(park|nature_reserve)$"]{bb};
);
out center 6000;"""


async def fetch_osm(client: httpx.AsyncClient, box: tuple[float, float, float, float]) -> list[dict]:
    q = build_query(*box)
    last: Exception | None = None
    for url in OVERPASS:
        try:
            r = await client.post(url, data={"data": q}, timeout=40)
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as e:
            last = e
    raise RuntimeError(f"Overpass unavailable: {last}")


def classify(tags: dict) -> list[str]:
    k: list[str] = []
    a, s, lu = tags.get("amenity"), tags.get("shop"), tags.get("landuse")
    if tags.get("highway") == "street_lamp":
        k.append("lamp")
    if a == "police":
        k += ["help", "late", "police"]
    elif a == "hospital":
        k += ["help", "late", "hospital"]
    elif a == "fire_station":
        k.append("help")
    elif a in ("pharmacy", "restaurant", "cafe", "fast_food", "bar", "pub", "fuel", "cinema"):
        k.append("late")
        if a in ("pharmacy", "fuel"):
            k.append(a)
    elif a in ("clinic", "atm", "bank", "marketplace", "school", "college", "university"):
        k.append("day")
    if s in ("convenience", "supermarket"):
        k.append("late")
    elif s:
        k.append("day")
    if tags.get("highway") == "bus_stop":
        k.append("day")
    if lu == "construction":
        k.append("construction")
    elif lu in ("industrial", "quarry", "landfill", "cemetery", "forest"):
        k.append("remote")
    if tags.get("natural") in ("wood", "scrub") or tags.get("leisure") in ("park", "nature_reserve"):
        k.append("remote_soft")
    return k


class Index:
    """Tiny spatial hash so counting 'things within 150 m' of 40 sample points stays fast."""

    def __init__(self, lat0: float, cell: float = 120.0):
        self.kx = 111320.0 * max(0.2, math.cos(math.radians(lat0)))
        self.ky = 110540.0
        self.cell = cell
        self.b: dict[tuple, list] = defaultdict(list)
        self.size = 0

    def xy(self, lat: float, lng: float):
        return lng * self.kx, lat * self.ky

    def add(self, kind: str, lat: float, lng: float, meta: dict | None = None):
        x, y = self.xy(lat, lng)
        self.b[(kind, int(x // self.cell), int(y // self.cell))].append((x, y, lat, lng, meta or {}))
        self.size += 1

    def within(self, kind: str, lat: float, lng: float, r: float) -> list:
        x, y = self.xy(lat, lng)
        n = int(r // self.cell) + 1
        cx, cy = int(x // self.cell), int(y // self.cell)
        out = []
        for i in range(cx - n, cx + n + 1):
            for j in range(cy - n, cy + n + 1):
                for it in self.b.get((kind, i, j), ()):
                    if (it[0] - x) ** 2 + (it[1] - y) ** 2 <= r * r:
                        out.append(it)
        return out

    def nearest(self, kind: str, lat: float, lng: float, max_d: float) -> float:
        x, y = self.xy(lat, lng)
        n = int(max_d // self.cell) + 1
        cx, cy = int(x // self.cell), int(y // self.cell)
        best = max_d
        for i in range(cx - n, cx + n + 1):
            for j in range(cy - n, cy + n + 1):
                for it in self.b.get((kind, i, j), ()):
                    d = math.hypot(it[0] - x, it[1] - y)
                    if d < best:
                        best = d
        return best


def build_index(elements: list[dict], lat0: float) -> Index:
    idx = Index(lat0)
    for el in elements:
        tags = el.get("tags") or {}
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lng = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lng is None:
            continue
        for kind in classify(tags):
            idx.add(kind, lat, lng, {"name": tags.get("name", ""), "kind": kind, "hours": tags.get("opening_hours", "")})
    return idx
