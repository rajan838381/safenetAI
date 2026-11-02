"""Geometry helpers: distances, polylines, resampling, sun position."""
from __future__ import annotations
import math
from datetime import datetime, timezone

R_EARTH = 6371000.0


def clamp(v: float, a: float = 0.0, b: float = 1.0) -> float:
    return a if v < a else b if v > b else v


def smooth(a: float, b: float, x: float) -> float:
    t = clamp((x - a) / (b - a))
    return t * t * (3 - 2 * t)


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance in metres between (lat, lng) pairs."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(h))


def decode_polyline(s: str, precision: int = 5) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline into [(lat, lng), ...]."""
    f = 10 ** precision
    out, i, lat, lng = [], 0, 0, 0
    while i < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63; i += 1
                result |= (b & 0x1F) << shift; shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if which == 0: lat += d
            else: lng += d
        out.append((lat / f, lng / f))
    return out


def path_length(pts: list[tuple[float, float]]) -> float:
    return sum(haversine(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def resample(pts: list[tuple[float, float]], spacing: float) -> list[dict]:
    """Points every `spacing` metres along the path, each with cumulative distance `d` (m)."""
    if len(pts) < 2:
        return [{"lat": pts[0][0], "lng": pts[0][1], "d": 0.0}] if pts else []
    out = [{"lat": pts[0][0], "lng": pts[0][1], "d": 0.0}]
    total, next_at = 0.0, spacing
    for i in range(1, len(pts)):
        seg = haversine(pts[i - 1], pts[i])
        while seg > 0 and total + seg >= next_at:
            t = (next_at - total) / seg
            out.append({"lat": pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t,
                        "lng": pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t, "d": next_at})
            next_at += spacing
        total += seg
    if total - out[-1]["d"] > spacing * 0.3:
        out.append({"lat": pts[-1][0], "lng": pts[-1][1], "d": total})
    return out


def simplify(pts: list[tuple[float, float]], max_points: int = 400) -> list[tuple[float, float]]:
    if len(pts) <= max_points:
        return pts
    step = len(pts) / max_points
    out = [pts[int(i * step)] for i in range(max_points)]
    out.append(pts[-1])
    return out


def bbox(pts: list[tuple[float, float]], pad: float = 0.0) -> tuple[float, float, float, float]:
    la = [p[0] for p in pts]; lo = [p[1] for p in pts]
    return min(la) - pad, min(lo) - pad, max(la) + pad, max(lo) + pad  # south, west, north, east


def offset_point(lat: float, lng: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    return (lat + dist_m * math.cos(b) / 110540.0,
            lng + dist_m * math.sin(b) / (111320.0 * max(0.2, math.cos(math.radians(lat)))))


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, la2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def solar_elevation(lat: float, lng: float, when: datetime) -> float:
    """Sun elevation in degrees (NOAA approximation). `when` must be timezone-aware."""
    t = when.astimezone(timezone.utc)
    n = t.timetuple().tm_yday
    hour = t.hour + t.minute / 60 + t.second / 3600
    g = 2 * math.pi / 365 * (n - 1 + (hour - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hour * 60 + eqt + 4 * lng
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return math.degrees(math.asin(clamp(cz, -1, 1)))


def darkness(lat: float, lng: float, when: datetime) -> float:
    """0 in full daylight, 1 at night, smooth through twilight."""
    return clamp((6 - solar_elevation(lat, lng, when)) / 12)
