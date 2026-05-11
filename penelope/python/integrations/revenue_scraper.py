"""Revenue scraper for Stripe Express + Gumroad dashboards.

The voice-library / gumroad / stripe-connect-express APIs don't expose
earnings to creators (Stripe Express accounts have no developer
credentials). So we scrape the logged-in dashboards once a day using
Playwright with a persistent profile.

Profile lives at ~/Library/Application Support/Penelope/scraper-profile.
First invocation opens a visible window so Dylan can log in once;
subsequent runs reuse cookies and finish in a few seconds.

CLI:
    python python/run_revenue_scrape.py            # default: all sources
    python python/run_revenue_scrape.py --stripe   # just Stripe Express
    python python/run_revenue_scrape.py --headless # try headless (skip first run)

Output: overwrites the stripe_express + gumroad blocks of config/revenue.json
with timestamped results. brain.gather_revenue() picks the numbers up.

Designed for daily runs via launchd. The plist lives at scripts/penelope.revenue.plist.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = Path.home() / "Library" / "Application Support" / "Penelope" / "scraper-profile"
REVENUE_JSON = ROOT / "config" / "revenue.json"
STRIPE_EXPRESS_URL = "https://connect.stripe.com/express_login"


# ---------- Stripe Express scrape ------------------------------------------

_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")


def _parse_money(s: str | None) -> float | None:
    if not s:
        return None
    m = _MONEY.search(s.replace(" ", " "))
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


async def scrape_stripe_express(headless: bool = False) -> dict:
    from playwright.async_api import async_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict = {
        "scraped_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "scrape_source": "playwright",
    }

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(STRIPE_EXPRESS_URL, wait_until="domcontentloaded",
                            timeout=30000)

            # If we're not logged in Stripe will route to a login page.
            # Wait up to 5 minutes the first time so Dylan can finish login.
            login_deadline = dt.datetime.now() + dt.timedelta(minutes=5)
            while True:
                url = page.url
                if "/app/" in url or "/express/" in url and "login" not in url.lower():
                    break
                if dt.datetime.now() > login_deadline:
                    raise RuntimeError("not logged in (5 min timeout)")
                await page.wait_for_timeout(2000)

            # Earnings dashboard layout: top-of-page contains
            # "Recent earnings" (12mo total) and a "Total balance" card.
            # We grab the page text and regex out the structured numbers
            # since the DOM selectors change frequently.
            await page.wait_for_timeout(2500)
            body_text = await page.evaluate("() => document.body.innerText")
            out["raw_url"] = url

            # 12-month earnings — the headline number under "Recent earnings"
            m = re.search(r"Recent earnings[\s\S]{0,80}?\$([\d,]+\.\d{2})", body_text)
            if m:
                out["earnings_12mo_usd"] = float(m.group(1).replace(",", ""))

            # Total balance — under "Total balance" heading
            m = re.search(r"Total balance[\s\S]{0,40}?\$([\d,]+\.\d{2})", body_text)
            if m:
                out["total_balance_usd"] = float(m.group(1).replace(",", ""))

            # Available to pay out — appears as "$N.NN Available to pay out"
            m = re.search(r"\$([\d,]+\.\d{2})\s*[\n\r ]+Available to pay out", body_text)
            if m:
                out["available_to_payout_usd"] = float(m.group(1).replace(",", ""))

            # Pull "Recent transactions" rows for today
            today_iso = dt.date.today().isoformat()
            today_label = dt.date.today().strftime("%b %-d")  # e.g. "May 11"
            today_total = 0.0
            today_count = 0
            for line in body_text.splitlines():
                if today_label in line and "$" in line:
                    val = _parse_money(line)
                    if val is not None and val < 10000:  # sanity
                        today_total += val
                        today_count += 1
            out["today_usd"] = round(today_total, 2)
            out["today_payment_count"] = today_count
            out["today_label"] = today_label
            out["today_date"] = today_iso

            # Activity feed: "Your $X.XX payout from <platform> is on its way"
            m = re.search(r"Your\s*\$([\d,]+\.\d{2})\s*payout from (\w+)", body_text)
            if m:
                out["last_payout_usd"] = float(m.group(1).replace(",", ""))
                out["last_payout_platform"] = m.group(2)
        finally:
            await ctx.close()

    return out


# ---------- config/revenue.json write ---------------------------------------

def write_revenue(stripe_express: dict | None = None,
                  gumroad: dict | None = None) -> None:
    cur = json.loads(REVENUE_JSON.read_text())
    if stripe_express:
        cur["stripe_express"] = stripe_express
    if gumroad:
        cur["gumroad"] = gumroad
    REVENUE_JSON.write_text(json.dumps(cur, indent=2) + "\n")


# ---------- main ------------------------------------------------------------

async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--stripe", action="store_true", help="only scrape Stripe Express")
    ap.add_argument("--gumroad", action="store_true", help="only scrape Gumroad (TBD)")
    ap.add_argument("--headless", action="store_true",
                    help="run headless (requires cookies already saved)")
    args = ap.parse_args()

    run_all = not (args.stripe or args.gumroad)
    out: dict = {}

    if run_all or args.stripe:
        try:
            print("[revenue_scraper] Stripe Express…", file=sys.stderr)
            out["stripe_express"] = await scrape_stripe_express(headless=args.headless)
            print(f"  ✓ {out['stripe_express'].get('today_usd', 0):.2f} today, "
                  f"{out['stripe_express'].get('available_to_payout_usd', 0):.2f} available",
                  file=sys.stderr)
        except Exception as e:
            print(f"  ✗ Stripe Express failed: {e}", file=sys.stderr)
            out["stripe_express"] = {"error": str(e),
                                     "scraped_at": dt.datetime.now().astimezone().isoformat()}

    write_revenue(stripe_express=out.get("stripe_express"),
                  gumroad=out.get("gumroad"))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
