"""Probe the Strategy Report's List of trades table to identify the
scrollable container. Needed for the virtualization fix in
strategy_tester.trades.
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

        # Open Strategy Report (skip if already open).
        open_btn = page.locator('button[aria-label="Open Strategy Report"]').first
        if await open_btn.count() > 0 and await open_btn.is_visible():
            await open_btn.click()
            await page.wait_for_timeout(1500)
        # Switch to List of trades.
        trades_tab = page.locator('[role="tab"]:has-text("List of trades")').first
        if await trades_tab.count() > 0 and await trades_tab.is_visible():
            await trades_tab.click()
            await page.wait_for_timeout(1500)

        info = await page.evaluate(r"""() => {
            // Find the trades table.
            const tbl = Array.from(document.querySelectorAll('table')).find(t => {
                if (!t.offsetWidth) return false;
                const heads = Array.from(t.querySelectorAll('th'))
                    .map(h => (h.innerText || '').trim().toLowerCase());
                return heads.some(h => h.includes('trade')) || heads.some(h => h.includes('signal'));
            });
            if (!tbl) return {found: false};
            // Walk up ancestors looking for one with overflow-y: auto/scroll
            // and a scrollHeight > clientHeight.
            let p = tbl.parentElement;
            const ancestors = [];
            while (p && p.tagName !== 'BODY' && ancestors.length < 10) {
                const cs = window.getComputedStyle(p);
                ancestors.push({
                    tag: p.tagName,
                    classes: (p.className || '').toString().slice(0, 80),
                    dataName: p.getAttribute('data-name'),
                    overflowY: cs.overflowY,
                    scrollHeight: p.scrollHeight,
                    clientHeight: p.clientHeight,
                    canScroll: p.scrollHeight > p.clientHeight && (cs.overflowY === 'auto' || cs.overflowY === 'scroll'),
                });
                p = p.parentElement;
            }
            const headers = Array.from(tbl.querySelectorAll('thead th, tr:first-child th'))
                .map(h => (h.innerText || '').trim());
            const rowCount = tbl.querySelectorAll('tbody tr, tr:not(:first-child)').length;
            // Sample first 3 rows for attributes.
            const rowSamples = Array.from(tbl.querySelectorAll('tbody tr, tr:not(:first-child)')).slice(0, 3).map(r => {
                const attrs = {};
                Array.from(r.attributes).forEach(a => {
                    if (a.name.startsWith('data-') || a.name === 'role')
                        attrs[a.name] = a.value;
                });
                return {
                    attrs,
                    classes: (r.className || '').toString().slice(0, 80),
                    cells: Array.from(r.querySelectorAll('th, td')).slice(0, 3).map(c => (c.innerText || '').trim().slice(0, 30)),
                };
            });
            return {found: true, headers, rowCount, rowSamples, ancestors};
        }""")

        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"trades-scroll-{ts}.json"
        out_path.write_text(json.dumps(info, indent=2))
        print(f"Wrote snapshot to {out_path}", flush=True)
        print(flush=True)

        if not info.get("found"):
            print("Trades table not found. Is a strategy applied?", flush=True)
            return 1

        print(f"Headers: {info['headers']}", flush=True)
        print(f"Rows in DOM right now: {info['rowCount']}", flush=True)
        print(f"\nRow samples:", flush=True)
        for s in info["rowSamples"]:
            print(f"  attrs={s['attrs']}  cells={s['cells']}", flush=True)
        print(f"\nAncestor scroll candidates:", flush=True)
        for i, a in enumerate(info["ancestors"]):
            marker = "← CAN SCROLL" if a["canScroll"] else ""
            print(
                f"  [{i}] {a['tag']:5s}  data-name={a['dataName']!r:30s}  "
                f"overflowY={a['overflowY']:7s}  "
                f"scroll={a['scrollHeight']}/{a['clientHeight']}  "
                f"classes={a['classes'][:50]!r}  {marker}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    asyncio.run(main())
