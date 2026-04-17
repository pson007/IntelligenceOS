"""
Dump the exact text and selectors of items in the layout dropdown.
Non-destructive — only opens the menu, reads, and holds.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from session import tv_context, is_logged_in

CHART_URL = "https://www.tradingview.com/chart/"
PROBE_OUT = Path(__file__).parent / "probed_layout_menu.json"


async def main() -> int:
    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        await page.goto(CHART_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2500)

        if not await is_logged_in(page):
            return 1

        # Open the layout menu.
        await page.locator('[data-name="save-load-menu"]').first.click()
        await page.wait_for_timeout(800)

        # Dump every clickable-ish element that appeared top-right after click.
        items = await page.evaluate(
            """() => {
                const out = [];
                // Look for menu-like containers. TradingView uses a portaled
                // popup container, often a div with class containing 'menu'.
                const popups = document.querySelectorAll(
                    '[class*="menuBox"], [class*="menuWrap"], [class*="popup"], ' +
                    '[data-name*="menu-inner"], [data-name*="submenu"]'
                );
                popups.forEach(p => {
                    const r = p.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        out.push({
                            type: 'popup-container',
                            klass: p.className.slice(0, 120),
                            dataName: p.getAttribute('data-name'),
                            tag: p.tagName.toLowerCase(),
                            x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height),
                            preview: (p.innerText || '').slice(0, 300),
                        });
                    }
                });
                // Dump ALL visible elements with text in the top-right
                // quadrant (x > 1000, y > 30, y < 800), which is where the
                // dropdown lives.
                document.querySelectorAll('div, button, a, span').forEach(n => {
                    const r = n.getBoundingClientRect();
                    if (r.x > 1000 && r.y > 30 && r.y < 800 && r.width > 0 && r.height > 0) {
                        const txt = (n.innerText || '').trim();
                        if (txt && txt.length < 80 && n.children.length < 4) {
                            out.push({
                                type: 'menu-item-candidate',
                                tag: n.tagName.toLowerCase(),
                                dataName: n.getAttribute('data-name'),
                                role: n.getAttribute('role'),
                                klass: (n.className || '').toString().slice(0, 80),
                                text: txt,
                                x: Math.round(r.x), y: Math.round(r.y),
                            });
                        }
                    }
                });
                return out;
            }"""
        )
        PROBE_OUT.write_text(json.dumps(items, indent=2))
        print(f"Wrote {len(items)} items → {PROBE_OUT}", flush=True)

        print("\n--- popup containers ---", flush=True)
        for it in items:
            if it.get("type") == "popup-container":
                print(f"  {it}", flush=True)

        print("\n--- menu-item candidates (deduped by text) ---", flush=True)
        seen = set()
        for it in items:
            if it.get("type") == "menu-item-candidate":
                key = it["text"]
                if key in seen:
                    continue
                seen.add(key)
                print(f"  y={it['y']:4d}  [{it['tag']}] text={it['text']!r}  "
                      f"dataName={it['dataName']}  class={it['klass']}", flush=True)

        await page.screenshot(path="/tmp/tv_layout_menu_dump.png")
        print("\nHolding 300s.", flush=True)
        await asyncio.sleep(300)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
