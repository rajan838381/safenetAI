"""Maps providers: place search, reverse geocoding and routing.

Uses Google Maps Platform when a key is available, otherwise free OpenStreetMap services
(Photon / Nominatim for search, OSRM for routes). Every function degrades gracefully.
"""
from __future__ import annotations
import math
import re
from datetime import datetime, timezone
import httpx
from . import config
from .geo import (bearing, decode_polyline, haversine, offset_point, path_length)

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_AC_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACES_URL = "https://places.googleapis.com/v1/places/"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM = "https://nominatim.openstreetmap.org"
OSRM = {"walk": "https://routing.openstreetmap.de/routed-foot/route/v1/driving/",
        "cycle": "https://routing.openstreetmap.de/routed-bike/route/v1/driving/",
        "scooter": "https://router.project-osrm.org/route/v1/driving/",
        "drive": "https://router.project-osrm.org/route/v1/driving/"}
GOOGLE_MODE = {"walk": "WALK", "cycle": "BICYCLE", "scooter": "TWO_WHEELER", "drive": "DRIVE"}


class ProviderError(Exception):
    pass


# ------------------------------------------------------------------ search
async def suggest(client: httpx.AsyncClient, q: str, lat: float | None, lng: float | None, gkey: str) -> list[dict]:
    q = q.strip()
    if len(q) < 2:
        return []
    if gkey:
        try:
            body: dict = {"input": q}
            if lat is not None and lng is not None:
                body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 50000.0}}
            r = await client.post(PLACES_AC_URL, json=body, headers={"X-Goog-Api-Key": gkey})
            r.raise_for_status()
            out = []
            for s in r.json().get("suggestions", []):
                p = s.get("placePrediction")
                if p:
                    out.append({"label": p["text"]["text"], "place_id": p["placeId"], "source": "google"})
            if out:
                return out[:6]
        except Exception:
            pass  # fall through to free providers
    try:
        params = {"q": q, "limit": "6"}
        if lat is not None and lng is not None:
            params.update(lat=str(lat), lon=str(lng))
        r = await client.get(PHOTON_URL, params=params, headers={"User-Agent": config.user_agent()})
        r.raise_for_status()
        out = []
        for f in r.json().get("features", []):
            pr, (lo, la) = f.get("properties", {}), f["geometry"]["coordinates"]
            bits = [pr.get("name"), pr.get("street"), pr.get("district") or pr.get("suburb"), pr.get("city") or pr.get("county"),
                    pr.get("state"), pr.get("country")]
            label = ", ".join(dict.fromkeys(b for b in bits if b))
            if label:
                out.append({"label": label, "lat": la, "lng": lo, "source": "photon"})
        if out:
            return out
    except Exception:
        pass
    r = await client.get(f"{NOMINATIM}/search", params={"q": q, "format": "jsonv2", "limit": "6"},
                         headers={"User-Agent": config.user_agent()})
    r.raise_for_status()
    return [{"label": x["display_name"], "lat": float(x["lat"]), "lng": float(x["lon"]), "source": "nominatim"} for x in r.json()]


async def place_details(client: httpx.AsyncClient, place_id: str, gkey: str) -> dict:
    if not gkey:
        raise ProviderError("Google key missing")
    r = await client.get(PLACES_URL + place_id, headers={"X-Goog-Api-Key": gkey,
                         "X-Goog-FieldMask": "location,displayName,formattedAddress"})
    r.raise_for_status()
    j = r.json()
    loc = j["location"]
    label = j.get("formattedAddress") or j.get("displayName", {}).get("text", "")
    name = j.get("displayName", {}).get("text", "")
    return {"label": f"{name}, {label}" if name and name not in label else label, "lat": loc["latitude"], "lng": loc["longitude"]}


async def reverse(client: httpx.AsyncClient, lat: float, lng: float, gkey: str) -> str:
    if gkey:
        try:
            r = await client.get(GEOCODE_URL, params={"latlng": f"{lat},{lng}", "key": gkey})
            res = r.json().get("results") or []
            if res:
                return res[0]["formatted_address"]
        except Exception:
            pass
    try:
        r = await client.get(f"{NOMINATIM}/reverse", params={"lat": lat, "lon": lng, "format": "jsonv2"},
                             headers={"User-Agent": config.user_agent()})
        return r.json().get("display_name") or f"{lat:.5f}, {lng:.5f}"
    except Exception:
        return f"{lat:.5f}, {lng:.5f}"


# ------------------------------------------------------------------ routing
def _parse_secs(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"([\d.]+)s", str(v or ""))
    return float(m.group(1)) if m else 0.0


