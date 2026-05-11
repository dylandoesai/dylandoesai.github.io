"""upload-post.com API client.

upload-post.com lets you post to YouTube, TikTok, Instagram, Facebook,
and X with a single API and pull analytics back. Per user spec, that's
how we get analytics for all 7 channels x 5 platforms.

Config keys we expect in config/config.json:
  upload_post:
    api_key: "<your key>"
    accounts:
      - {nickname: "main", platforms: ["youtube", "tiktok", "instagram",
                                       "facebook", "x"]}
      - {nickname: "channel-2", platforms: [...]}
      ...

Endpoints used (per upload-post docs):
  GET /api/accounts                       -- list connected accounts
  GET /api/analytics?nickname={n}         -- per-account analytics

If the API key is absent we return the JSON cache, so the renderer still
shows something sensible.
"""

from __future__ import annotations

import asyncio

import requests

API_BASE = "https://api.upload-post.com/api"


async def fetch_all(cfg: dict) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync, cfg)


def _fetch_sync(cfg: dict) -> dict:
    up = cfg.get("upload_post") or {}
    api_key = up.get("api_key")
    accounts = up.get("accounts") or []
    if not api_key or not accounts:
        return cfg.get("analytics", {})

    headers = {"Authorization": f"Apikey {api_key}"}
    yt_channels, tt_channels = [], []
    yt_series, tt_series = [], []

    for acct in accounts:
        nickname = acct["nickname"]
        try:
            r = requests.get(f"{API_BASE}/analytics",
                             headers=headers,
                             params={"nickname": nickname},
                             timeout=10)
            r.raise_for_status()
            data = r.json() or {}
        except Exception:
            continue

        # YouTube
        yt = data.get("youtube") or {}
        if yt:
            yt_channels.append({
                "name": nickname,
                "handle": yt.get("handle"),
                "subs": yt.get("subscribers", 0),
                "views_today": yt.get("views_24h", 0),
                "views_28d": yt.get("views_28d", 0),
                "top": [
                    {"title": v.get("title"), "views": v.get("views", 0)}
                    for v in (yt.get("top_videos") or [])[:5]
                ],
            })
            yt_series.append(yt.get("series_views_14d") or [])

        # TikTok
        tt = data.get("tiktok") or {}
        if tt:
            tt_channels.append({
                "name": nickname,
                "handle": tt.get("handle"),
                "subs": tt.get("followers", 0),
                "views_today": tt.get("views_24h", 0),
                "views_28d": tt.get("views_28d", 0),
                "top": [
                    {"title": v.get("title"), "views": v.get("views", 0)}
                    for v in (tt.get("top_videos") or [])[:5]
                ],
            })
            tt_series.append(tt.get("series_views_14d") or [])

    def agg(series_list):
        if not series_list: return []
        n = max(len(s) for s in series_list)
        out = [0] * n
        for s in series_list:
            for i, v in enumerate(s):
                out[i] += v
        return out

    return {
        "youtube": {"channels": yt_channels, "series_views": agg(yt_series)},
        "tiktok":  {"channels": tt_channels, "series_views": agg(tt_series)},
    }
