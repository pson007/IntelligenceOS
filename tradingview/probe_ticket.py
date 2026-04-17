"""
Probe the order-ticket DOM after Paper Trading is already activated.

Run AFTER `activate_paper.py` has succeeded (i.e. the bottom of the chart
shows a `Paper Trading` tab — meaning the persistent profile now has the
broker connection saved).

What it does:
  1. Opens the persistent Chromium profile (already logged in, Paper
     Trading already wired).
  2. Goes to AAPL chart, clicks the inline BUY button.
  3. Order ticket should open directly (no broker picker, no sign-in).
  4. Dumps every [data-name] inside the ticket to probed_selectors.json.
  5. Holds the browser window open for 30 minutes so the user does NOT
     have to sign in again if they want to use it.

Usage:
    .venv/bin/python probe_ticket.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import TimeoutError as PWTimeoutError

from session import tv_context, is_logged_in

CHART_URL = "https://www.tradingview.com/chart/?symbol=NASDAQ%3AAAPL"
PROBE_OUT = Path(__file__).parent / "probed_selectors.json"

SEL_BUY_INLINE = '[data-name="buy-order-button"]'
SEL_BROKER_DIALOG = '[data-name="select-broker-dialog"]'
SEL_ORDER_TICKET = ', '.join([
    '[data-name="order-dialog"]',
    '[data-name="order-ticket"]',
    '[data-name="iep-dialog-content"]',
    'div[role="dialog"]:has([data-name*="order"])',
    'div[role="dialog"]:has-text("Quantity")',
    'div[role="dialog"]:has-text("Buying Power")',
])

# Hold the browser open this long after probing so the user keeps state.
# 30 min is more than enough to wire the rest of the pipeline.
HOLD_OPEN_S = 1800


async def main() -> int:
    print(f"Probe output → {PROBE_OUT}", flush=True)

    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        await page.goto(CHART_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2000)

        if not await is_logged_in(page):
            print("ERROR: Not logged in. Re-run login.py first.", flush=True)
            return 1
        print("Login confirmed (no re-auth needed — using saved profile).", flush=True)

        # Sanity check: is the Paper Trading tab visible at the bottom?
        # If yes, activation persisted.
        paper_tab = await page.locator('text=/^Paper Trading$/').count()
        print(f"Paper Trading tab visible at bottom: {paper_tab > 0}", flush=True)

        # Click BUY on the chart.
        print(f"Clicking {SEL_BUY_INLINE}...", flush=True)
        await page.locator(SEL_BUY_INLINE).first.click(timeout=10_000)
        await page.wait_for_timeout(1500)

        # If broker picker comes up, activation actually didn't persist.
        if await page.locator(SEL_BROKER_DIALOG).count() > 0:
            print("ERROR: Broker picker still showing — Paper Trading NOT activated.", flush=True)
            await page.screenshot(path="/tmp/tv_probe_broker_again.png")
            return 2

        # Wait for the order ticket.
        print("Waiting for order ticket to appear...", flush=True)
        try:
            await page.wait_for_selector(SEL_ORDER_TICKET, state="visible", timeout=15_000)
        except PWTimeoutError:
            print("ERROR: Order ticket selector not found. Saving DOM dump.", flush=True)
            await page.screenshot(path="/tmp/tv_probe_no_ticket.png")
            # Dump every visible dialog so we can see what DID appear.
            dialogs = await page.evaluate(
                """() => Array.from(document.querySelectorAll('div[role="dialog"]')).map(d => ({
                    dataName: d.getAttribute('data-name'),
                    text: (d.innerText || '').slice(0, 200),
                }))"""
            )
            print(f"Visible dialogs: {json.dumps(dialogs, indent=2)}", flush=True)
            return 3

        ticket = page.locator(SEL_ORDER_TICKET).first

        # Probe the DOM.
        results = await ticket.evaluate(
            """el => {
                const out = [];
                el.querySelectorAll('[data-name]').forEach(n => {
                    out.push({
                        dataName: n.getAttribute('data-name'),
                        tag: n.tagName.toLowerCase(),
                        role: n.getAttribute('role'),
                        type: n.getAttribute('type'),
                        ariaLabel: n.getAttribute('aria-label'),
                        text: (n.innerText || '').trim().slice(0, 80),
                        placeholder: n.getAttribute('placeholder'),
                    });
                });
                return out;
            }"""
        )
        PROBE_OUT.write_text(json.dumps(results, indent=2))
        print(f"\nWrote {len(results)} entries → {PROBE_OUT}", flush=True)

        # Print likely candidates.
        print("\nLikely qty input:", flush=True)
        for r in results:
            if r.get("tag") == "input":
                print(f"  {r}", flush=True)

        print("\nLikely buttons:", flush=True)
        for r in results:
            if r.get("tag") == "button":
                print(f"  {r}", flush=True)

        await page.screenshot(path="/tmp/tv_order_ticket_active.png")
        print("\nScreenshot → /tmp/tv_order_ticket_active.png", flush=True)
        print(f"\nProbe complete. Holding browser open for {HOLD_OPEN_S}s "
              f"so you don't lose state. Close at any time by killing this script.",
              flush=True)
        await asyncio.sleep(HOLD_OPEN_S)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
