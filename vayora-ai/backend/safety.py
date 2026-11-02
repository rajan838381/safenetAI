"""VAYORA risk engine.

Safety risk  : explainable weighted model on REAL OpenStreetMap street data (lighting, open places, distance to
               police/hospitals, isolated land), real sun position (darkness), community reports and live advisories.
Pollution    : PM2.5 forecast from Open-Meteo at the exact place and hour you will be there, scaled by travel mode.
Time         : journey duration compared with the fastest option.
Combined     : weighted average of the three (weights are user-adjustable prototype settings, not scientific constants).

The safety weights below are expert-set starting points. Real deployment should calibrate them against verified
incident data; this is stated openly in the app.
"""
from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone

from .airquality import cell_key, value_at
from .geo import clamp, darkness, haversine, resample

MODES = {"walk": {"safety": 1.0, "pollution": 1.0}, "cycle": {"safety": 0.95, "pollution": 1.15},
         "scooter": {"safety": 0.85, "pollution": 0.95}, "drive": {"safety": 0.7, "pollution": 0.45}}
NEUTRAL = {"lamps": 2, "late": 2, "day": 2, "help_d": 1200.0, "remote": False, "remote_soft": False,
           "construction": False, "osm": False}
PM_BREAKS = [(0, 0), (12, 15), (35, 40), (55, 58), (150, 85), (250, 100)]


def pm_to_risk(pm: float) -> float:
    for (x0, y0), (x1, y1) in zip(PM_BREAKS, PM_BREAKS[1:]):
        if pm <= x1:
            return y0 + (y1 - y0) * (max(pm, x0) - x0) / (x1 - x0)
    return 100.0


def aqi_label(pm: float | None) -> str:
    if pm is None: return "Unknown"
    return ("Good" if pm <= 12 else "Moderate" if pm <= 35 else "Unhealthy for sensitive groups" if pm <= 55
            else "Unhealthy" if pm <= 150 else "Very unhealthy" if pm <= 250 else "Hazardous")


def sample_features(idx, lat: float, lng: float) -> dict:
    if idx is None:
        return dict(NEUTRAL)
    help_d = idx.nearest("help", lat, lng, 3000.0)
    return {"lamps": len(idx.within("lamp", lat, lng, 120)), "late": len(idx.within("late", lat, lng, 200)),
            "day": len(idx.within("day", lat, lng, 200)), "help_d": help_d,
            "remote": bool(idx.within("remote", lat, lng, 150)), "remote_soft": bool(idx.within("remote_soft", lat, lng, 120)),
            "construction": bool(idx.within("construction", lat, lng, 150)), "osm": True}


def safety_risk(f: dict, dark: float, extra: float = 0.0, advisory: float = 0.0) -> tuple[float, dict]:
    lit = clamp(f["lamps"] / 4)
    activity = clamp((f["late"] + f["day"] * 0.5 * (1 - 0.8 * dark)) / 6)
    parts = {
        "Poor street lighting": 0.30 * dark * (1 - lit),
        "Few people or open places nearby": 0.28 * (1 - activity) * (0.45 + 0.55 * dark),
        "Far from police or hospitals": 0.14 * clamp((f["help_d"] - 300) / 1700),
        "Isolated land (industrial, forest, park)": 0.12 * (1.0 if f["remote"] else (0.6 * dark if f["remote_soft"] else 0.0)),
        "Community reports": extra,
        "Live local advisories": advisory,
        "Baseline": 0.04,
    }
    return clamp(sum(parts.values())) * 100, {k: v * 100 for k, v in parts.items()}


def pollution_risk(pm: float | None, construction: bool, mode: str, congestion: float = 0.0) -> float:
    base = pm_to_risk(pm) if pm is not None else 45.0
    base += (8 if construction else 0) + 8 * congestion
    return clamp(base * MODES[mode]["pollution"], 0, 100)


def time_risk(dur_s: float, fastest_s: float) -> float:
    m, f = dur_s / 60, fastest_s / 60
    return clamp(m * 0.9 + (m - f) * 3, 0, 100)


def report_penalty(lat: float, lng: float, reports: list[dict], now: datetime) -> float:
    pen = 0.0
    for r in reports:
        if haversine((lat, lng), (r["lat"], r["lng"])) <= 250:
            age_days = max(0.0, (now.timestamp() - r["created_at"]) / 86400)
            pen += (0.03 + 0.03 * r.get("severity", 1)) * 0.5 ** (age_days / 14)
    return min(pen, 0.15)


