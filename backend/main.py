"""VAYORA AI - FastAPI backend. Run:  uvicorn backend.main:app --reload   (from the project folder)."""
from __future__ import annotations
import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, airquality, config, db, notify, osm, providers, safety, tinyfish
from .geo import bbox, haversine, simplify

_cache: dict = {}


async def cached(key, ttl: int, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    val = await fn()
    _cache[key] = (now + ttl, val)
    if len(_cache) > 300:
        for k in [k for k, v in _cache.items() if v[0] < now]:
            _cache.pop(k, None)
    return val


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=25, follow_redirects=True)
    db.conn()
    yield
    await app.state.http.aclose()


app = FastAPI(title="VAYORA AI", version="1.0", description="Safer routes. Cleaner journeys.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def gkey(request: Request) -> str:
    return config.google_server_key(request.headers.get("x-google-key", ""))


def tkey(request: Request) -> str:
    return config.tinyfish_key(request.headers.get("x-tinyfish-key", ""))


# ---------------------------------------------------------------- models
class Pt(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    label: str = ""


class Weights(BaseModel):
    safety: float = Field(50, ge=0, le=100)
    pollution: float = Field(35, ge=0, le=100)
    time: float = Field(15, ge=0, le=100)


class AnalyzeReq(BaseModel):
    origin: Pt
    destination: Pt
    mode: Literal["walk", "cycle", "scooter", "drive"] = "walk"
    depart_at: Optional[str] = None
    weights: Weights = Weights()
    use_intel: bool = True


class ReportReq(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    category: Literal["poor_lighting", "harassment", "unsafe_crowd", "isolated", "road_hazard", "pollution_source", "other"]
    severity: int = Field(2, ge=1, le=3)
    note: str = Field("", max_length=300)


class TripReq(BaseModel):
    name: str = "Traveller"
    route: dict = {}


class PingReq(BaseModel):
    lat: float
    lng: float
    status: str = "active"


class Contact(BaseModel):
    name: str = ""
    phone: str = ""


class SosReq(BaseModel):
    name: str = "Traveller"
    lat: float
    lng: float
    reason: str = "Manual SOS"
    route_label: str = ""
    destination: str = ""
    nearest_safe: str = ""
    risk: Optional[float] = None
    tracking_url: str = ""
    contacts: list[Contact] = []


class IntelReq(BaseModel):
    areas: list[str] = []


class DeepReq(BaseModel):
    url: str


class ExplainReq(BaseModel):
    context: str = Field(max_length=4000)


# ---------------------------------------------------------------- basic
@app.get("/api/config")
async def get_config():
    js = config.google_js_key()
    return {"google_js_key": js, "map_provider": "google" if js else "leaflet",
            "features": {"google_routing": bool(config.env("GOOGLE_MAPS_API_KEY")), "tinyfish": bool(config.env("TINYFISH_API_KEY")),
                         "claude": ai.available(), "sms": notify.available()}}


@app.get("/api/suggest")
async def suggest(request: Request, q: str, lat: float | None = None, lng: float | None = None):
    try:
        return {"results": await providers.suggest(http(request), q, lat, lng, gkey(request))}
    except Exception as e:
        raise HTTPException(502, f"Place search failed: {e}")


@app.get("/api/place")
async def place(request: Request, id: str):
    try:
        return await providers.place_details(http(request), id, gkey(request))
    except Exception as e:
        raise HTTPException(502, f"Could not load that place: {e}")


@app.get("/api/reverse")
async def reverse(request: Request, lat: float, lng: float):
    return {"label": await providers.reverse(http(request), lat, lng, gkey(request))}


# ---------------------------------------------------------------- analysis
def _parse_depart(s: Optional[str]) -> datetime:
    now = datetime.now(timezone.utc)
    if not s:
        return now
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d if d > now - timedelta(minutes=5) else now
    except ValueError:
        raise HTTPException(422, "depart_at must be an ISO date-time")


@app.post("/api/analyze")
async def analyze(req: AnalyzeReq, request: Request):
    client = http(request)
    o, d = (req.origin.lat, req.origin.lng), (req.destination.lat, req.destination.lng)
    dist = haversine(o, d)
    if dist < 80:
        raise HTTPException(422, "Start and destination are too close together. Pick two different places.")
    if dist > 60000:
        raise HTTPException(422, "This journey is longer than 60 km. VAYORA analyses journeys up to 60 km.")
    depart = _parse_depart(req.depart_at)
    w = req.weights.model_dump()
    status: list[dict] = []

    try:
        routes, rnotes = await providers.get_routes(client, o, d, req.mode, depart, gkey(request))
    except providers.ProviderError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"Routing service failed: {e}")
    for i, r in enumerate(routes):
        r["id"] = "ABC"[i]
        r["name"] = f"Route {r['id']}" + (f" via {r['summary']}" if r.get("summary") else "")
    status.append({"name": "Routing", "ok": True, "text": ("Google Maps Routes API" if routes[0]["source"] == "google" else "OpenStreetMap routing (OSRM)")})
    for n in rnotes:
        status.append({"name": "Routing", "ok": False, "text": n})

    allpts = [p for r in routes for p in r["pts"]]
    box = bbox(allpts, 0.002)
    span = max(box[2] - box[0], box[3] - box[1])
    mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    cells = list(dict.fromkeys(airquality.cell_key(p[0], p[1]) for p in allpts[:: max(1, len(allpts) // 60)]))
    areas = [a for a in (req.origin.label, req.destination.label) if a]
    key_t = tkey(request)

    async def get_osm():
        if span > 0.3:
            return None
        return await cached(("osm", tuple(round(x, 3) for x in box)), 1800, lambda: osm.fetch_osm(client, box))

    async def get_air():
        return await cached(("air", tuple(cells)), 900, lambda: airquality.fetch_air(client, cells))

    async def get_wx():
        return await cached(("wx", round(mid[0], 2), round(mid[1], 2)), 900, lambda: airquality.fetch_weather(client, mid[0], mid[1]))

    async def get_intel():
        if not (req.use_intel and key_t and areas):
            return None
        return await cached(("intel", tuple(areas)), 900, lambda: tinyfish.live_intel(client, key_t, areas))

    elements, air, wx, intel = await asyncio.gather(get_osm(), get_air(), get_wx(), get_intel(), return_exceptions=True)
    idx = None
    if isinstance(elements, Exception):
        status.append({"name": "Street data", "ok": False, "text": f"OpenStreetMap (Overpass) unavailable: {str(elements)[:90]}. Using neutral street assumptions."})
    elif elements is None:
        status.append({"name": "Street data", "ok": False, "text": "Route area too large for a street scan. Using neutral street assumptions."})
    else:
        idx = osm.build_index(elements, mid[0])
        status.append({"name": "Street data", "ok": True, "text": f"OpenStreetMap: {idx.size} street features (lamps, open places, police, hospitals) scanned"})
    if isinstance(air, Exception):
        status.append({"name": "Air quality", "ok": False, "text": f"Open-Meteo air quality unavailable: {str(air)[:90]}. Pollution uses a neutral estimate."})
        air = {}
    else:
        status.append({"name": "Air quality", "ok": True, "text": f"Open-Meteo PM2.5 forecast for {len(air)} area(s)"})
    wx = None if isinstance(wx, Exception) else wx
    advisory, intel_out = 0.0, None
    if isinstance(intel, Exception):
        status.append({"name": "TinyFish intel", "ok": False, "text": str(intel)[:140]})
    elif intel is None:
        status.append({"name": "TinyFish intel", "ok": False, "text": "Not used (no TinyFish key set, or switched off)."})
    else:
        advisory, intel_out = intel["advisory_penalty"], intel
        status.append({"name": "TinyFish intel", "ok": True, "text": f"TinyFish Search found {len(intel['items'])} relevant local update(s)"})
    reports = db.reports_in(*box)
    status.append({"name": "Community", "ok": True, "text": f"{len(reports)} community report(s) near this route (last 45 days)"})

    series = safety.analyze_routes(routes, depart, idx, air, reports, req.mode, w, advisory)
    best_id, conf, why = safety.explain(routes, w)
    safest, cleanest, fastest = min(routes, key=lambda r: r["S"]), min(routes, key=lambda r: r["P"]), min(routes, key=lambda r: r["duration_s"])
    out_routes = []
    for r in routes:
        badges = [b for b, c in (("Recommended", r["id"] == best_id), ("Safest", r is safest), ("Cleanest air", r is cleanest), ("Fastest", r is fastest)) if c]
        out_routes.append({
            "id": r["id"], "name": r["name"], "badges": badges, "source": r["source"],
            "distance_m": round(r["distance_m"]), "duration_s": round(r["duration_s"]),
            "scores": {"safety": round(r["S"], 1), "pollution": round(r["P"], 1), "time": round(r["T"], 1), "combined": round(r["combined"], 1)},
            "pm25": None if r["pm25"] is None else round(r["pm25"], 1), "aqi_label": safety.aqi_label(r["pm25"]),
            "stats": r["stats"], "factors": [f for f in r["factors"] if f["points"] > 0.4][:4], "help_near": r["help_near"],
            "safe_points": r["safe_points"], "polyline": [[round(p[0], 5), round(p[1], 5)] for p in simplify(r["pts"], 350)],
            "profile": r["profile"]})
    best_row = min(series, key=lambda s: min(s["routes"].values()))
    now_best = min(series[0]["routes"].values())
    tz = next(iter(air.values()))["offset"] if air else 0
    best_r = next(r for r in routes if r["id"] == best_id)
    local_hour = int(((depart + timedelta(seconds=tz)).hour))
    db.add_journey(req.mode, best_r["distance_m"], best_r["combined"], best_r["S"], best_r["P"], local_hour)
    return {"recommended": best_id, "confidence": conf, "why": why, "routes": out_routes, "weather": wx, "tz_offset_s": tz,
            "depart_at": depart.isoformat(), "mode": req.mode,
            "best_time": {"series": series, "best_offset_h": best_row["offset_h"],
                          "saving": round(max(0.0, now_best - min(best_row["routes"].values())), 1)},
            "intel": intel_out, "status": status}


# ---------------------------------------------------------------- TinyFish
@app.post("/api/intel")
async def intel(req: IntelReq, request: Request):
    try:
        return await tinyfish.live_intel(http(request), tkey(request), req.areas)
    except tinyfish.TinyFishError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"TinyFish request failed: {e}")


@app.post("/api/intel/deep")
async def intel_deep(req: DeepReq, request: Request):
    if not req.url.startswith("http"):
        raise HTTPException(422, "url must start with http")
    try:
        return await tinyfish.agent_run(http(request), tkey(request), req.url, tinyfish.DEEP_GOAL)
    except tinyfish.TinyFishError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"TinyFish agent failed: {e}")


# ---------------------------------------------------------------- community, trips, SOS
@app.post("/api/reports")
async def post_report(r: ReportReq):
    return {"id": db.add_report(r.lat, r.lng, r.category, r.severity, r.note)}


@app.get("/api/reports")
async def get_reports(south: float, west: float, north: float, east: float):
    return {"reports": db.reports_in(south, west, north, east)}


@app.post("/api/trips")
async def create_trip(t: TripReq):
    return {"id": db.new_trip(t.name, t.route)}


@app.post("/api/trips/{tid}/ping")
async def ping(tid: str, p: PingReq):
    if not db.ping_trip(tid, p.lat, p.lng, p.status):
        raise HTTPException(404, "Unknown trip")
    return {"ok": True}


@app.get("/api/trips/{tid}")
async def trip(tid: str):
    t = db.get_trip(tid)
    if not t:
        raise HTTPException(404, "Unknown trip")
    return t


def sos_text(s: SosReq) -> str:
    risk = f" Estimated risk here: {round(s.risk)}/100." if s.risk is not None else ""
    bits = [f"SOS from {s.name}. {s.reason}.", f"Location: https://maps.google.com/?q={s.lat:.6f},{s.lng:.6f}.{risk}"]
    if s.route_label or s.destination:
        bits.append(f"Travelling{(' on ' + s.route_label) if s.route_label else ''}{(' to ' + s.destination) if s.destination else ''}.")
    if s.nearest_safe:
        bits.append(f"Nearest safe point: {s.nearest_safe}.")
    if s.tracking_url:
        bits.append(f"Live trip: {s.tracking_url}")
    return " ".join(bits)


@app.post("/api/sos")
async def sos(s: SosReq, request: Request):
    text = sos_text(s)
    polished = await ai.ask(http(request), "You write urgent, calm, factual SOS messages for people's trusted contacts. Max 60 words. Keep every URL exactly as given. No emojis.", text, 200)
    summary = polished or text
    db.add_sos(s.name, s.lat, s.lng, s.reason, summary)
    sent = []
    if notify.available():
        for c in s.contacts:
            if c.phone:
                try:
                    sent.append(await notify.send_sms(http(request), c.phone, summary))
                except Exception as e:
                    sent.append({"to": c.phone, "ok": False, "error": str(e)[:80]})
    return {"summary": summary, "maps_url": f"https://maps.google.com/?q={s.lat:.6f},{s.lng:.6f}", "sms_sent": sent,
            "sms_enabled": notify.available(), "note": "Also call 112 (India) or your local emergency number."}


@app.post("/api/explain")
async def explain(e: ExplainReq, request: Request):
    txt = await ai.ask(http(request), "You are VAYORA AI, a calm travel-safety assistant. Explain the route comparison below in 3 short sentences a student would understand. Do not invent facts not in the data.", e.context, 300)
    return {"text": txt, "claude": ai.available()}


@app.get("/api/analytics")
async def analytics():
    return db.analytics()


# ---------------------------------------------------------------- diagnostics
async def _timed(name: str, coro):
    t0 = time.time()
    try:
        detail = await coro
        return {"name": name, "ok": True, "ms": round((time.time() - t0) * 1000), "detail": detail or "OK"}
    except Exception as e:
        return {"name": name, "ok": False, "ms": round((time.time() - t0) * 1000), "detail": str(e)[:200]}


@app.get("/api/diagnostics")
async def diagnostics(request: Request):
    c, gk, tk = http(request), gkey(request), tkey(request)
    delhi_a, delhi_b = (28.6129, 77.2295), (28.6315, 77.2167)

    async def t_google_routes():
        if not gk: return "Not configured (using OpenStreetMap routing)"
        r = await providers._google_route(c, delhi_a, delhi_b, "walk", None, gk)
        return f"Routes API OK, {len(r)} route(s)"

    async def t_google_places():
        if not gk: return "Not configured (using Photon / Nominatim search)"
        r = await providers.suggest(c, "India Gate", None, None, gk)
        return f"Places API OK, {len(r)} suggestion(s) from {r[0]['source'] if r else 'none'}"

    async def t_tinyfish():
        if not tk: return "Not configured. Add TINYFISH_API_KEY"
        r = await tinyfish.search(c, tk, "Delhi weather", news=False)
        return f"Search API OK, {len(r)} result(s)"

    async def t_air():
        r = await airquality.fetch_air(c, [(28.6, 77.2)])
        return f"Open-Meteo OK, {len(next(iter(r.values()))['times'])} hourly values"

    async def t_osm():
        r = await osm.fetch_osm(c, (28.6129, 77.2295, 28.6150, 77.2320))
        return f"Overpass OK, {len(r)} elements"

    async def t_osrm():
        r = await providers._osrm_route(c, delhi_a, delhi_b, "walk")
        return f"OSRM OK, {len(r)} route(s)"

    res = await asyncio.gather(_timed("Google Routes API", t_google_routes()), _timed("Google Places API", t_google_places()),
                               _timed("TinyFish Search API", t_tinyfish()), _timed("Open-Meteo air quality", t_air()),
                               _timed("OpenStreetMap Overpass", t_osm()), _timed("OSRM routing", t_osrm()))
    return {"checks": res, "claude": ai.available(), "sms": notify.available()}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
