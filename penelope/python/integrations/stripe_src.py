"""Stripe revenue fetcher.

Config:
  stripe:
    api_key: "rk_live_..."     # restricted key, read-only balance + charges
"""

from __future__ import annotations

import asyncio
import datetime as dt


async def fetch(cfg: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync, cfg)


def _fetch_sync(cfg: dict):
    s = (cfg.get("stripe") or {}).get("api_key")
    if not s:
        return None
    try:
        import stripe
    except ImportError:
        return None
    stripe.api_key = s

    now = dt.datetime.now(dt.timezone.utc)
    day_start = int(dt.datetime.combine(now.date(), dt.time.min,
                                         tzinfo=dt.timezone.utc).timestamp())
    month_start = int(dt.datetime(now.year, now.month, 1,
                                   tzinfo=dt.timezone.utc).timestamp())

    today_total = 0
    mtd_total = 0
    try:
        for ch in stripe.BalanceTransaction.list(
                created={"gte": month_start}, limit=100).auto_paging_iter():
            if ch.type not in ("charge", "payment"): continue
            amt = (ch.amount or 0) / 100.0
            mtd_total += amt
            if ch.created >= day_start:
                today_total += amt
    except Exception as e:
        return {"today": 0, "mtd": 0, "error": str(e)}

    return {"today": round(today_total, 2), "mtd": round(mtd_total, 2)}
