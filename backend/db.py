"""SQLite storage: community reports, shared trips, SOS events and anonymous journey stats."""
from __future__ import annotations
import json
import secrets
import sqlite3
import threading
import time
from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, lat REAL, lng REAL, category TEXT, severity INTEGER, note TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS trips(id TEXT PRIMARY KEY, name TEXT, route TEXT, created_at REAL, last_lat REAL, last_lng REAL, last_ts REAL, status TEXT);
        CREATE TABLE IF NOT EXISTS sos(id INTEGER PRIMARY KEY, name TEXT, lat REAL, lng REAL, reason TEXT, summary TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS journeys(id INTEGER PRIMARY KEY, mode TEXT, distance_m REAL, combined REAL, safety REAL, pollution REAL, hour INTEGER, created_at REAL);
        """)
    return _conn


def reset_for_tests(path: str) -> None:
    global _conn
    config.DB_PATH = path
    _conn = None


def add_report(lat, lng, category, severity, note) -> int:
    with _lock:
        c = conn().execute("INSERT INTO reports(lat,lng,category,severity,note,created_at) VALUES(?,?,?,?,?,?)",
                           (lat, lng, category, severity, note[:300], time.time()))
        conn().commit()
        return c.lastrowid


def reports_in(south, west, north, east, days=45) -> list[dict]:
    since = time.time() - days * 86400
    with _lock:
        rows = conn().execute("SELECT * FROM reports WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? AND created_at>? ORDER BY created_at DESC LIMIT 300",
                              (south, north, west, east, since)).fetchall()
    return [dict(r) for r in rows]


def new_trip(name: str, route: dict) -> str:
    tid = secrets.token_urlsafe(6)
    with _lock:
        conn().execute("INSERT INTO trips VALUES(?,?,?,?,?,?,?,?)", (tid, name[:40], json.dumps(route), time.time(), None, None, None, "active"))
        conn().commit()
    return tid


def ping_trip(tid: str, lat: float, lng: float, status: str) -> bool:
    with _lock:
        c = conn().execute("UPDATE trips SET last_lat=?, last_lng=?, last_ts=?, status=? WHERE id=?", (lat, lng, time.time(), status, tid))
        conn().commit()
        return c.rowcount > 0


def get_trip(tid: str) -> dict | None:
    with _lock:
        r = conn().execute("SELECT * FROM trips WHERE id=?", (tid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["route"] = json.loads(d["route"])
    return d


def add_sos(name, lat, lng, reason, summary) -> int:
    with _lock:
        c = conn().execute("INSERT INTO sos(name,lat,lng,reason,summary,created_at) VALUES(?,?,?,?,?,?)", (name[:40], lat, lng, reason[:200], summary[:1500], time.time()))
        conn().commit()
        return c.lastrowid


def add_journey(mode, distance_m, combined, safety, pollution, hour) -> None:
    with _lock:
        conn().execute("INSERT INTO journeys(mode,distance_m,combined,safety,pollution,hour,created_at) VALUES(?,?,?,?,?,?,?)",
                       (mode, distance_m, combined, safety, pollution, hour, time.time()))
        conn().commit()


def analytics() -> dict:
    with _lock:
        c = conn()
        rep = [dict(r) for r in c.execute("SELECT category, COUNT(*) n, AVG(severity) sev FROM reports GROUP BY category")]
        hours = [dict(r) for r in c.execute("SELECT hour, COUNT(*) n, AVG(combined) risk FROM journeys GROUP BY hour ORDER BY hour")]
        modes = [dict(r) for r in c.execute("SELECT mode, COUNT(*) n, AVG(combined) risk FROM journeys GROUP BY mode")]
        tot = dict(c.execute("SELECT COUNT(*) journeys, AVG(combined) avg_risk, SUM(distance_m)/1000 km FROM journeys").fetchone())
        sos = [dict(r) for r in c.execute("SELECT id,name,lat,lng,reason,created_at FROM sos ORDER BY created_at DESC LIMIT 20")]
        pts = [dict(r) for r in c.execute("SELECT lat,lng,category,severity,note,created_at FROM reports ORDER BY created_at DESC LIMIT 500")]
        sos_n = c.execute("SELECT COUNT(*) FROM sos").fetchone()[0]
        trips = c.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    return {"totals": {**tot, "sos": sos_n, "shared_trips": trips, "reports": sum(r["n"] for r in rep)},
            "reports_by_category": rep, "journeys_by_hour": hours, "journeys_by_mode": modes, "recent_sos": sos, "report_points": pts}
