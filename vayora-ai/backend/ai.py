"""Optional Claude (Anthropic) integration: plain-language route explanation and SOS summary."""
from __future__ import annotations
import httpx
from . import config

URL = "https://api.anthropic.com/v1/messages"


def available() -> bool:
    return bool(config.env("ANTHROPIC_API_KEY"))


async def ask(client: httpx.AsyncClient, system: str, prompt: str, max_tokens: int = 350) -> str | None:
    key = config.env("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        r = await client.post(URL, headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                              json={"model": config.env("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": max_tokens,
                                    "system": system, "messages": [{"role": "user", "content": prompt}]}, timeout=40)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", [])).strip() or None
    except Exception:
        return None
