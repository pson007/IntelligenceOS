"""Probe the watchlist row remove-X path with real Playwright pointer
events.

Earlier dive2 probe found that JS-dispatched mouseenter/mouseover
doesn't reveal TV's hover-only X button (same React-handler pattern
from the indicators legend §7c). Try Playwright's `hover()` which
fires real pointer events.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from preflight import ensure_automation_chromium
from session import tv_context

from ..lib.context import find_or_open_chart

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await find_or_open_chart(ctx)
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(800)

        # Close the Pine Editor first if open. Monaco's various
        # overlays (view-lines, decorationsOverviewRuler) sit in the
        # overlap-manager-root z-stack and intercept pointer events
        # targeting other panels. Use force=True since the same overlay
        # blocks our path to the Pine toolbar button.
        pine_btn = page.locator('[data-name="pine-dialog-button"]').first
        monaco = page.locator('.pine-editor-monaco').first
        if await monaco.count() > 0 and await monaco.is_visible():
            await pine_btn.click(force=True)
            await page.wait_for_timeout(800)

        # Open the watchlist sidebar if needed.
        tree = page.locator('[data-name="tree"]').first
        if await tree.count() == 0 or not await tree.is_visible():
            await page.locator('[data-name="base"]').first.click(force=True)
            await page.wait_for_timeout(800)

        # Pick a target row — VX1! was non-active in the prior dive.
        # If absent, fall back to the last symbol in the list.
        target_symbol = await page.evaluate(r"""() => {
            const tree = document.querySelector('[data-name="tree"]');
            if (!tree) return null;
            const seen = new Set();
            const all = [];
            tree.querySelectorAll('[data-symbol-short]').forEach(el => {
                const s = el.getAttribute('data-symbol-short');
                const active = el.getAttribute('data-active') === 'true';
                if (!s || seen.has(s)) return;
                seen.add(s);
                all.push({s, active});
            });
            const inactive = all.filter(x => !x.active);
            return inactive.length ? inactive[inactive.length - 1].s : (all[0] || {}).s;
        }""")
        print(f"Target symbol: {target_symbol}", flush=True)
        if not target_symbol:
            print("No symbols in the watchlist to probe with.", flush=True)
            return 1

        # Scroll the row into view so it's a real hover target.
        await page.evaluate(r"""(sym) => {
            const row = document.querySelector(`[data-symbol-short="${CSS.escape(sym)}"]`);
            if (row) row.scrollIntoView({block: 'center'});
        }""", target_symbol)
        await page.wait_for_timeout(300)

        # Position the real cursor over the row's center via raw
        # mouse.move() — bypasses Playwright's actionability hit-test
        # (Monaco's overlay claims the hit at any other element). Real
        # cursor position triggers TV's CSS `:hover` reveal.
        rect = await page.evaluate(r"""(sym) => {
            const row = document.querySelector(`[data-symbol-short="${CSS.escape(sym)}"]`);
            if (!row) return null;
            const r = row.getBoundingClientRect();
            return {x: r.x + r.width / 2, y: r.y + r.height / 2};
        }""", target_symbol)
        if rect is None:
            print("Row vanished before probe.", flush=True)
            return 1
        await page.mouse.move(rect["x"], rect["y"])
        await page.wait_for_timeout(600)
        row = page.locator(f'[data-symbol-short="{target_symbol}"]').first

        # Snapshot any newly-visible buttons in/near the row's bounding box.
        info = await page.evaluate(r"""(sym) => {
            const row = document.querySelector(`[data-symbol-short="${CSS.escape(sym)}"]`);
            if (!row) return {found: false};
            const rb = row.getBoundingClientRect();
            const top = rb.y - 4, bot = rb.y + rb.height + 4;
            const left = rb.x - 8, right = rb.x + rb.width + 200;

            // All visible buttons / [role="button"] / [data-name] elements
            // whose center sits within the row's expanded bounds.
            const all = Array.from(document.querySelectorAll(
                'button, [role="button"], [data-name], [class*="remove"], [class*="delete"], [class*="close"]'
            )).filter(b => {
                const r = b.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return false;
                const cy = r.y + r.height / 2;
                const cx = r.x + r.width / 2;
                return cy >= top && cy <= bot && cx >= left && cx <= right;
            });
            const dedup = new Set();
            const out = [];
            all.forEach(b => {
                const key = b.tagName + '|' + (b.className || '').toString().slice(0, 60);
                if (dedup.has(key)) return;
                dedup.add(key);
                const r = b.getBoundingClientRect();
                out.push({
                    tag: b.tagName,
                    dataName: b.getAttribute('data-name'),
                    ariaLabel: b.getAttribute('aria-label'),
                    title: b.getAttribute('title'),
                    text: (b.innerText || '').trim().slice(0, 40),
                    classes: (b.className || '').toString().slice(0, 80),
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                });
            });
            return {found: true, rowRect: {x: Math.round(rb.x), y: Math.round(rb.y), w: Math.round(rb.width), h: Math.round(rb.height)}, buttons: out};
        }""", target_symbol)

        # Right-click via raw mouse.click — fires the full contextmenu
        # event (mousedown + mouseup + contextmenu) at the position.
        await page.mouse.click(rect["x"], rect["y"], button="right")
        await page.wait_for_timeout(800)
        ctx_menu = await page.evaluate(r"""() => {
            const popups = Array.from(document.querySelectorAll(
                '[class*="menuBox-"], div[role="menu"]'
            )).filter(p => {
                const r = p.getBoundingClientRect();
                return r.width > 80 && r.height > 40;
            });
            if (!popups.length) return {found: false};
            const popup = popups[popups.length - 1];
            const items = [];
            popup.querySelectorAll('[class*="item-jFqVJoPk"], [role="menuitem"]').forEach(it => {
                const t = (it.innerText || '').trim();
                if (!t) return;
                items.push({
                    tag: it.tagName,
                    dataName: it.getAttribute('data-name'),
                    text: t.replace(/\s+/g, ' ').slice(0, 80),
                });
            });
            return {found: true, items, popupClass: popup.className.slice(0, 80)};
        }""")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)

        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"watchlist-remove-{ts}.json"
        out_path.write_text(json.dumps({
            "target_symbol": target_symbol,
            "hover_buttons": info,
            "right_click_menu": ctx_menu,
        }, indent=2))
        print(f"Wrote snapshot to {out_path}", flush=True)
        print(flush=True)

        if info.get("found"):
            print(f"HOVER on {target_symbol!r} row (bounds {info['rowRect']}):", flush=True)
            for b in info["buttons"][:20]:
                print(
                    f"  {b['tag']:6s} data-name={b['dataName']!r:25s} aria={b['ariaLabel']!r:25s} title={b['title']!r:15s} text={b['text']!r}",
                    flush=True,
                )
                print(f"         classes={b['classes'][:80]!r}", flush=True)
        print(flush=True)
        if ctx_menu.get("found"):
            print(f"RIGHT-CLICK on {target_symbol!r}:", flush=True)
            for it in ctx_menu["items"][:30]:
                print(f"  data-name={it['dataName']!r:25s}  text={it['text']!r}", flush=True)
        else:
            print("RIGHT-CLICK menu: NOT FOUND", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
