#!/usr/bin/env bash
# Run the revenue scraper using the system Playwright install
# (Homebrew Python 3.14, which already has playwright + chromium).
# Penelope's own .venv is intentionally NOT used here so we don't
# bloat its requirements with another Chromium download.

set -euo pipefail
cd "$(dirname "$0")/.."

SYSTEM_PY="/opt/homebrew/opt/python@3.14/bin/python3.14"
if [ ! -x "$SYSTEM_PY" ]; then
  SYSTEM_PY="/opt/homebrew/bin/python3"
fi

exec "$SYSTEM_PY" python/run_revenue_scrape.py "$@"
