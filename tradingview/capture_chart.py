"""
Capture the current TradingView chart for analysis by Claude Code.

No Anthropic API key required — this script just does the browser work:
  1. Preflight → attach to automation Chromium.
  2. Find the active chart tab (or navigate to --symbol / --interval).
  3. Screenshot the chart; pull symbol + interval from the page title.
  4. Write the screenshot and a metadata JSON to pine/captures/.
  5. Print the path to both so Claude Code can read them via Read tool.

Usage:
    .venv/bin/python capture_chart.py
    .venv/bin/python capture_chart.py --symbol NASDAQ:AAPL --interval 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from preflight import ensure_automation_chromium
from session import is_logged_in, tv_context

OUT_DIR = Path(__file__).parent / "pine" / "captures"
CHART_URL = "https://www.tradingview.com/chart/"


async def find_or_open_chart(ctx):
    for p in ctx.pages:
        if "tradingview.com/chart" in p.url:
            await p.bring_to_front()
            return p
    page = await ctx.new_page()
    await page.goto(CHART_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    await page.wait_for_timeout(1500)
    return page


async def extract_metadata(page) -> dict:
    """Pull symbol + interval. The <title> is authoritative for symbol
    (updates on every in-chart symbol change). Interval isn't in the title
    when a saved layout is active, so we query the DOM for the active
    resolution button."""
    title = await page.title()
    url = page.url

    # Title formats observed:
    #   "TSLA 1H chart — TradingView"           (generic page)
    #   "MNQ1! 26,487.25 ▲ +0.46% OC407"         (saved layout active)
    #   "NASDAQ:AAPL 5 chart — TradingView"
    symbol = None
    interval = None
    m = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s+([A-Z0-9]+)\s+chart", title)
    if m:
        symbol = m.group(1)
        interval = m.group(2)
    else:
        # Layout-active title — symbol is the leading token.
        m2 = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s", title)
        if m2:
            symbol = m2.group(1)

    if not symbol:
        um = re.search(r"[?&]symbol=([^&]+)", url)
        if um:
            symbol = um.group(1)
    if not interval:
        um = re.search(r"[?&]interval=([^&]+)", url)
        if um:
            interval = um.group(1)

    # DOM fallback for interval. The top toolbar has a resolution button
    # with data-name="menu-inner" inside an element whose id contains
    # "header-toolbar-intervals". We look for the button's visible text.
    if not interval:
        try:
            interval = await page.evaluate("""() => {
              // Strategy 1: the currently-active interval tab/button.
              const active = document.querySelector(
                '#header-toolbar-intervals button[data-name][class*="isActive"]'
              ) || document.querySelector(
                '[id*="header-toolbar-intervals"] button[aria-pressed="true"]'
              );
              if (active && active.innerText) return active.innerText.trim();
              // Strategy 2: the resolution button that pops the menu.
              const btn = document.querySelector(
                'button[aria-label^="Change interval"], button[id="header-toolbar-intervals"]'
              );
              if (btn && btn.innerText) return btn.innerText.trim();
              return null;
            }""")
        except Exception:
            interval = None

    return {
        "symbol": symbol or "UNKNOWN",
        "interval": interval or "UNKNOWN",
        "url": url,
        "title": title,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description="Capture TV chart for analysis.")
    ap.add_argument("--symbol", help="Override symbol, e.g. NASDAQ:AAPL")
    ap.add_argument("--interval", help="Override interval, e.g. 60")
    args = ap.parse_args()

    await ensure_automation_chromium()

    async with tv_context(headless=False) as ctx:
        page = await find_or_open_chart(ctx)

        if not await is_logged_in(page):
            print("ERROR: not signed in to TradingView.", flush=True)
            return 1

        if args.symbol or args.interval:
            params = []
            if args.symbol:
                params.append(f"symbol={args.symbol}")
            if args.interval:
                params.append(f"interval={args.interval}")
            await page.goto(
                f"{CHART_URL}?{'&'.join(params)}",
                wait_until="domcontentloaded",
            )
            await page.wait_for_selector("canvas", state="visible", timeout=30_000)
            await page.wait_for_timeout(1500)

        meta = await extract_metadata(page)

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", meta["symbol"])
        safe_int = re.sub(r"[^A-Za-z0-9]+", "_", meta["interval"])
        base = OUT_DIR / f"{safe_sym}_{safe_int}_{ts}"
        png = base.with_suffix(".png")
        meta_path = base.with_suffix(".json")

        await page.screenshot(path=str(png), full_page=False)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")

        print(f"Symbol:   {meta['symbol']}")
        print(f"Interval: {meta['interval']}")
        print(f"Screenshot: {png}")
        print(f"Metadata:   {meta_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
