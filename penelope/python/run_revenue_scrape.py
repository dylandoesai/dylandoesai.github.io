"""Entry point for the daily revenue scrape.

Currently scrapes:
  - ElevenLabs voice-library financial rewards (chart → SVG path → USD)

Use:  bash scripts/scrape-revenue.sh
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from integrations.elevenlabs_dashboard_scraper import main as elevenlabs_main  # noqa: E402


async def main():
    await elevenlabs_main()


if __name__ == "__main__":
    asyncio.run(main())
