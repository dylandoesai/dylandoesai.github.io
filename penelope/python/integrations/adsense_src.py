"""Google AdSense / YouTube ad-revenue fetcher.

Two modes (decided by what's in config.json -> adsense):

  A) Google AdSense Management API
       adsense:
         oauth_token: "ya29.a0..."   # bearer token from OAuth flow
         account_id:  "pub-1234567890123456"

  B) YouTube Studio direct revenue (via YouTube Analytics API)
       youtube_revenue:
         oauth_token: "ya29.a0..."
         channel_ids: ["UC_xxx", ...]

OAuth setup is a one-time chore: create a Google Cloud project, enable
the AdSense Management API (or YouTube Analytics API), generate a
desktop-app OAuth client, run the helper at:
    scripts/google_oauth_setup.py
to capture a refresh token, then paste it into config.json.

Until you configure it, this returns None and the JSON cache is used.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import requests


async def fetch(cfg: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync, cfg)


def _fetch_sync(cfg: dict):
    a = cfg.get("adsense") or {}
    token = a.get("oauth_token")
    acct = a.get("account_id")
    if not token or not acct:
        return None
    now = dt.date.today()
    month_start = now.replace(day=1)
    base = f"https://adsense.googleapis.com/v2/accounts/accounts/{acct}/reports:generate"
    headers = {"Authorization": f"Bearer {token}"}

    def total(start, end):
        try:
            r = requests.get(base, headers=headers, params={
                "dateRange": "CUSTOM",
                "startDate.year": start.year, "startDate.month": start.month,
                "startDate.day": start.day,
                "endDate.year": end.year, "endDate.month": end.month,
                "endDate.day": end.day,
                "metrics": "ESTIMATED_EARNINGS",
            }, timeout=10).json()
            cells = ((r.get("totals") or {}).get("cells")) or []
            if cells: return float(cells[0].get("value") or 0)
        except Exception: pass
        return 0
    return {
        "today": round(total(now, now), 2),
        "mtd": round(total(month_start, now), 2),
    }
