"""upload-post.com API client.

upload-post.com gives one API + one nickname per platform-account
connection. With 7 channels x 5 platforms (YouTube, TikTok, Instagram,
Facebook, X) you'll have up to 35 separate connections, each with its
own nickname.

Source of truth for what to fetch is config/channels.json. Schema:

    {
      "channels": [
        { "id": 1, "name": "channel-1",
          "platforms": {
            "youtube":   { "handle": "@a",  "upload_post_nickname": "ch1-yt" },
            "tiktok":    { "handle": "@aa", "upload_post_nickname": "ch1-tt" },
            "instagram": { "handle": "@a",  "upload_post_nickname": "ch1-ig" },
            "facebook":  { "handle": "a",   "upload_post_nickname": "ch1-fb" },
            "x":         { "handle": "@A",  "upload_post_nickname": "ch1-x"  }
          }
        },
        ...
      ]
    }

Handles can differ per platform per channel (that's the whole point of
the per-platform record). Anything with an empty upload_post_nickname
is skipped.

This module aggregates analytics per platform across all channels for
the side panels, and also returns per-channel breakdowns Penelope can
draw on for the daily brief.
"""

from __future__ import annotations

import asyncio
import concurrent.futures

import requests

API_BASE = "https://api.upload-post.com/api"
PLATFORMS = ("youtube", "tiktok", "instagram", "facebook", "x")


async def fetch_all(cfg: dict) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync, cfg)


def _fetch_sync(cfg: dict) -> dict:
    up = cfg.get("upload_post") or {}
    api_key = up.get("api_key")
    channels_cfg = (cfg.get("channels") or {})
    channels = channels_cfg.get("channels") if isinstance(channels_cfg, dict) else channels_cfg
    if not api_key or not channels:
        return cfg.get("analytics", {})

    headers = {"Authorization": f"Apikey {api_key}"}

    # Build the (channel, platform, nickname) work list
    jobs = []
    for ch in channels:
        name = ch.get("name") or f"channel-{ch.get('id','?')}"
        for platform in PLATFORMS:
            p = (ch.get("platforms") or {}).get(platform) or {}
            nick = p.get("upload_post_nickname")
            if not nick:
                continue
            jobs.append({
                "channel": name,
                "platform": platform,
                "handle": p.get("handle") or "",
                "nickname": nick,
            })

    # Fetch them in parallel (up to 8 at a time)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fetch_one, headers, j): j for j in jobs}
        for f in concurrent.futures.as_completed(futs):
            j = futs[f]
            try: data = f.result()
            except Exception as e: data = {"error": str(e)}
            results.append({**j, "data": data})

    return _shape_for_panels(results)


def _fetch_one(headers, job):
    r = requests.get(
        f"{API_BASE}/analytics",
        headers=headers,
        params={"nickname": job["nickname"], "platform": job["platform"]},
        timeout=10,
    )
    r.raise_for_status()
    return r.json() or {}


def _shape_for_panels(results: list) -> dict:
    """Bucket per-channel-per-platform results into the shape the side
    panels expect (YT and TT each get a 'channels' list + agg series)."""
    out = {p: {"channels": [], "series_views": []} for p in PLATFORMS}
    series_by_platform = {p: [] for p in PLATFORMS}

    for r in results:
        p = r["platform"]; d = r.get("data") or {}
        out[p]["channels"].append({
            "name": r["channel"],
            "handle": r["handle"],
            "subs": d.get("followers", d.get("subscribers", 0)),
            "views_today": d.get("views_24h", 0),
            "views_28d": d.get("views_28d", 0),
            "top": [
                {"title": v.get("title"), "views": v.get("views", 0)}
                for v in (d.get("top_videos") or d.get("top_posts") or [])[:5]
            ],
        })
        s = d.get("series_views_14d") or d.get("series_14d") or []
        if s: series_by_platform[p].append(s)

    for p, lst in series_by_platform.items():
        if not lst: continue
        n = max(len(s) for s in lst)
        agg = [0] * n
        for s in lst:
            for i, v in enumerate(s):
                agg[i] += v
        out[p]["series_views"] = agg

    # The renderer panels currently render youtube + tiktok prominently;
    # ig/fb/x are returned too so Penelope can mention them in the brief.
    return {
        "youtube":   out["youtube"],
        "tiktok":    out["tiktok"],
        "instagram": out["instagram"],
        "facebook":  out["facebook"],
        "x":         out["x"],
    }
