"""ElevenLabs voice-library financial-rewards scraper.

ElevenLabs does not expose voice-library payouts via public API
(verified 10+ endpoints, all 404). The data lives only behind the
Voices → More actions → "View analytics" modal at
https://elevenlabs.io/app/voice-lab. The modal renders a Recharts
area chart whose series we parse out of the SVG path.

Flow:
  1. Open /app/voice-lab in a persistent Chromium profile.
     First run: Dylan logs in once. Cookies persist after.
  2. Click "More actions" on the configured voice row.
  3. Click "View analytics" → Metrics modal opens.
  4. JS-eval: click the chart-type combobox, click "Financial rewards"
     option. Standard `element.click()` doesn't open Radix selects —
     we dispatch a full pointerdown/up/click sequence.
  5. JS-eval: read .recharts-yAxis tick labels (USD scale) and the
     .recharts-area-curve path d attribute. Parse the bezier
     endpoints and linearly map last-point's SVG-y to dollars.

Output overwrites the `elevenlabs_voice_library` block of
config/revenue.json. brain.gather_revenue() reads it.

Use the system Homebrew Python (which already has Playwright);
penelope's own .venv stays slim. The wrapper at
scripts/scrape-revenue.sh routes to the right interpreter.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = Path.home() / "Library" / "Application Support" / "Penelope" / "scraper-profile"
REVENUE_JSON = ROOT / "config" / "revenue.json"
CONFIG_JSON = ROOT / "config" / "config.json"
VOICE_LAB_URL = "https://elevenlabs.io/app/voice-lab"


# This is the JS we inject after the Metrics modal is open. It both
# switches the dropdown to "Financial rewards" and extracts the data
# from the resulting chart. Returns {ok, last_value_usd, points}.
EXTRACT_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // 1. Find the chart-type combobox and switch to "Financial rewards"
  const cbs = [...document.querySelectorAll('[role="combobox"]')];
  const target = cbs.find(b =>
      /Character usage|Financial rewards/.test(b.textContent || ''));
  if (!target) return { ok: false, err: 'combobox not found' };

  if (!/Financial/.test(target.textContent || '')) {
    const rect = target.getBoundingClientRect();
    const ev = (t) => new MouseEvent(t, {
      bubbles: true, cancelable: true, button: 0, pointerType: 'mouse',
      clientX: rect.left + rect.width/2, clientY: rect.top + rect.height/2,
    });
    for (const t of ['pointerdown','mousedown','pointerup','mouseup','click']) {
      target.dispatchEvent(ev(t));
    }
    await sleep(600);
    const opts = [...document.querySelectorAll('[role="option"]')];
    const fr = opts.find(o => /Financial rewards/i.test(o.textContent || ''));
    if (!fr) return { ok: false, err: 'Financial rewards option not in dropdown' };
    const r2 = fr.getBoundingClientRect();
    const ev2 = (t) => new MouseEvent(t, {
      bubbles: true, cancelable: true, button: 0, pointerType: 'mouse',
      clientX: r2.left + r2.width/2, clientY: r2.top + r2.height/2,
    });
    for (const t of ['pointerdown','mousedown','pointerup','mouseup','click']) {
      fr.dispatchEvent(ev2(t));
    }
    await sleep(2500);  // chart re-renders
  }

  // 2. Parse the recharts area curve
  const svg = document.querySelector('.recharts-wrapper svg');
  if (!svg) return { ok: false, err: 'no chart svg' };
  const yTicks = [...svg.querySelectorAll(
    '.recharts-yAxis .recharts-cartesian-axis-tick text')].map(t => ({
      label: parseFloat(t.textContent),
      y: parseFloat(t.getAttribute('y')),
  }));
  if (yTicks.length < 2) return { ok: false, err: 'no y ticks' };
  const xTicks = [...svg.querySelectorAll(
    '.recharts-xAxis .recharts-cartesian-axis-tick-value')]
    .map(t => t.textContent);

  const curve = svg.querySelector('.recharts-area-curve');
  if (!curve) return { ok: false, err: 'no area curve' };
  const d = curve.getAttribute('d') || '';
  const nums = (d.match(/-?[\d.]+/g) || []).map(parseFloat);
  // recharts area curve: "M x0,y0 C cp1, cp2, x1,y1 C cp3, cp4, x2,y2 ..."
  const points = [];
  if (nums.length >= 2) points.push([nums[0], nums[1]]);
  for (let i = 2; i + 5 < nums.length; i += 6) {
    points.push([nums[i+4], nums[i+5]]);
  }
  if (!points.length) return { ok: false, err: 'no points parsed' };
  const t0 = yTicks[0], t1 = yTicks[yTicks.length - 1];
  const yToVal = (y) => t0.label + (y - t0.y) * (t1.label - t0.label) / (t1.y - t0.y);
  const dollars = points.map(p => Math.max(0, yToVal(p[1])));
  return {
    ok: true,
    point_count: points.length,
    last_value_usd: dollars[dollars.length - 1],
    series: dollars.map(v => Math.round(v * 100) / 100),
    x_labels: xTicks,
    y_labels: yTicks.map(t => t.label),
  };
};
"""


