"""Offline tests: external services are replaced by small fakes so the whole pipeline can be checked without internet."""
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from fastapi.testclient import TestClient

from backend import airquality, db, main, osm, providers, safety, tinyfish
from backend.geo import decode_polyline, haversine, resample, solar_elevation

A, B = (28.6129, 77.2295), (28.6315, 77.2167)


def fake_route(offset):
    pts = [(A[0] + (B[0] - A[0]) * t + offset * math.sin(math.pi * t), A[1] + (B[1] - A[1]) * t + offset * 0.8 * math.sin(math.pi * t))
           for t in [i / 40 for i in range(41)]]
    d = sum(haversine(pts[i - 1], pts[i]) for i in range(1, len(pts)))
    return {"pts": pts, "distance_m": d, "duration_s": d / 1.35, "static_duration_s": d / 1.35, "summary": "", "source": "osrm"}


def fake_elements():
    els = []
    # a busy, lit corridor along route B (offset +0.004) and nothing near route C
    for i in range(30):
        t = i / 29
        lat = A[0] + (B[0] - A[0]) * t + 0.004 * math.sin(math.pi * t)
        lng = A[1] + (B[1] - A[1]) * t + 0.0032 * math.sin(math.pi * t)
        els.append({"type": "node", "lat": lat, "lon": lng, "tags": {"highway": "street_lamp"}})
        els.append({"type": "node", "lat": lat + 0.0003, "lon": lng, "tags": {"amenity": "restaurant", "name": f"R{i}"}})
    els.append({"type": "node", "lat": 28.622, "lon": 77.224, "tags": {"amenity": "police", "name": "Test Police Station"}})
    els.append({"type": "way", "center": {"lat": 28.625, "lon": 77.214}, "tags": {"landuse": "industrial"}})
    return els


def fake_air(cells):
    base = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
    times = [base + timedelta(hours=i) for i in range(72)]
    return {c: {"offset": 19800.0, "times": times, "pm25": [80 + 30 * math.sin(i / 4) for i in range(72)], "pm10": [], "aqi": []} for c in cells}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))

    async def get_routes(client, o, d, mode, depart, gkey):
        return [fake_route(0.0004), fake_route(0.004), fake_route(-0.004)], []

    async def fetch_osm(client, box):
        return fake_elements()

    async def fetch_air(client, cells):
        return fake_air(cells)

    async def fetch_weather(client, lat, lng):
        return {"temp_c": 27, "wind_kmh": 6, "rain_mm": 0, "code": 1}

    async def live_intel(client, key, areas):
        return {"items": [{"title": "Test", "snippet": "", "url": "https://x", "source": "x", "category": "safety", "severity": 2}], "advisory_penalty": 0.015, "queries": areas}

    monkeypatch.setattr(providers, "get_routes", get_routes)
    monkeypatch.setattr(osm, "fetch_osm", fetch_osm)
    monkeypatch.setattr(airquality, "fetch_air", fetch_air)
    monkeypatch.setattr(airquality, "fetch_weather", fetch_weather)
    monkeypatch.setattr(tinyfish, "live_intel", live_intel)
    main._cache.clear()
    with TestClient(main.app) as c:
        yield c


def body(**kw):
    b = {"origin": {"lat": A[0], "lng": A[1], "label": "India Gate, New Delhi, Delhi, India"},
         "destination": {"lat": B[0], "lng": B[1], "label": "Connaught Place, New Delhi, Delhi, India"}, "mode": "walk",
         "depart_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}
    b.update(kw)
    return b


def test_geo_basics():
    assert abs(haversine((0, 0), (0, 1)) - 111195) < 300
    assert decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")[0] == (38.5, -120.2)
    assert len(resample([A, B], 100)) > 10
    noon = datetime(2026, 10, 14, 6, 30, tzinfo=timezone.utc)
    assert solar_elevation(28.6, 77.2, noon) > 45


def test_safety_is_worse_at_night_and_when_unlit():
    f_good = {"lamps": 5, "late": 6, "day": 2, "help_d": 150, "remote": False, "remote_soft": False, "construction": False}
    f_bad = {"lamps": 0, "late": 0, "day": 0, "help_d": 2500, "remote": True, "remote_soft": False, "construction": False}
    assert safety.safety_risk(f_bad, 1)[0] > safety.safety_risk(f_good, 1)[0] + 40
    assert safety.safety_risk(f_bad, 1)[0] > safety.safety_risk(f_bad, 0)[0]
    assert safety.safety_risk(f_good, 1)[0] < 15


def test_pm_scale_is_monotonic():
    vals = [safety.pm_to_risk(x) for x in (0, 10, 30, 60, 120, 200, 400)]
    assert vals == sorted(vals) and vals[0] == 0 and vals[-1] == 100


def test_analyze_end_to_end(client):
    r = client.post("/api/analyze", json=body())
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["routes"]) == 3 and j["recommended"] in "ABC"
    for rt in j["routes"]:
        assert 0 <= rt["scores"]["combined"] <= 100 and len(rt["profile"]) > 3 and rt["polyline"]
    best = next(x for x in j["routes"] if x["id"] == j["recommended"])
    assert best["scores"]["combined"] == min(x["scores"]["combined"] for x in j["routes"])
    assert j["why"] and j["best_time"]["series"] and len(j["best_time"]["series"]) == 13
    assert any(s["name"] == "TinyFish intel" for s in j["status"])


