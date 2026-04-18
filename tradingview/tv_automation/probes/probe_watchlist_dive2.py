"""Third-pass watchlist probe — captures the per-row REMOVE flow
(hover-reveal vs right-click context menu) and the Open list…
picker dialog structure.
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

        # Open the watchlist sidebar if needed.
        tree = page.locator('[data-name="tree"]').first
        if await tree.count() == 0 or not await tree.is_visible():
            await page.locator('[data-name="base"]').first.click()
            await page.wait_for_timeout(800)

        # 1. Hover a symbol row and capture buttons that appear.
        # Pick a non-active symbol so we don't accidentally remove the
        # one currently being charted. From the prior probe: VX1! is
        # data-active="false".
        hover_data = await page.evaluate(r"""() => {
            const row = document.querySelector(
                '[data-symbol-short="VX1!"]'
            );
            if (!row) return {found: false, reason: 'no_VX1_row'};
            const rect = row.getBoundingClientRect();
            row.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            row.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
            // Wait a tick then snapshot the row's interactive children.
            return new Promise(resolve => {
                setTimeout(() => {
                    // Walk parents up to symbol-list-wrap and capture all
                    // visible buttons whose center sits within the row's
                    // y-range — the X reveals as a sibling, not a child.
                    const top = rect.y, bot = rect.y + rect.height;
                    const allBtns = Array.from(document.querySelectorAll(
                        'button, [role="button"], [data-name]'
                    )).filter(b => {
                        const r = b.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) return false;
                        const cy = r.y + r.height / 2;
                        return cy >= top - 2 && cy <= bot + 2 && r.x > rect.x - 50;
                    });
                    const out = [];
                    allBtns.forEach(b => {
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
                    resolve({found: true, rowRect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}, buttons: out});
                }, 400);
            });
        }""")

        # 2. Right-click context menu on the same row.
        # We need to dispatch contextmenu via JS — Playwright's right-click
        # works too but JS is simpler/more reliable inside a virtualized list.
        await page.evaluate(r"""() => {
            const row = document.querySelector('[data-symbol-short="VX1!"]');
            if (!row) return;
            const r = row.getBoundingClientRect();
            const ev = new MouseEvent('contextmenu', {
                bubbles: true, cancelable: true, view: window,
                button: 2, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2,
            });
            row.dispatchEvent(ev);
        }""")
        await page.wait_for_timeout(600)
        context_menu = await page.evaluate(r"""() => {
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
                const r = it.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                const t = (it.innerText || '').trim();
                if (!t) return;
                items.push({
                    tag: it.tagName,
                    dataName: it.getAttribute('data-name'),
                    text: t.replace(/\s+/g, ' ').slice(0, 80),
                });
            });
            return {found: true, items};
        }""")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # 3. Open the Open list… dialog via the watchlists-button menu.
        await page.locator('[data-name="watchlists-button"]').first.click()
        await page.wait_for_timeout(700)
        # Click the "Open list…" item.
        await page.evaluate(r"""() => {
            const items = Array.from(document.querySelectorAll(
                '[class*="item-jFqVJoPk"]'
            ));
            const target = items.find(it =>
                (it.innerText || '').trim().startsWith('Open list')
            );
            if (target) target.click();
        }""")
        await page.wait_for_timeout(1000)
        open_list_dlg = await page.evaluate(r"""() => {
            const dlgs = Array.from(document.querySelectorAll(
                'div[class*="dialog-"], [data-dialog-name]'
            )).filter(d => {
                const r = d.getBoundingClientRect();
                return r.width > 200 && r.height > 100;
            });
            if (!dlgs.length) return {found: false};
            const dlg = dlgs[dlgs.length - 1];
            const inputs = [];
            dlg.querySelectorAll('input').forEach(i => {
                const r = i.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                inputs.push({
                    placeholder: i.placeholder,
                    ariaLabel: i.getAttribute('aria-label'),
                });
            });
            // Capture every list-item-like element in the dialog.
            const rows = [];
            dlg.querySelectorAll('*').forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width < 100 || r.height < 16 || r.height > 60) return;
                const t = (el.innerText || '').trim();
                if (!t || t.length > 100) return;
                const cls = (el.className || '').toString();
                // Filter to elements that look like single-line list items
                // (avoid the dialog wrapper itself).
                if (t.includes('\n')) return;
                if (cls.includes('button') || cls.includes('input')) return;
                rows.push({
                    tag: el.tagName,
                    dataName: el.getAttribute('data-name'),
                    role: el.getAttribute('role'),
                    text: t.slice(0, 80),
                    classes: cls.split(' ').filter(c => c).slice(0, 4).join(' '),
                });
            });
            // Dedup adjacent rows with same text (parent/child duplicates).
            const seen = new Set();
            const uniq = rows.filter(r => {
                if (seen.has(r.text)) return false;
                seen.add(r.text);
                return true;
            });
            return {
                found: true,
                dialogClass: dlg.className.slice(0, 100),
                dialogName: dlg.getAttribute('data-dialog-name'),
                inputs,
                rows: uniq,
            };
        }""")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"watchlist-dive2-{ts}.json"
        out_path.write_text(json.dumps({
            "hover": hover_data,
            "context_menu": context_menu,
            "open_list_dialog": open_list_dlg,
        }, indent=2))

        print(f"Wrote snapshot to {out_path}", flush=True)
        print(flush=True)
        print("HOVER REVEAL on VX1! row:", flush=True)
        if hover_data.get("found"):
            for b in hover_data["buttons"][:15]:
                print(
                    f"  {b['tag']:6s}  data-name={b['dataName']!r:30s}  "
                    f"aria={b['ariaLabel']!r:25s}  text={b['text']!r}",
                    flush=True,
                )
        print(flush=True)
        print("RIGHT-CLICK CONTEXT MENU:", flush=True)
        if context_menu.get("found"):
            for it in context_menu["items"][:30]:
                print(f"  {it['tag']:5s}  data-name={it['dataName']!r:25s}  text={it['text']!r}", flush=True)
        else:
            print(f"  not found: {context_menu}", flush=True)
        print(flush=True)
        print("OPEN LIST… DIALOG:", flush=True)
        if open_list_dlg.get("found"):
            print(f"  name={open_list_dlg.get('dialogName')!r}", flush=True)
            print(f"  inputs: {open_list_dlg['inputs']}", flush=True)
            print(f"  rows ({len(open_list_dlg['rows'])}):", flush=True)
            for r in open_list_dlg["rows"][:30]:
                print(f"    {r['tag']:5s}  data-name={r['dataName']!r:20s}  text={r['text']!r}  classes={r['classes']!r}", flush=True)

    return 0


if __name__ == "__main__":
    asyncio.run(main())