def eval_at(samples: list[dict], depart: datetime, duration_s: float, total_m: float, air: dict, mode: str,
            advisory: float, congestion: float) -> list[dict]:
    out = []
    for s in samples:
        eta = depart + timedelta(seconds=duration_s * (s["d"] / total_m if total_m else 0))
        dark = darkness(s["lat"], s["lng"], eta)
        risk, parts = safety_risk(s["f"], dark, s["rep"], advisory)
        a = air.get(s["cell"]) if air else None
        pm = value_at(a, "pm25", eta) if a else None
        out.append({"dark": dark, "S": risk * MODES[mode]["safety"], "P": pollution_risk(pm, s["f"]["construction"], mode, congestion),
                    "pm": pm, "parts": parts})
    return out


def _agg(vals: list[float]) -> float:
    return 0.75 * sum(vals) / len(vals) + 0.25 * max(vals) if vals else 0.0


def combine(S: float, P: float, T: float, w: dict) -> float:
    tot = (w["safety"] + w["pollution"] + w["time"]) or 1
    return (w["safety"] * S + w["pollution"] * P + w["time"] * T) / tot


def analyze_routes(routes: list[dict], depart: datetime, idx, air: dict, reports: list[dict], mode: str,
                   weights: dict, advisory: float = 0.0, hours_ahead: int = 12) -> list[dict]:
    """Score every route. Mutates and returns the route dicts with all scores, profile, stats and factors."""
    fastest = min(r["duration_s"] for r in routes)
    now = datetime.now(timezone.utc)
    for r in routes:
        total = r["distance_m"] or 1
        spacing = max(150.0, total / 36)
        samples = resample(r["pts"], spacing)
        for s in samples:
            s["f"] = sample_features(idx, s["lat"], s["lng"])
            s["cell"] = cell_key(s["lat"], s["lng"])
            s["rep"] = report_penalty(s["lat"], s["lng"], reports, now)
        congestion = clamp((r["duration_s"] / max(r["static_duration_s"], 1) - 1) / 0.6)
        ev = eval_at(samples, depart, r["duration_s"], total, air, mode, advisory, congestion)
        r["_samples"], r["_congestion"] = samples, congestion
        r["S"], r["P"] = _agg([e["S"] for e in ev]), sum(e["P"] for e in ev) / len(ev)
        pms = [e["pm"] for e in ev if e["pm"] is not None]
        r["pm25"] = sum(pms) / len(pms) if pms else None
        r["T"] = time_risk(r["duration_s"], fastest)
        r["_ev"] = ev
        n = len(samples)
        # explainable factors: average points contributed by each safety component
        keys = [k for k in ev[0]["parts"] if k != "Baseline"]
        r["factors"] = sorted(({"name": k, "points": sum(e["parts"][k] for e in ev) / n} for k in keys), key=lambda x: -x["points"])
        r["stats"] = {
            "well_lit_pct": round(100 * sum(s["f"]["lamps"] >= 2 for s in samples) / n),
            "active_pct": round(100 * sum((s["f"]["late"] + s["f"]["day"]) >= 3 for s in samples) / n),
            "avg_help_distance_m": round(sum(s["f"]["help_d"] for s in samples) / n),
            "construction_near": sum(s["f"]["construction"] for s in samples),
            "dark_pct": round(100 * sum(e["dark"] > 0.5 for e in ev) / n),
            "osm_data": bool(idx is not None),
        }
        # longest isolated, dark stretch (metres)
        best = cur = 0.0
        for s, e in zip(samples, ev):
            bad = e["dark"] > 0.5 and (s["f"]["late"] + s["f"]["day"]) < 2 and s["f"]["lamps"] < 2
            cur = cur + spacing if bad else 0.0
            best = max(best, cur)
        r["stats"]["isolated_stretch_m"] = round(best)
        r["profile"] = [{"d_km": round(s["d"] / 1000, 3), "lat": round(s["lat"], 6), "lng": round(s["lng"], 6),
                         "safety": round(e["S"], 1), "pollution": round(e["P"], 1),
                         "pm25": None if e["pm"] is None else round(e["pm"], 1)} for s, e in zip(samples, ev)]
        if idx is not None:
            seen, pts = set(), []
            for s in samples:
                for kind in ("help", "pharmacy", "fuel"):
                    for it in idx.within(kind, s["lat"], s["lng"], 250):
                        key = (round(it[2], 5), round(it[3], 5))
                        if key not in seen:
                            seen.add(key)
                            pts.append({"lat": it[2], "lng": it[3], "type": it[4].get("kind") or kind, "name": it[4].get("name", "")})
            r["safe_points"] = pts[:40]
            r["help_near"] = len([p for p in pts if p["type"] in ("police", "hospital", "help")])
        else:
            r["safe_points"], r["help_near"] = [], 0
    for r in routes:
        r["combined"] = combine(r["S"], r["P"], r["T"], weights)
        for p, e in zip(r["profile"], r["_ev"]):
            p["combined"] = round(combine(e["S"], e["P"], r["T"], weights), 1)
    # best time to leave: re-score each route for departures over the next hours
    series = []
    for h in range(hours_ahead + 1):
        d_h = depart + timedelta(hours=h)
        row = {"t": d_h.isoformat(), "offset_h": h, "routes": {}}
        for r in routes:
            ev = eval_at(r["_samples"], d_h, r["duration_s"], r["distance_m"] or 1, air, mode, advisory, r["_congestion"])
            row["routes"][r["id"]] = round(combine(_agg([e["S"] for e in ev]), sum(e["P"] for e in ev) / len(ev), r["T"], weights), 1)
        series.append(row)
    return series


