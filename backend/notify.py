"""Optional Twilio SMS for real SOS messages (set TWILIO_* in .env)."""
from __future__ import annotations
import httpx
from . import config


def available() -> bool:
    return all(config.env(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"))


async def send_sms(client: httpx.AsyncClient, to: str, body: str) -> dict:
    sid, tok, frm = config.env("TWILIO_ACCOUNT_SID"), config.env("TWILIO_AUTH_TOKEN"), config.env("TWILIO_FROM")
    r = await client.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", auth=(sid, tok),
                          data={"To": to, "From": frm, "Body": body[:1500]}, timeout=20)
    return {"to": to, "ok": r.status_code < 300, "status": r.status_code}
