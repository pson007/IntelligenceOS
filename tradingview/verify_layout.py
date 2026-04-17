"""Quick verification: print the currently-active layout name."""

from __future__ import annotations

import asyncio
import sys

from session import tv_context, is_logged_in

CHART_URL = "https://www.tradingview.com/chart/"


async def main() -> int:
    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        await page.goto(CHART_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2000)

        if not await is_logged_in(page):
            print("ERROR: not logged in", flush=True)
            return 1

        # The current layout name appears in the browser tab title AND in
        # an element near the save-load-menu button. The tab title is the
        # simplest reliable source.
        title = await page.title()
        print(f"Tab title: {title!r}", flush=True)

        # Also dump anything near save-load-menu with text content.
        nearby = await page.evaluate(
            """() => {
                const out = [];
                const btn = document.querySelector('[data-name="save-load-menu"]');
                if (!btn) return out;
                const r = btn.getBoundingClientRect();
                document.querySelectorAll('div, span, button').forEach(n => {
                    const nr = n.getBoundingClientRect();
                    if (Math.abs(nr.y - r.y) < 40 && nr.x > r.x - 300 && nr.x < r.x
                        && nr.width > 30 && nr.width < 250) {
                        const t = (n.innerText || '').trim();
                        if (t && t.length < 60) {
                            out.push({ text: t, x: Math.round(nr.x), w: Math.round(nr.width) });
                        }
                    }
                });
                return out;
            }"""
        )
        print("Text near the layout-menu button:", flush=True)
        seen = set()
        for n in nearby:
            if n["text"] in seen:
                continue
            seen.add(n["text"])
            print(f"  x={n['x']:4d}  w={n['w']:3d}  text={n['text']!r}", flush=True)

        # Open the layouts menu and list the "RECENTLY USED" layouts so we
        # can see whether OC109 actually exists.
        await page.locator('[data-name="save-load-menu"]').first.click()
        await page.wait_for_timeout(800)
        popup_text = await page.evaluate(
            """() => {
                const popup = document.querySelector('[class*="menuBox-"]');
                return popup ? popup.innerText : null;
            }"""
        )
        print("\nLayouts menu contents:", flush=True)
        print(popup_text, flush=True)

        await page.screenshot(path="/tmp/tv_verify_menu.png")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
