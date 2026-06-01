---
description: Scrape Dylan's Stripe Express (and later Gumroad) dashboards and update config/revenue.json. Use when he asks for fresh revenue numbers or for a daily check-in.
---

Run the Penelope revenue scraper end-to-end.

Steps:

1. From repo root `~/dylandoesai.github.io/penelope/`, activate the venv:
   `source .venv/bin/activate`
2. Run: `python python/run_revenue_scrape.py`
3. If it prints `not logged in (5 min timeout)`, tell Dylan the Playwright
   window is open — he needs to log into Stripe Express once. Cookies
   persist in `~/Library/Application Support/Penelope/scraper-profile/`,
   so subsequent runs are silent.
4. After it completes, read back `config/revenue.json` → `stripe_express`
   block and summarize for him in one sentence: today's total, available
   balance, last payout.

Pass `--headless` to attempt a no-window run (only works after first login).
Pass `--stripe` or `--gumroad` to scope to one source.
