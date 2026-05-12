"""upload-post.com analytics client.

API base + auth:
    GET https://api.upload-post.com/api/analytics/{profile_username}
        ?platforms=youtube,tiktok,instagram,facebook,x
    Authorization: Apikey <jwt>

Single call returns 28-day-window stats per requested platform:
    {
      "<platform>": {
        "followers": int,
        "reach": int,
        "impressions": int,
        "likes": int,
        "comments": int,
        "shares": int,
        "saves": int,
        "profileViews": int,
        "reach_timeseries": [{"date": "YYYY-MM-DD", "value": int}, ...],
      },
      ...
    }

One nickname per upload-post profile covers all five of that channel's
social accounts, so we make one call per channel (7 calls for the
network, not 35).

Channel-to-nickname mapping comes from config/channels.json. We collect
the distinct upload_post_nickname per channel and call the API once.

Endpoint discovered via the OpenAPI spec at
https://docs.upload-post.com/openapi.json (2026-05-11).
"""

from __future__ import annotations

import asyncio
import concurrent.futures

import requests

API = "https://api.upload-post.com/api"
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

    # One call per channel — the upload_post nickname is shared across
    # platforms for a given channel, so a single GET pulls all 5 buckets.
    jobs = []
    for ch in channels:
        name = ch.get("name") or f"channel-{ch.get('id','?')}"
        platforms_map = ch.get("platforms") or {}
        nick = None
        for p in PLATFORMS:
            n = (platforms_map.get(p) or {}).get("upload_post_nickname")
            if n:
                nick = n; break
        if not nick:
            continue
        handles = {p: (platforms_map.get(p) or {}).get("handle") or ""
                   for p in PLATFORMS}
        jobs.append({"channel": name, "nickname": nick, "handles": handles})

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futs = {ex.submit(_fetch_one, headers, j): j for j in jobs}
        for f in concurrent.futures.as_completed(futs):
            j = futs[f]
            try:
                data = f.result()
            except Exception as e:
                data = {"error": str(e)}
            results.append({**j, "data": data})

    return _shape_for_panels(results)


def _fetch_one(headers, job):
    r = requests.get(
        f"{API}/analytics/{job['nickname']}",
        headers=headers,
        params={"platforms": ",".join(PLATFORMS)},
        timeout=12,
    )
    r.raise_for_status()
    return r.json() or {}


def _last_value(ts):
    if not isinstance(ts, list) or not ts:
        return 0
    return ts[-1].get("value", 0) or 0


def _sum_values(ts, days=None):
    if not isinstance(ts, list):
        return 0
    src = ts[-days:] if days else ts
    return sum((p.get("value", 0) or 0) for p in src)


def _shape_for_panels(results: list) -> dict:
    """Bucket results into the per-platform shape the renderer expects."""
    out = {p: {"channels": [], "series_views": []} for p in PLATFORMS}
    series_by_platform = {p: [] for p in PLATFORMS}

    for r in results:
        per_platform = r.get("data") or {}
        if isinstance(per_platform, dict) and "error" in per_platform and len(per_platform) == 1:
            # All-platforms failed for this channel; still emit empty rows
            for p in PLATFORMS:
                out[p]["channels"].append({
                    "name": r["channel"],
                    "platform_handle": r["handles"].get(p, ""),
                    "subs": 0, "views_today": 0, "views_28d": 0, "top": [],
                    "error": per_platform.get("error"),
                })
            continue
        for p in PLATFORMS:
            d = per_platform.get(p) or {}
            ts = d.get("reach_timeseries") or []
            out[p]["channels"].append({
                "name": r["channel"],
                "platform_handle": r["handles"].get(p, ""),
                "subs":         d.get("followers", 0) or 0,
                "views_today":  _last_value(ts),
                "views_28d":    d.get("impressions", 0) or _sum_values(ts),
                "likes_28d":    d.get("likes", 0) or 0,
                "comments_28d": d.get("comments", 0) or 0,
                "shares_28d":   d.get("shares", 0) or 0,
                "top": [],  # top-videos endpoint is separate; not pulled here
            })
            if ts:
                series_by_platform[p].append([pt.get("value", 0) or 0 for pt in ts])

    for p, lst in series_by_platform.items():
        if not lst:
            continue
        n = max(len(s) for s in lst)
        agg = [0] * n
        for s in lst:
            for i, v in enumerate(s):
                agg[i] += v
        out[p]["series_views"] = agg

    return {p: out[p] for p in PLATFORMS}
