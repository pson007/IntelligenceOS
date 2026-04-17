"""
Side-effect-free DOM dump of TradingView's chart page.

Why this exists:
  We discovered that `[data-name="buy-order-button"]` fires a market order
  instantly — there is no ticket to fill. So we need to find:
    (a) the top-toolbar quantity input that sets order size, and
    (b) the inline BUY / SELL button pair (already known but confirm),
  *without* clicking anything that could place a trade.

What it does:
  1. Opens chart with the persistent profile.
  2. Opens the Trading Panel at the bottom (clicking a *tab*, not a Buy
     button — clicking a tab is harmless).
  3. Dumps EVERY `[data-name]` element on the page to a JSON file, with
     enough context (tag, role, aria-label, text, placeholder) to identify
     the qty input.
  4. Filters and prints the most-likely candidates for: qty input, buy
     button, sell button, panel toggle.
  5. Holds browser open (45 min) so the user can poke around.

No clicks fire trades. Safe to run repeatedly.

Usage:
    .venv/bin/python probe_full.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from session import tv_context, is_logged_in

CHART_URL = "https://www.tradingview.com/chart/?symbol=NASDAQ%3AAAPL"
PROBE_OUT = Path(__file__).parent / "probed_selectors.json"
HOLD_OPEN_S = 2700


async def main() -> int:
    print(f"DOM dump → {PROBE_OUT}", flush=True)

    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        await page.goto(CHART_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2000)

        if not await is_logged_in(page):
            print("ERROR: Not logged in.", flush=True)
            return 1
        print("Login confirmed.", flush=True)

        # Try to expand the Trading Panel so its qty/buy/sell controls are
        # in the DOM. Clicking the "Paper Trading" tab at the bottom toggles
        # the panel without firing a trade.
        try:
            paper_tab = page.locator('[data-name="bottom-area-toggle"], '
                                     'div[data-name*="bottom"]:has-text("Paper Trading"), '
                                     'button:has-text("Paper Trading")').first
            if await paper_tab.count() > 0:
                await paper_tab.click(timeout=3000)
                await page.wait_for_timeout(1500)
                print("Clicked Paper Trading tab to open trading panel.", flush=True)
        except Exception as e:
            print(f"Could not open trading panel (continuing anyway): {e}", flush=True)

        # Dump all data-name elements on the entire page.
        results = await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('[data-name]').forEach(n => {
                    const rect = n.getBoundingClientRect();
                    out.push({
                        dataName: n.getAttribute('data-name'),
                        tag: n.tagName.toLowerCase(),
                        role: n.getAttribute('role'),
                        type: n.getAttribute('type'),
                        ariaLabel: n.getAttribute('aria-label'),
                        text: (n.innerText || '').trim().slice(0, 80),
                        placeholder: n.getAttribute('placeholder'),
                        visible: rect.width > 0 && rect.height > 0,
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                    });
                });
                return out;
            }"""
        )
        PROBE_OUT.write_text(json.dumps(results, indent=2))
        print(f"\nWrote {len(results)} entries → {PROBE_OUT}", flush=True)

        def show(label, predicate, limit=15):
            matches = [r for r in results if predicate(r)]
            print(f"\n{label} ({len(matches)} match):", flush=True)
            for r in matches[:limit]:
                print(f"  {r}", flush=True)

        show("All <input> elements (qty input candidates)",
             lambda r: r["tag"] == "input" and r["visible"])

        show("Buy/Sell-named elements",
             lambda r: any(s in (r["dataName"] or "").lower()
                           for s in ("buy", "sell")) and r["visible"])

        show("Bottom-area / panel toggles",
             lambda r: any(s in (r["dataName"] or "").lower()
                           for s in ("bottom", "panel", "trading", "broker")) and r["visible"])

        show("Quantity-related",
             lambda r: any(s in (r["dataName"] or "").lower()
                           for s in ("qty", "quantity", "size", "amount")))

        await page.screenshot(path="/tmp/tv_probe_full.png", full_page=True)
        print("\nFull-page screenshot → /tmp/tv_probe_full.png", flush=True)
        print(f"\nDONE. Holding browser open {HOLD_OPEN_S}s.", flush=True)
        await asyncio.sleep(HOLD_OPEN_S)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
