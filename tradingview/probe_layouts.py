"""
Side-effect-free probe of TradingView's layout-management UI.

We need to find the [data-name] selectors for:
  - the current layout name button (top-right of header)
  - its dropdown / menu trigger
  - "save as" / "create new layout" menu items
  - the resulting input field for the new layout's name
  - the confirm button

Reads only — no clicks that could mutate state. After probing, the script
clicks the layout-name area to expand its menu, then dumps DOM again.

Output: probed_layouts.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from session import tv_context, is_logged_in

CHART_URL = "https://www.tradingview.com/chart/"
PROBE_OUT = Path(__file__).parent / "probed_layouts.json"


async def dump_top_region(page, label: str) -> list:
    """Dump all [data-name] nodes whose y-coordinate is in the top 80px."""
    items = await page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('[data-name]').forEach(n => {
                const r = n.getBoundingClientRect();
                if (r.y < 80 && r.width > 0 && r.height > 0) {
                    out.push({
                        dataName: n.getAttribute('data-name'),
                        tag: n.tagName.toLowerCase(),
                        ariaLabel: n.getAttribute('aria-label'),
                        title: n.getAttribute('title'),
                        text: (n.innerText || '').trim().slice(0, 60),
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height),
                    });
                }
            });
            // Also any [class*="layout"] in the top region — for fallback.
            document.querySelectorAll('[class*="layout"], [class*="Layout"]').forEach(n => {
                const r = n.getBoundingClientRect();
                if (r.y < 80 && r.width > 0 && r.height > 0 && r.x > 800) {
                    out.push({
                        klass: n.className.slice(0, 80),
                        tag: n.tagName.toLowerCase(),
                        title: n.getAttribute('title'),
                        ariaLabel: n.getAttribute('aria-label'),
                        text: (n.innerText || '').trim().slice(0, 60),
                        x: Math.round(r.x), y: Math.round(r.y),
                    });
                }
            });
            return out;
        }"""
    )
    print(f"\n--- {label} ({len(items)} items) ---", flush=True)
    for it in items:
        print(f"  {it}", flush=True)
    return items


async def dump_visible_dialogs(page, label: str) -> list:
    """Dump role=dialog / role=menu containers."""
    items = await page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('[role="dialog"], [role="menu"], [data-name*="menu"], [data-name*="popup"], [data-name*="Layout"], [data-name*="layout"]').forEach(n => {
                const r = n.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    out.push({
                        dataName: n.getAttribute('data-name'),
                        role: n.getAttribute('role'),
                        tag: n.tagName.toLowerCase(),
                        text: (n.innerText || '').trim().slice(0, 200),
                        x: Math.round(r.x), y: Math.round(r.y),
                    });
                }
            });
            return out;
        }"""
    )
    print(f"\n--- {label} dialogs/menus ({len(items)} items) ---", flush=True)
    for it in items:
        print(f"  {it}", flush=True)
    return items


async def main() -> int:
    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        await page.goto(CHART_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2500)

        if not await is_logged_in(page):
            print("ERROR: not logged in", flush=True)
            return 1

        before_top = await dump_top_region(page, "BEFORE — top toolbar")
        before_dialogs = await dump_visible_dialogs(page, "BEFORE")

        # Try clicking the layout-name button. The most likely candidate is
        # data-name="header-toolbar-save-load" or similar — but we'll let
        # the dump tell us. As a generic attempt, look for any header item
        # whose text matches the current layout name, OR data-name contains
        # 'save'/'load'/'layout'.
        candidates = [c for c in before_top if any(
            s in (c.get("dataName") or "").lower()
            for s in ("save", "load", "layout")
        )]
        print(f"\nLayout-related candidates: {len(candidates)}", flush=True)
        for c in candidates:
            print(f"  → {c}", flush=True)

        # Click the first candidate that looks like a button and dump again.
        clicked = None
        for c in candidates:
            sel = f'[data-name="{c["dataName"]}"]'
            try:
                await page.locator(sel).first.click(timeout=2000)
                clicked = c
                print(f"\nClicked: {sel}", flush=True)
                break
            except Exception as e:
                print(f"Click failed on {sel}: {e}", flush=True)

        if clicked:
            await page.wait_for_timeout(800)
            after_dialogs = await dump_visible_dialogs(page, "AFTER click")
            await page.screenshot(path="/tmp/tv_layouts_after_click.png")
            print("Screenshot → /tmp/tv_layouts_after_click.png", flush=True)
        else:
            after_dialogs = []
            await page.screenshot(path="/tmp/tv_layouts_baseline.png")

        PROBE_OUT.write_text(json.dumps({
            "before_top": before_top,
            "before_dialogs": before_dialogs,
            "clicked": clicked,
            "after_dialogs": after_dialogs,
        }, indent=2))
        print(f"\nFull dump → {PROBE_OUT}", flush=True)

        print("\nHolding browser open 600s.", flush=True)
        await asyncio.sleep(600)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