def test_lit_busy_route_wins_at_night(client):
    night = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc).isoformat()   # 23:30 IST
    j = client.post("/api/analyze", json=body(depart_at=night, weights={"safety": 90, "pollution": 5, "time": 5})).json()
    # depart_at in the past is clamped to "now"; so recompute directly with the engine instead for a deterministic check
    routes = [fake_route(0.0004), fake_route(0.004), fake_route(-0.004)]
    for i, r in enumerate(routes):
        r["id"] = "ABC"[i]
        r["name"] = "Route " + r["id"]
    idx = osm.build_index(fake_elements(), A[0])
    depart = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)
    safety.analyze_routes(routes, depart, idx, fake_air([airquality.cell_key(28.62, 77.22)]), [], "walk", {"safety": 90, "pollution": 5, "time": 5})
    rid, conf, why = safety.explain(routes, {"safety": 90, "pollution": 5, "time": 5})
    assert rid == "B" and 40 <= conf <= 96 and any("lighting" in w["text"] or "safety" in w["text"].lower() for w in why)


def test_validation(client):
    assert client.post("/api/analyze", json=body(destination={"lat": A[0], "lng": A[1]})).status_code == 422
    assert client.post("/api/analyze", json=body(destination={"lat": 40.7, "lng": -74.0})).status_code == 422
    assert client.post("/api/analyze", json=body(mode="rocket")).status_code == 422


def test_reports_affect_scores_and_listing(client):
    base = client.post("/api/analyze", json=body()).json()
    mid = base["routes"][0]["profile"][len(base["routes"][0]["profile"]) // 2]
    for _ in range(4):
        assert client.post("/api/reports", json={"lat": mid["lat"], "lng": mid["lng"], "category": "harassment", "severity": 3, "note": "x"}).status_code == 200
    again = client.post("/api/analyze", json=body()).json()
    assert again["routes"][0]["scores"]["safety"] > base["routes"][0]["scores"]["safety"]
    got = client.get("/api/reports", params={"south": 28.5, "west": 77.1, "north": 28.7, "east": 77.3}).json()
    assert len(got["reports"]) == 4


def test_trip_sharing_and_sos(client):
    tid = client.post("/api/trips", json={"name": "Asha", "route": {"polyline": [[1, 2]]}}).json()["id"]
    assert client.post(f"/api/trips/{tid}/ping", json={"lat": 28.6, "lng": 77.2}).status_code == 200
    t = client.get(f"/api/trips/{tid}").json()
    assert t["last_lat"] == 28.6 and t["route"]["polyline"] == [[1, 2]]
    assert client.get("/api/trips/nope").status_code == 404
    s = client.post("/api/sos", json={"name": "Asha", "lat": 28.6, "lng": 77.2, "reason": "Manual SOS", "risk": 81, "contacts": [{"name": "Mom", "phone": "+910000000000"}]}).json()
    assert "maps.google.com" in s["summary"] and s["sms_sent"] == []
    a = client.get("/api/analytics").json()
    assert a["totals"]["sos"] == 1 and a["totals"]["shared_trips"] == 1


def test_tinyfish_classifier():
    assert tinyfish.classify("Woman molested near metro station, police arrest accused")[0] == "safety"
    assert tinyfish.classify("Road closure and diversion near Ring Road after waterlogging")[0] == "road"
    assert tinyfish.classify("Delhi AQI turns very poor, GRAP stage 3 imposed")[0] == "air"
    assert tinyfish.area_queries(["Connaught Place, New Delhi, Delhi, India"]) == ["Connaught Place New Delhi"]


def test_diagnostics_without_keys(client, monkeypatch):
    async def ok(*a, **k):
        return {(28.6, 77.2): {"times": [1], "pm25": [], "pm10": [], "aqi": [], "offset": 0}}
    monkeypatch.setattr(airquality, "fetch_air", ok)
    async def ov(*a, **k): return []
    monkeypatch.setattr(osm, "fetch_osm", ov)
    async def osrm(*a, **k): return [1]
    monkeypatch.setattr(providers, "_osrm_route", osrm)
    r = client.get("/api/diagnostics").json()
    assert {c["name"] for c in r["checks"]} >= {"TinyFish Search API", "Google Routes API"}
