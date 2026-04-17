"""
Probe how the inline `qtyEl` quantity widget accepts input.

Hypothesis: clicking qtyEl turns it into an input or contenteditable.
We need to know the post-click selector and how to push a numeric value
without firing a trade.

What it does:
  1. Opens chart, finds [data-name="qtyEl"].
  2. Logs what tag/attrs it has BEFORE click.
  3. Clicks it.
  4. Logs what's now at that location AND the focused element.
  5. Tries pushing keystrokes ('5') to see if it accepts them.
  6. Logs again. Then escapes (no trade fires — the qty change alone
     does not place an order; only clicking BUY/SELL does).
  7. Holds browser open 30 min so the user can verify.

Usage:
    .venv/bin/python probe_qty.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from session import tv_context, is_logged_in

CHART_URL = "https://www.tradingview.com/chart/?symbol=NASDAQ%3AAAPL"
PROBE_OUT = Path(__file__).parent / "probed_qty.json"


async def snapshot(page, label: str) -> dict:
    """Return interesting DOM state for diagnosis."""
    snap = await page.evaluate(
        """() => {
            const out = {};
            const qty = document.querySelector('[data-name="qtyEl"]');
            out.qtyEl = qty ? {
                tag: qty.tagName.toLowerCase(),
                outerHTML: qty.outerHTML.slice(0, 400),
                contentEditable: qty.getAttribute('contenteditable'),
                text: qty.innerText,
            } : null;

            const focused = document.activeElement;
            out.focused = focused ? {
                tag: focused.tagName.toLowerCase(),
                dataName: focused.getAttribute('data-name'),
                contentEditable: focused.getAttribute('contenteditable'),
                type: focused.getAttribute('type'),
                value: focused.value,
                text: focused.innerText ? focused.innerText.slice(0, 80) : null,
                outerHTML: focused.outerHTML ? focused.outerHTML.slice(0, 400) : null,
            } : null;

            // Any inputs anywhere?
            out.allInputs = Array.from(document.querySelectorAll('input')).map(i => ({
                dataName: i.getAttribute('data-name'),
                type: i.type,
                value: i.value,
                name: i.name,
                placeholder: i.placeholder,
            }));

            // Any visible contenteditable?
            out.contentEditables = Array.from(document.querySelectorAll('[contenteditable="true"]')).slice(0, 5).map(c => ({
                tag: c.tagName.toLowerCase(),
                dataName: c.getAttribute('data-name'),
                text: (c.innerText || '').slice(0, 80),
            }));

            return out;
        }"""
    )
    print(f"\n--- {label} ---", flush=True)
    print(json.dumps(snap, indent=2), flush=True)
    return snap


async def main() -> int:
    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        await page.goto(CHART_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2000)

        if not await is_logged_in(page):
            print("ERROR: not logged in", flush=True)
            return 1

        before = await snapshot(page, "BEFORE click")

        # Click qtyEl to enter edit mode.
        qty_el = page.locator('[data-name="qtyEl"]').first
        if await qty_el.count() == 0:
            print("ERROR: qtyEl not present", flush=True)
            return 2

        await qty_el.click()
        await page.wait_for_timeout(500)
        after_click = await snapshot(page, "AFTER click")

        # Try pushing keystrokes — select-all then type. This should NOT
        # place a trade by itself (only Buy/Sell click does).
        await page.keyboard.press("Meta+A")
        await page.keyboard.type("5")
        await page.wait_for_timeout(300)
        after_type = await snapshot(page, "AFTER typing '5'")

        # Press Tab to commit (some widgets only commit on blur).
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(500)
        after_tab = await snapshot(page, "AFTER Tab")

        PROBE_OUT.write_text(json.dumps({
            "before": before,
            "after_click": after_click,
            "after_type": after_type,
            "after_tab": after_tab,
        }, indent=2))
        print(f"\nFull dump → {PROBE_OUT}", flush=True)

        await page.screenshot(path="/tmp/tv_qty_after.png")
        print("Screenshot → /tmp/tv_qty_after.png", flush=True)

        print("\nHolding 1800s. Browser open. NO TRADE FIRED (we never clicked BUY/SELL).", flush=True)
        await asyncio.sleep(1800)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
