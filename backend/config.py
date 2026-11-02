"""Central place that reads API keys and settings from the environment (.env)."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:  # python-dotenv is optional
    pass

PLACEHOLDER = "PASTE_YOUR"


def env(name: str, default: str = "") -> str:
    v = (os.getenv(name) or default).strip()
    return "" if v.startswith(PLACEHOLDER) else v  # an untouched placeholder counts as "not set"


def google_server_key(override: str = "") -> str:
    return override.strip() or env("GOOGLE_MAPS_API_KEY")


def google_js_key() -> str:
    return env("GOOGLE_MAPS_JS_KEY") or env("GOOGLE_MAPS_API_KEY")


def tinyfish_key(override: str = "") -> str:
    return override.strip() or env("TINYFISH_API_KEY")


def user_agent() -> str:
    return f"VAYORA-AI/1.0 ({env('CONTACT_EMAIL', 'you@example.com')})"


FRONTEND_DIR = ROOT / "frontend"
DB_PATH = env("DB_PATH", "vayora.db")