async def scrape() -> dict:
    from playwright.async_api import async_playwright

    cfg = json.loads(CONFIG_JSON.read_text())
    voice_name = (cfg.get("elevenlabs") or {}).get("voice_name") or "Dylan - Chill SoCal Male"

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict = {
        "scraped_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "scrape_source": "playwright_recharts_extract",
        "voice_name": voice_name,
    }

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,    # first run: visible so Dylan can log in
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(VOICE_LAB_URL, wait_until="domcontentloaded", timeout=30000)

            # Wait for login if needed (up to 5 min on first run)
            deadline = dt.datetime.now() + dt.timedelta(minutes=5)
            while True:
                if "/sign-in" not in page.url and "/login" not in page.url:
                    try:
                        # Voice list rendered = logged in
                        await page.wait_for_selector(
                            f'text="{voice_name}"', timeout=5000)
                        break
                    except Exception:
                        pass
                if dt.datetime.now() > deadline:
                    raise RuntimeError("not logged in (5 min timeout)")
                await page.wait_for_timeout(2000)

            # Open the More-actions menu next to Dylan's voice
            row = page.locator(
                f'div:has-text("{voice_name}")').filter(
                has=page.locator('button[aria-haspopup="menu"], button:has-text("More actions"), button[aria-label*="actions"]')
            ).first
            # Robust path: find the row by voice text, then the kebab inside it
            voice_row = page.locator('li, [role="listitem"]', has_text=voice_name).first
            menu_btn = voice_row.locator('button').filter(
                has_text="").locator('xpath=./..//button[contains(@aria-label,"More") or contains(@aria-label,"actions")] | xpath=ancestor::*[1]//button[contains(@aria-label,"More")]')
            # Simpler & reliable: query all "More actions" buttons and pick the one whose ancestor li contains the voice name
            await page.evaluate(f"""
              (() => {{
                const wanted = "{voice_name}";
                const buttons = [...document.querySelectorAll('button')];
                const b = buttons.find(btn => {{
                  const label = btn.getAttribute('aria-label') || '';
                  if (!/More|actions/i.test(label)) return false;
                  let n = btn;
                  while (n) {{ if ((n.textContent || '').includes(wanted)) return true; n = n.parentElement; }}
                  return false;
                }});
                if (b) b.click();
              }})();
            """)
            await page.wait_for_timeout(400)

            # Click "View analytics" menuitem
            await page.evaluate("""
              (() => {
                const items = [...document.querySelectorAll('[role="menuitem"]')];
                const a = items.find(i => /View analytics/i.test(i.textContent || ''));
                if (a) a.click();
              })();
            """)
            await page.wait_for_timeout(2500)

            # Switch dropdown + extract chart
            result = await page.evaluate(EXTRACT_JS)
            if not result or not result.get("ok"):
                raise RuntimeError(f"extract failed: {result}")
            out.update({
                "financial_rewards_past_month_usd": round(result["last_value_usd"], 2),
                "point_count": result["point_count"],
                "x_window": (result.get("x_labels") or [None, None])[0] + " → " + (result.get("x_labels") or [None, None, None, None])[-1]
                            if result.get("x_labels") else None,
                "series": result.get("series"),
            })
        finally:
            await ctx.close()

    return out


def write_revenue(elevenlabs: dict) -> None:
    cur = json.loads(REVENUE_JSON.read_text())
    block = cur.get("elevenlabs_voice_library") or {}
    block.update(elevenlabs)
    block["extraction_method"] = "recharts_svg_path_parse"
    cur["elevenlabs_voice_library"] = block
    REVENUE_JSON.write_text(json.dumps(cur, indent=2) + "\n")


async def main():
    print("[elevenlabs scraper] starting…", file=sys.stderr)
    result = await scrape()
    write_revenue(result)
    print(f"  ✓ ${result.get('financial_rewards_past_month_usd', '?')} "
          f"past-month financial rewards", file=sys.stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
