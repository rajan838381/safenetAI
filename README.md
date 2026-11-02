# VAYORA AI - Safer routes. Cleaner journeys.

Plan a journey between **any two places in the world**. VAYORA AI compares up to three routes on
**personal safety** (street lighting, open places, police and hospitals, isolated land, real sunset times,
community reports, live local news) and **air pollution** (hour-by-hour PM2.5 forecast), explains *why* one route
wins, tells you the best time to leave, and stays with you through a live journey with SOS and trip sharing.

## 1. Run it (5 minutes)

You need Python 3.10 or newer.

**Windows:** double-click `run.bat`  
**Mac / Linux:** `bash run.sh`

Or manually:

```bash
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Mac/Linux: cp .env.example .env
uvicorn backend.main:app --reload
```

Open **http://localhost:8000**. It works immediately with free services (OpenStreetMap, Open-Meteo).
Add your keys to unlock Google Maps and TinyFish.

## 2. Where to put your API keys

Open the file **`.env`** (created from `.env.example`) and replace the placeholders:

| Key in `.env` | What it unlocks | Where to get it |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | Google routes, place search, geocoding (server side) | console.cloud.google.com -> APIs & Services |
| `GOOGLE_MAPS_JS_KEY` | Google map in the browser (leave empty to reuse the key above) | same place |
| `TINYFISH_API_KEY` | Live Safety Intel (TinyFish Search, Fetch and Agent APIs) | https://agent.tinyfish.ai/api-keys |
| `ANTHROPIC_API_KEY` (optional) | Plain-language explanations and polished SOS text from Claude | console.anthropic.com |
| `TWILIO_*` (optional) | Real SMS to trusted contacts when SOS is sent | twilio.com |

**Google APIs to enable** in your Google Cloud project: *Maps JavaScript API*, *Routes API*, *Places API (New)*, *Geocoding API*.
Restrict the browser key to your website address, and the server key to those APIs.

You can also paste the Google and TinyFish keys inside the app: **Settings -> API keys** (saved only in your browser).
After saving keys, press **Settings -> Test connections**. It checks every integration and shows exactly what is wrong.

Restart the server after editing `.env`.

## 3. How to use

1. **Plan:** type a start and destination (any place, any address), use **My location**, or tap **Pick on map**. Choose Walk, Cycle, Scooter or Cab, and leave now or later.
2. **Compare routes:** see Safety risk, Air pollution, Time and a combined score for each route, the reasons, a risk chart along the route, and the best time to leave in the next 12 hours. Move the priority sliders (Safety first, Clean air, Fastest) and the ranking updates.
3. **Live:** start with GPS, or use **Simulate walk** to demo without moving. Off-route detection asks "Are you safe?" and sends an SOS if you do not answer. **Share live trip** gives your family a link.
4. **TinyFish intel:** scan the area for fresh local news and advisories, then let a TinyFish web agent verify any article and extract structured facts.
5. **Report:** flag a spot with poor lighting or harassment. Reports raise risk on nearby routes and fade over about a month.
6. **SOS** (red button): 5-second cancel window, then text, WhatsApp, call 112, optional SMS through Twilio. If you are offline the alert is saved and sent when you reconnect.
7. **Dashboard** (`/admin.html`): hotspots, report categories and journeys by hour for campuses and cab fleets.

## 4. How the scoring works (no black box)

* **Safety risk (0-100, higher is worse)** = poor lighting (30) + few people or open places nearby (28, stronger at night) + far from police/hospitals (14) + isolated land (12) + community reports and live advisories + a small baseline. Data: OpenStreetMap (via Overpass), real sun position, community reports, TinyFish.
* **Pollution risk** = PM2.5 forecast from Open-Meteo at the exact place and hour you will be there, mapped to a 0-100 scale, scaled by mode (cab 0.45, walk 1.0, cycle 1.15), plus construction and congestion bumps.
* **Time risk** = journey duration compared with the fastest route.
* **Combined** = weighted average with your weights.

The weights are expert-set starting points, **not** scientific constants. They should be calibrated with verified incident data before real-world deployment. See `docs/architecture.md`.

## 5. Project structure

```
vayora-ai/
  .env.example         <- put your API keys here (copy to .env)
  run.bat / run.sh     <- one-click start
  backend/
    main.py            API: analyze, intel, reports, trips, SOS, analytics, diagnostics
    providers.py       Google Routes / Places / Geocoding, with OpenStreetMap fallbacks
    safety.py          the risk engine and the explanations
    osm.py             street data from OpenStreetMap (Overpass)
    airquality.py      PM2.5 and weather from Open-Meteo
    tinyfish.py        TinyFish Search, Fetch and Agent APIs
    ai.py, notify.py   optional Claude and Twilio
    db.py              SQLite (reports, trips, SOS, stats)
    tests/             offline tests: python -m pytest backend/tests
  frontend/            index.html, track.html, admin.html, css/, js/
  docs/                architecture.md, tinyfish-integration.md
```

## 6. Honest limits

* Safety scores are explainable **estimates from open data**, not guarantees or crime predictions.
* OpenStreetMap coverage varies. Where data is thin the app says so and falls back to neutral assumptions.
* Free public services (Photon, Nominatim, OSRM, Overpass) have fair-use limits. Add a Google key for heavier use.
* Journeys are analysed up to 60 km.
* The community report system has no moderation yet. Add it before a public launch.

## 7. Hackathon note (HackIIITD Round 1)

The event rules say Round 1 is a **PPT/PDF submission**, and that submitting deployed links or coded material is not required and **may cause negative marking**. Keep this project folder for the finals. Put screenshots in your deck as the prototype, but do not attach code or live links in Round 1. Re-check the rules on the Unstop page before you submit.
