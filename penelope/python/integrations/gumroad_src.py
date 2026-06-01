"""Gumroad revenue fetcher.

Config:
  gumroad:
    access_token: "<personal token from https://gumroad.com/settings/advanced>"

We hit /v2/sales with filtered date ranges. Gumroad's API caps at 250
per page; we paginate until we cover the month.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import requests

API = "https://api.gumroad.com/v2"


async def fetch(cfg: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync, cfg)


def _fetch_sync(cfg: dict):
    g = (cfg.get("gumroad") or {}).get("access_token")
    if not g:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    month_start = dt.datetime(now.year, now.month, 1, tzinfo=dt.timezone.utc)
    day_start = dt.datetime.combine(now.date(), dt.time.min,
                                     tzinfo=dt.timezone.utc)

    today, mtd = 0.0, 0.0
    page = 1
    while page < 20:  # safety cap
        try:
            r = requests.get(f"{API}/sales",
                              params={
                                  "access_token": g,
                                  "after": month_start.strftime("%Y-%m-%d"),
                                  "page": page,
                              },
                              timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return {"today": 0, "mtd": 0, "error": str(e)}
        sales = data.get("sales") or []
        if not sales:
            break
        for s in sales:
            cents = s.get("price", 0)
            amt = cents / 100.0
            mtd += amt
            ts = s.get("created_at")
            if ts:
                try:
                    when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if when >= day_start:
                        today += amt
                except Exception:
                    pass
        if not data.get("next_page_url"):
            break
        page += 1
    return {"today": round(today, 2), "mtd": round(mtd, 2)}
