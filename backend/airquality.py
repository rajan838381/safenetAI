"""Live air quality + weather from Open-Meteo (free, no key). Forecast covers the next ~3 days."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import httpx

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_URL = "https://api.open-meteo.com/v1/forecast"


def cell_key(lat: float, lng: float) -> tuple[float, float]:
    return (round(lat, 1), round(lng, 1))   # ~11 km, the native resolution of the global model


async def fetch_air(client: httpx.AsyncClient, cells: list[tuple[float, float]]) -> dict:
    """Return {cell: {"times": [utc datetimes], "pm25": [...], "pm10": [...], "aqi": [...]}}."""
    cells = list(dict.fromkeys(cells))[:12]
    if not cells:
        return {}
    params = {"latitude": ",".join(str(c[0]) for c in cells), "longitude": ",".join(str(c[1]) for c in cells),
              "hourly": "pm2_5,pm10,us_aqi", "forecast_days": "3", "timezone": "auto"}
    r = await client.get(AQ_URL, params=params)
    r.raise_for_status()
    j = r.json()
    items = j if isinstance(j, list) else [j]
    out = {}
    for cell, it in zip(cells, items):
        off = timedelta(seconds=it.get("utc_offset_seconds", 0))
        h = it["hourly"]
        times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) - off for t in h["time"]]
        out[cell] = {"offset": off.total_seconds(), "times": times, "pm25": h.get("pm2_5", []), "pm10": h.get("pm10", []), "aqi": h.get("us_aqi", [])}
    return out


def value_at(series: dict, key: str, when: datetime):
    """Value of `key` at the hour closest to `when` (None if missing)."""
    times = series["times"]
    if not times:
        return None
    best, bi = None, 0
    for i, t in enumerate(times):
        d = abs((t - when).total_seconds())
        if best is None or d < best:
            best, bi = d, i
    vals = series.get(key) or []
    v = vals[bi] if bi < len(vals) else None
    return None if v is None else float(v)


async def fetch_weather(client: httpx.AsyncClient, lat: float, lng: float) -> dict:
    r = await client.get(WX_URL, params={"latitude": lat, "longitude": lng, "timezone": "auto",
                         "current": "temperature_2m,wind_speed_10m,precipitation,weather_code"})
    r.raise_for_status()
    c = r.json().get("current", {})
    return {"temp_c": c.get("temperature_2m"), "wind_kmh": c.get("wind_speed_10m"), "rain_mm": c.get("precipitation"),
            "code": c.get("weather_code")}
