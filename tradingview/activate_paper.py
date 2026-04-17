"""
One-shot Paper Trading activation + selector probe.

Why this exists:
  TradingView's Paper Trading "broker" connection is stored in the *browser
  profile* (localStorage + IndexedDB), not server-side. Activating it in
  Safari does not carry into our Playwright Chromium profile. So we must
  do it inside the same persistent_context that bridge.py will use later.

What it does:
  1. Opens the persistent Chromium profile (visible).
  2. Goes to a chart and clicks the inline BUY button.
  3. If the "select broker" dialog appears, clicks the Paper Trading tile.
  4. Pauses for the user to accept TOS (legally required — a click).
  5. Polls until the order ticket DOM appears.
  6. Dumps every [data-name="..."] inside the order ticket to
     `tradingview/probed_selectors.json` so we can wire bridge.py with
     verified selectors instead of guesses.
  7. Closes cleanly. The next run of bridge.py inherits the activated profile.

Usage:
    .venv/bin/python activate_paper.py
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

# Selectors we already know are stable.
SEL_BUY_INLINE = '[data-name="buy-order-button"]'
SEL_BROKER_DIALOG = '[data-name="select-broker-dialog"]'
# The Paper Trading tile inside the broker picker. The dialog uses a list of
# tiles; Paper Trading is identified by its visible label, which is stable.
SEL_PAPER_TILE = 'div[role="dialog"] >> text=/^Paper Trading$/'

# Order ticket — once activation completes, clicking BUY opens this instead
# of the broker dialog. The container has data-name="order-dialog" on most
# recent TradingView builds, but we handle a few aliases.
SEL_ORDER_TICKET = ', '.join([
    '[data-name="order-dialog"]',
    '[data-name="order-ticket"]',
    '[data-name="iep-dialog-content"]',
    'div[role="dialog"]:has([data-name*="order"])',
])


async def main() -> int:
    print(f"Probe output will be written to: {PROBE_OUT}", flush=True)

    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        print(f"Navigating to {CHART_URL}", flush=True)
        await page.goto(CHART_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2000)

        if not await is_logged_in(page):
            print("ERROR: Not logged in. Run `python login.py` first.", flush=True)
            return 1
        print("Login confirmed.", flush=True)

        # Click the inline BUY button on the chart.
        print(f"Clicking BUY button: {SEL_BUY_INLINE}", flush=True)
        try:
            await page.locator(SEL_BUY_INLINE).first.click(timeout=10_000)
        except PWTimeoutError:
            print("ERROR: Inline BUY button not found. The chart layout may have changed.", flush=True)
            return 2

        await page.wait_for_timeout(1500)

        # Two possibilities now:
        #   (a) Broker picker dialog appeared (Paper Trading not yet activated)
        #   (b) Order ticket appeared (already activated — nothing to do)
        broker_visible = await page.locator(SEL_BROKER_DIALOG).count() > 0
        if broker_visible:
            print("Broker picker is showing — activating Paper Trading...", flush=True)
            try:
                await page.locator(SEL_PAPER_TILE).first.click(timeout=5_000)
            except PWTimeoutError:
                print("ERROR: Could not find Paper Trading tile in dialog.", flush=True)
                # Save a screenshot so we can re-probe by hand.
                await page.screenshot(path="/tmp/tv_activate_dialog.png")
                print("  → Screenshot saved to /tmp/tv_activate_dialog.png", flush=True)
                return 3

            print(flush=True)
            print("=" * 60, flush=True)
            print("USER ACTION REQUIRED in the Chromium window:", flush=True)
            print("  TradingView treats Paper Trading as a 'broker connection'", flush=True)
            print("  so it requires a fresh sign-in even though you're already", flush=True)
            print("  logged into the chart.", flush=True)
            print(flush=True)
            print("  STEP 1: If a Sign Up panel appears, click the small", flush=True)
            print("          'Sign in' link at the BOTTOM (not 'Continue with", flush=True)
            print("          Google' / 'Email' at the top).", flush=True)
            print("  STEP 2: Sign in with your normal TradingView credentials.", flush=True)
            print("  STEP 3: Accept any TOS / disclaimer that follows.", flush=True)
            print(flush=True)
            print("  This script will auto-detect when the order ticket opens.", flush=True)
            print("  Timeout: 10 minutes.", flush=True)
            print("=" * 60, flush=True)
            print(flush=True)

            # Poll up to 10 minutes for the order ticket to appear.
            elapsed = 0
            ticket_handle = None
            while elapsed < 600:
                # If the broker dialog is gone AND order-ticket-ish container
                # is visible, we're past activation.
                ticket_count = await page.locator(SEL_ORDER_TICKET).count()
                broker_still = await page.locator(SEL_BROKER_DIALOG).count()
                if ticket_count > 0 and broker_still == 0:
                    ticket_handle = page.locator(SEL_ORDER_TICKET).first
                    break
                if elapsed % 10 == 0:
                    print(f"  ...waiting for order ticket ({elapsed}s)", flush=True)
                await asyncio.sleep(2)
                elapsed += 2
            else:
                print("ERROR: Order ticket never appeared (timed out).", flush=True)
                await page.screenshot(path="/tmp/tv_activate_timeout.png")
                return 4
        else:
            # Either the order ticket is already up (success), or something
            # else opened. Try to find the ticket directly.
            print("No broker picker — Paper Trading may already be active.", flush=True)
            try:
                await page.wait_for_selector(SEL_ORDER_TICKET, state="visible", timeout=5_000)
                ticket_handle = page.locator(SEL_ORDER_TICKET).first
            except PWTimeoutError:
                print("ERROR: Neither broker picker nor order ticket appeared.", flush=True)
                await page.screenshot(path="/tmp/tv_activate_unknown.png")
                return 5

        # ----- Probe the order-ticket DOM for stable selectors. -----
        print(flush=True)
        print("Order ticket detected. Probing DOM for [data-name] attributes...", flush=True)

        # Pull every element with a data-name inside the ticket and its label/role.
        results = await ticket_handle.evaluate(
            """el => {
                const out = [];
                el.querySelectorAll('[data-name]').forEach(n => {
                    out.push({
                        dataName: n.getAttribute('data-name'),
                        tag: n.tagName.toLowerCase(),
                        role: n.getAttribute('role'),
                        type: n.getAttribute('type'),
                        ariaLabel: n.getAttribute('aria-label'),
                        text: (n.innerText || '').trim().slice(0, 60),
                        placeholder: n.getAttribute('placeholder'),
                    });
                });
                return out;
            }"""
        )

        PROBE_OUT.write_text(json.dumps(results, indent=2))
        print(f"  Wrote {len(results)} entries to {PROBE_OUT}", flush=True)

        # Print the most-likely candidates inline.
        print(flush=True)
        print("Likely qty input candidates:", flush=True)
        for r in results:
            if r.get("tag") == "input" and (
                "qty" in (r.get("dataName") or "").lower()
                or "quantity" in (r.get("dataName") or "").lower()
                or "size" in (r.get("dataName") or "").lower()
            ):
                print(f"  {r}", flush=True)

        print(flush=True)
        print("Likely submit button candidates:", flush=True)
        for r in results:
            text = (r.get("text") or "").lower()
            dn = (r.get("dataName") or "").lower()
            if r.get("tag") == "button" and (
                "submit" in dn or "place" in dn or "confirm" in dn
                or "buy" in text or "sell" in text or "place" in text
            ):
                print(f"  {r}", flush=True)

        await page.screenshot(path="/tmp/tv_order_ticket_active.png", full_page=False)
        print(flush=True)
        print("Screenshot saved: /tmp/tv_order_ticket_active.png", flush=True)
        print("Probe complete.", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