async def _google_route(client, o, d, mode, depart, gkey, via=None, alternatives=True) -> list[dict]:
    def wp(p):
        return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}
    body = {"origin": wp(o), "destination": wp(d), "travelMode": GOOGLE_MODE[mode], "languageCode": "en-US", "units": "METRIC"}
    if via:
        body["intermediates"] = [{**wp(via), "via": True}]
    elif alternatives:
        body["computeAlternativeRoutes"] = True
    if mode in ("drive", "scooter"):
        body["routingPreference"] = "TRAFFIC_AWARE"
    if depart and depart > datetime.now(timezone.utc) and mode in ("drive", "scooter"):
        body["departureTime"] = depart.strftime("%Y-%m-%dT%H:%M:%SZ")
    mask = "routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.description"
    r = await client.post(ROUTES_URL, json=body, headers={"X-Goog-Api-Key": gkey, "X-Goog-FieldMask": mask})
    if r.status_code >= 400:
        raise ProviderError(f"Google Routes API {r.status_code}: {r.text[:200]}")
    out = []
    for rt in r.json().get("routes", []):
        pts = decode_polyline(rt["polyline"]["encodedPolyline"])
        dur = _parse_secs(rt.get("duration")); st = _parse_secs(rt.get("staticDuration")) or dur
        out.append({"pts": pts, "distance_m": float(rt.get("distanceMeters") or path_length(pts)), "duration_s": dur,
                    "static_duration_s": st, "summary": rt.get("description", ""), "source": "google"})
    return out


async def _osrm_route(client, o, d, mode, via=None, alternatives=True) -> list[dict]:
    coords = [o] + ([via] if via else []) + [d]
    path = ";".join(f"{p[1]:.6f},{p[0]:.6f}" for p in coords)
    params = {"overview": "full", "geometries": "geojson", "alternatives": "true" if alternatives and not via else "false"}
    r = await client.get(OSRM[mode] + path, params=params, headers={"User-Agent": config.user_agent()})
    if r.status_code >= 400:
        raise ProviderError(f"OSRM {r.status_code}")
    out = []
    for rt in r.json().get("routes", []):
        pts = [(c[1], c[0]) for c in rt["geometry"]["coordinates"]]
        dist = float(rt["distance"])
        dur = float(rt["duration"])
        if mode == "walk":
            dur = dist / 1.35          # the public foot server reports driving-like times
        elif mode == "cycle":
            dur = dist / 4.2
        elif mode == "scooter":
            dur = dist / 8.0 + 0
        out.append({"pts": pts, "distance_m": dist, "duration_s": dur, "static_duration_s": dur, "summary": "", "source": "osrm"})
    return out


def _similar(a: list, b: list, tol: float = 60.0) -> bool:
    """Two routes are 'the same' when 9 evenly spaced points on a are all within tol metres of route b."""
    for k in range(1, 10):
        p = a[int(len(a) * k / 10)]
        if min(haversine(p, q) for q in b[:: max(1, len(b) // 120)]) > tol:
            return False
    return True


async def get_routes(client: httpx.AsyncClient, o, d, mode: str, depart: datetime | None, gkey: str) -> tuple[list[dict], list[str]]:
    """Return up to 3 distinct routes plus data-quality notes."""
    notes: list[str] = []
    routes: list[dict] = []
    use_google = bool(gkey)

    async def fetch(via=None, alternatives=True):
        nonlocal use_google
        if use_google:
            try:
                return await _google_route(client, o, d, mode, depart, gkey, via, alternatives)
            except Exception as e:  # key missing API, quota, mode not supported here...
                notes.append(f"Google routing unavailable ({str(e)[:90]}). Using OpenStreetMap routing instead.")
                use_google = False
        return await _osrm_route(client, o, d, mode, via, alternatives)

    try:
        routes = await fetch()
    except httpx.TransportError:
        raise ProviderError("Could not reach the routing service. Check your internet connection and try again.")
    except Exception as e:
        raise ProviderError(f"Could not find a route between these places: {e}")
    if not routes:
        raise ProviderError("No route found between these two places for this travel mode.")

    # Fewer than 3 alternatives? Ask for routes via side waypoints so the user always gets a real choice.
    if len(routes) < 3:
        base = routes[0]["pts"]
        mid = base[len(base) // 2]
        brg = bearing(o, d)
        dist = haversine(o, d)
        off = min(max(dist * 0.22, 350.0), 4000.0)
        for sign in (+1, -1):
            if len(routes) >= 3:
                break
            via = offset_point(mid[0], mid[1], brg + 90 * sign, off)
            try:
                for cand in await fetch(via=via, alternatives=False):
                    if not any(_similar(cand["pts"], r["pts"]) for r in routes) and cand["distance_m"] < routes[0]["distance_m"] * 1.9:
                        routes.append(cand)
                        break
            except Exception:
                continue
    # de-duplicate and cap
    uniq: list[dict] = []
    for r in routes:
        if not any(_similar(r["pts"], u["pts"]) for u in uniq):
            uniq.append(r)
    if len(uniq) == 1:
        notes.append("Only one distinct route exists between these places, so there is nothing to compare.")
    return uniq[:3], notes
