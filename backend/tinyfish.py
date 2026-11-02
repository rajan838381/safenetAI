"""TinyFish integration - turns the live web into safety intelligence for a route.

Three TinyFish APIs are used:
  * Search API  (GET  https://api.search.tinyfish.ai)          - finds fresh local news and civic advisories
  * Fetch API   (POST https://api.fetch.tinyfish.ai)           - reads the full text of the most relevant articles
  * Agent API   (POST https://agent.tinyfish.ai/v1/automation/run-async + GET /v1/runs/{id})
                                                             - a web agent that opens a page and extracts structured data

All calls send the key in the `X-API-Key` header. See docs/tinyfish-integration.md.
"""
from __future__ import annotations
import asyncio
import re
import time
import httpx

SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"
AGENT_BASE = "https://agent.tinyfish.ai"

CATEGORIES = {
    "safety": ["harass", "molest", "assault", "stalk", "robbery", "snatch", "chain snatching", "kidnap", "rape", "eve-teas",
               "crime", "murder", "theft", "attack", "women safety", "unsafe", "stabbing", "molestation"],
    "road": ["road closed", "road closure", "diversion", "traffic jam", "accident", "waterlogging", "flood", "metro closed",
             "protest", "procession", "barricade", "blocked", "pothole", "bridge"],
    "air": ["aqi", "pollution", "smog", "air quality", "dust", "stubble", "graded response", "grap", "construction ban", "haze"],
    "civic": ["streetlight", "street light", "power cut", "blackout", "construction", "water supply", "police patrol", "advisory",
              "cctv", "pink", "she team"],
}
SEVERITY_WORDS = {"3": ["murder", "rape", "kidnap", "stabbing", "killed", "fatal"], "2": ["assault", "molest", "robbery", "snatch", "attack", "stalk", "harass"]}


class TinyFishError(Exception):
    pass


def _headers(key: str) -> dict:
    if not key:
        raise TinyFishError("TinyFish API key not set. Add TINYFISH_API_KEY to .env or paste it in Settings.")
    return {"X-API-Key": key}


def classify(text: str) -> tuple[str, int]:
    t = text.lower()
    best, hits = "other", 0
    for cat, words in CATEGORIES.items():
        h = sum(w in t for w in words)
        if h > hits:
            best, hits = cat, h
    sev = 1
    for s, words in SEVERITY_WORDS.items():
        if any(w in t for w in words):
            sev = max(sev, int(s))
    return best, sev


def area_queries(areas: list[str]) -> list[str]:
    """Turn place labels into short search queries such as 'Connaught Place Delhi'."""
    out = []
    for a in areas:
        parts = [p.strip() for p in a.split(",") if p.strip()]
        if not parts:
            continue
        place = parts[0]
        city = parts[-3] if len(parts) >= 4 else parts[-2] if len(parts) >= 2 else ""
        q = f"{place} {city}".strip()
        if q and q not in out:
            out.append(q)
    return out[:2]


async def search(client: httpx.AsyncClient, key: str, query: str, news: bool = True, recency_days: int = 14,
                 location: str = "IN") -> list[dict]:
    params = {"query": query, "location": location, "language": "en"}
    if news:
        params["domain_type"] = "news"
        params["recency_minutes"] = str(recency_days * 1440)
    r = await client.get(SEARCH_URL, params=params, headers=_headers(key), timeout=20)
    if r.status_code in (401, 403):
        raise TinyFishError("TinyFish rejected the API key (401/403). Check the key at agent.tinyfish.ai/api-keys.")
    r.raise_for_status()
    return r.json().get("results", [])


async def fetch_pages(client: httpx.AsyncClient, key: str, urls: list[str]) -> list[dict]:
    r = await client.post(FETCH_URL, json={"urls": urls[:5], "format": "markdown"}, headers=_headers(key), timeout=150)
    r.raise_for_status()
    return r.json().get("results", [])


async def agent_run(client: httpx.AsyncClient, key: str, url: str, goal: str, timeout_s: int = 110) -> dict:
    """Start an agent run and poll until it finishes. Returns {"status", "result"}."""
    h = {**_headers(key), "Content-Type": "application/json"}
    r = await client.post(f"{AGENT_BASE}/v1/automation/run-async", json={"url": url, "goal": goal}, headers=h, timeout=30)
    if r.status_code in (401, 403):
        raise TinyFishError("TinyFish rejected the API key (401/403).")
    r.raise_for_status()
    j = r.json()
    run_id = j.get("run_id") or j.get("id")
    if not run_id:
        return {"status": j.get("status", "UNKNOWN"), "result": j.get("result")}
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        await asyncio.sleep(3)
        g = await client.get(f"{AGENT_BASE}/v1/runs/{run_id}", headers=_headers(key), timeout=30)
        g.raise_for_status()
        d = g.json()
        st = str(d.get("status", "")).upper()
        if st in ("COMPLETED", "FAILED", "CANCELLED"):
            return {"status": st, "result": d.get("result"), "error": (d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error")}
    raise TinyFishError("The TinyFish agent is still running. Try again in a minute.")


async def live_intel(client: httpx.AsyncClient, key: str, areas: list[str]) -> dict:
    """Search recent news around the route and classify it. Returns {items, advisory_penalty, queries}."""
    queries = area_queries(areas)
    jobs = []
    for q in queries:
        jobs.append(search(client, key, f"{q} women safety crime harassment"))
        jobs.append(search(client, key, f"{q} road closure traffic air quality advisory"))
    res = await asyncio.gather(*jobs, return_exceptions=True)
    errors = [r for r in res if isinstance(r, Exception)]
    if errors and len(errors) == len(res):
        raise errors[0]
    items, seen = [], set()
    for r in res:
        if isinstance(r, Exception):
            continue
        for x in r:
            url = x.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            text = f"{x.get('title', '')}. {x.get('snippet', '')}"
            cat, sev = classify(text)
            if cat == "other":
                continue
            items.append({"title": x.get("title", ""), "snippet": x.get("snippet", ""), "url": url, "source": x.get("site_name", ""),
                          "category": cat, "severity": sev})
    items.sort(key=lambda i: (-i["severity"], i["category"] != "safety"))
    safety_hits = sum(1 for i in items if i["category"] == "safety")
    penalty = min(0.06, 0.015 * safety_hits)          # area-wide, deliberately small
    return {"items": items[:12], "advisory_penalty": penalty, "queries": queries}


DEEP_GOAL = (
    "Open this news article and extract safety-relevant facts as JSON with exactly these keys: "
    "headline (string), published_date (string, YYYY-MM-DD if shown), incident_type (one of: harassment, assault, theft, "
    "accident, road_closure, air_quality, civic_notice, other), location_text (the most specific place or locality named), "
    "city (string), severity (1 low, 2 medium, 3 high), time_of_day (string or null), summary (one sentence), "
    "advice_for_travellers (one short sentence). If the page is blocked or has no article, return {\"error\": \"reason\"}."
)
