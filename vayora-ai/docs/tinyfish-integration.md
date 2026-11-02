# How VAYORA AI integrates the TinyFish API

Use this page for the mandatory slide **"How do you plan to integrate the TinyFish API?"**

## The problem TinyFish solves for us
Route safety changes by the day: a road closed this morning, a streetlight outage, a news report from last night.
Static maps and open data cannot see that. VAYORA AI uses TinyFish to read the live web and turn it into structured safety intelligence.

## Three TinyFish APIs, three jobs

| TinyFish API | Endpoint | What VAYORA does with it | Code |
|---|---|---|---|
| **Search** | `GET https://api.search.tinyfish.ai?query=...&domain_type=news&recency_minutes=...` | Finds fresh local news and advisories for the start and destination areas. Results are classified (safety, road, air, civic) and scored for severity. A small area-wide advisory penalty (max +6 risk points) feeds the safety engine. | `backend/tinyfish.py: live_intel()` |
| **Fetch** | `POST https://api.fetch.tinyfish.ai` | Reads the full text of the most relevant articles so classification is not limited to snippets (extension point already wired as `fetch_pages()`). | `backend/tinyfish.py: fetch_pages()` |
| **Agent** | `POST https://agent.tinyfish.ai/v1/automation/run-async` then `GET /v1/runs/{id}` | The "Verify with TinyFish agent" button sends a plain-English goal to a web agent that opens an article and returns JSON: headline, date, incident type, location, severity, advice. | `backend/tinyfish.py: agent_run()` |

Authentication: `X-API-Key` header, key from `agent.tinyfish.ai/api-keys`, stored as `TINYFISH_API_KEY` (server) so it never reaches the browser.

## Data flow
```
Route request -> backend extracts area names -> TinyFish Search (news, last 14 days)
 -> keyword + severity classification -> advisory penalty -> safety engine -> explained route ranking
 -> user taps "Verify" -> TinyFish Agent opens the article -> structured JSON shown in the app
```

## Why this is feasible and scalable
* Search is fast (about 1-3 s), so it runs inside every analysis and is cached for 15 minutes per area.
* Agent runs (15-60 s) are on demand only, so cost stays low.
* The same pipeline works for any city: queries are built from the place names the user picks.

## Suggested slide text
**How do you plan to integrate the TinyFish API?**
1. Search API: find fresh local safety, road and air-quality news for the route area.
2. Fetch API: read full articles for accurate classification.
3. Agent API: a web agent verifies an article and extracts structured incident data (type, place, severity, advice).
4. Output: an area advisory score added to our explainable risk engine, and source links shown to the user.
5. Backend-only key handling, caching, graceful fallback when the key is missing.
