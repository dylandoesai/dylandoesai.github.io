"""Thin entry point so the scraper is a one-liner from anywhere:

    python python/run_revenue_scrape.py

Forwards all args to integrations/revenue_scraper.main.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from integrations.revenue_scraper import main  # noqa: E402

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
