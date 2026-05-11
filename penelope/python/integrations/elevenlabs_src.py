"""ElevenLabs voice-library activity fetcher.

The voice-library earnings dashboard at elevenlabs.io/app/voice-library/earnings
is not exposed via the public API (verified 2026-05-11 against 10+ candidate
paths, all 404). What we CAN pull live:

  - `cloned_by_count` for the user's shared voice (proxy for popularity)
  - `subscription.character_count` (own usage, separate from earnings)
  - voice status flags (enabled_in_library, financial_rewards_enabled)

Penelope reports the activity number honestly and tells Dylan the dollar
amount has to come from the dashboard. Once ElevenLabs ships an earnings
endpoint, swap `today` / `mtd` to the real numbers and the revenue panel
will pick it up automatically.

Config:
  elevenlabs:
    api_key: "sk_..."
    voice_id: "Mv9ouM1X38u0rfkwQxAz"   # the public shared voice
"""

from __future__ import annotations

import asyncio


async def fetch(cfg: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync, cfg)


def _fetch_sync(cfg: dict):
    el = cfg.get("elevenlabs") or {}
    key = el.get("api_key")
    vid = el.get("voice_id")
    if not key or not vid:
        return None
    try:
        import requests
    except ImportError:
        return None

    headers = {"xi-api-key": key}
    out = {"today": 0, "mtd": 0,
           "voice_id": vid,
           "voice_name": el.get("voice_name", ""),
           "note": "Earnings dashboard-only; see elevenlabs.io/app/voice-library/earnings"}

    try:
        r = requests.get(
            f"https://api.elevenlabs.io/v1/voices/{vid}?with_settings=true",
            headers=headers, timeout=10,
        )
        if r.ok:
            j = r.json()
            sharing = j.get("sharing") or {}
            out["voice_name"] = sharing.get("name", out["voice_name"]).strip()
            out["cloned_by_count"] = sharing.get("cloned_by_count", 0)
            out["liked_by_count"] = sharing.get("liked_by_count", 0)
            out["enabled_in_library"] = bool(sharing.get("enabled_in_library"))
            out["financial_rewards_enabled"] = bool(
                sharing.get("financial_rewards_enabled"))
    except Exception as e:
        out["error_voice"] = str(e)

    try:
        r = requests.get("https://api.elevenlabs.io/v1/user",
                         headers=headers, timeout=10)
        if r.ok:
            sub = r.json().get("subscription") or {}
            out["own_character_count"] = sub.get("character_count", 0)
            out["own_character_limit"] = sub.get("character_limit", 0)
            out["tier"] = sub.get("tier", "")
    except Exception as e:
        out["error_user"] = str(e)

    return out
