# VAYORA AI - Architecture

```
Browser (HTML, CSS, JS)                         FastAPI backend                          External services
┌─────────────────────────┐   /api/*          ┌───────────────────────────┐
│ Plan | Live | Intel |   │ ───────────────▶  │ main.py (routes)          │ ─▶ Google Routes / Places / Geocoding
│ Report | Settings       │                   │ providers.py              │ ─▶ OSRM, Photon, Nominatim (free fallback)
│ Google Maps or Leaflet  │ ◀───────────────  │ safety.py  risk engine    │ ─▶ OpenStreetMap Overpass  (street data)
│ 3D hero (three.js)      │   JSON            │ osm.py / airquality.py    │ ─▶ Open-Meteo (PM2.5, weather)
│ Service worker (offline)│                   │ tinyfish.py               │ ─▶ TinyFish Search, Fetch, Agent
└─────────────────────────┘                   │ ai.py / notify.py (opt.)  │ ─▶ Anthropic Claude, Twilio SMS
        track.html, admin.html                │ db.py (SQLite)            │
                                              └───────────────────────────┘
```

## Analysis pipeline (`POST /api/analyze`)

1. **Routes** - Google Routes API (or OSRM). If fewer than three distinct routes exist, extra routes are requested through side waypoints.
2. **Sample** - each route is resampled every 150 m or less (max about 36 points).
3. **Gather in parallel** - OSM street features for the route area, Open-Meteo PM2.5 for each ~11 km cell, weather, community reports from SQLite, TinyFish live intel.
4. **Score each sample** at its own arrival time (so a long walk that crosses sunset is scored correctly).
5. **Aggregate** - safety = 0.75 x mean + 0.25 x worst point (one dark alley matters); pollution = mean exposure; time = relative to the fastest route.
6. **Combine and rank** with the user's weights; build explanations and a 12-hour "best time to leave" series by re-scoring every route for each departure hour.

## Safety model weights (expert-set starting points)

| Component | Weight | Data |
|---|---|---|
| Poor street lighting (stronger after dark) | 0.30 | OSM `highway=street_lamp` within 120 m, sun elevation |
| Few people or open places nearby | 0.28 | OSM open-late amenities within 200 m (daytime-only places fade at night) |
| Far from police or hospitals | 0.14 | nearest OSM police/hospital/fire station |
| Isolated land | 0.12 | OSM industrial, quarry, landfill, cemetery, forest; parks count partly after dark |
| Community reports | up to 0.15 | VAYORA reports within 250 m, decaying with a 14-day half-life |
| Live advisories | up to 0.06 | TinyFish Search results classified as safety news |

These weights are not learned from data. Real deployment must calibrate them with verified incident data.

## Pollution

PM2.5 (Open-Meteo / CAMS forecast) -> risk via a piecewise scale: 12 -> 15, 35 -> 40, 55 -> 58, 150 -> 85, 250 -> 100.
Mode factors: cab 0.45 (cabin air), scooter 0.95, walk 1.0, cycle 1.15. Construction land nearby adds 8 points.

## Privacy

* Live location leaves the phone only when the user starts a shared trip or sends an SOS.
* Trip links use a random id and show only the route and last position. Stop sharing by ending the journey.
* API keys pasted in Settings stay in the browser. Server keys stay in `.env`.

## Scalability

* The backend is stateless apart from SQLite (swap for PostgreSQL by changing `db.py`).
* Overpass and Open-Meteo results are cached in memory (15-30 min). For scale, self-host Overpass and add Redis.
* One analysis uses 1 routing call, 1 Overpass call, 1 air-quality call, 1 weather call and 1-4 TinyFish Search calls.