def explain(routes: list[dict], weights: dict) -> tuple[str, int, list[dict]]:
    """Return (recommended id, confidence %, reasons)."""
    rk = sorted(routes, key=lambda r: r["combined"])
    best, others = rk[0], rk[1:]
    why: list[dict] = []
    if not others:
        return best["id"], 60, [{"ok": True, "text": "This is the only route available between these places."}]
    fast = min(routes, key=lambda r: r["duration_s"])
    dt = round((best["duration_s"] - fast["duration_s"]) / 60)
    why.append({"ok": dt <= 0, "text": "Also the fastest option" if dt <= 0 else f"Takes {dt} min longer than {fast['name']}"})
    pm_b = best["pm25"]
    pm_o = [o["pm25"] for o in others if o["pm25"] is not None]
    if pm_b is not None and pm_o:
        avg = sum(pm_o) / len(pm_o); pp = (avg - pm_b) / avg * 100 if avg else 0
        if pp >= 3: why.append({"ok": True, "text": f"{round(pp)}% lower PM2.5 exposure ({pm_b:.0f} vs {avg:.0f} µg/m³ on the other routes)"})
        elif pp <= -3: why.append({"ok": False, "text": f"{round(-pp)}% higher PM2.5 ({pm_b:.0f} vs {avg:.0f} µg/m³), offset by safety and time"})
        else: why.append({"ok": True, "text": f"Air quality is similar on all routes (about {pm_b:.0f} µg/m³ PM2.5)"})
    ds = sum(o["S"] for o in others) / len(others) - best["S"]
    why.append({"ok": ds >= -3, "text": (f"{round(ds)} points lower safety risk than the other routes" if ds >= 3 else
                                         f"Safety risk is {round(-ds)} points higher, offset by cleaner air and time" if ds <= -3 else
                                         "Safety risk is similar on all routes")})
    if best["stats"]["osm_data"]:
        wl = max(o["stats"]["well_lit_pct"] for o in others)
        if best["stats"]["well_lit_pct"] > wl + 8:
            why.append({"ok": True, "text": f"{best['stats']['well_lit_pct']}% of the path has street lighting nearby (others up to {wl}%)"})
        iso = max(o["stats"]["isolated_stretch_m"] for o in others)
        if best["stats"]["isolated_stretch_m"] + 150 < iso:
            why.append({"ok": True, "text": f"Longest dark, empty stretch is {best['stats']['isolated_stretch_m']} m instead of {iso} m"})
        why.append({"ok": best["help_near"] > 0, "text": (f"{best['help_near']} police or hospital point(s) within 250 m of the path" if best["help_near"]
                                                          else "No police or hospital within 250 m of the path. Share your trip with a contact")})
    margin = rk[1]["combined"] - best["combined"]
    quality = 0 if best["stats"]["osm_data"] and best["pm25"] is not None else -15
    conf = int(clamp(55 + margin * 3.5 + quality, 40, 96))
    return best["id"], conf, why
