"""Probe the TradingView screener page.

Goal: catalog selectors for the screener UI — table container, header
columns, body rows, filter button(s), preset/saved-screen menu, type
selector (stocks/crypto/forex/futures).

Run:
    python -m tv_automation.probes.probe_screener
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from preflight import ensure_automation_chromium
from session import tv_context

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
SCREENER_URL = "https://www.tradingview.com/screener/"


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        # Reuse an existing screener tab if one is open, else open one.
        page = None
        for p in ctx.pages:
            try:
                if "tradingview.com/screener" in p.url:
                    page = p
                    await p.bring_to_front()
                    break
            except Exception:
                continue
        if page is None:
            page = await ctx.new_page()
            await page.goto(SCREENER_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)  # let the screener hydrate

        info = await page.evaluate(r"""() => {
            const out = {
                url: window.location.href,
                title: document.title,
                tables: [],
                buttons: [],
                inputs: [],
                tabs: [],
                dataNames: [],
                ariaLabels: [],
                screenerHints: {},
            };

            // Find the screener container — TV uses class prefixes like
            // "container-" + "screener-".
            const containerCandidates = [
                'div[class*="screener-"]',
                'div[class*="screenerContainer"]',
                '[data-name="screener"]',
                '.tv-screener',
            ];
            let container = null;
            for (const sel of containerCandidates) {
                const el = document.querySelector(sel);
                if (el && el.offsetWidth > 200) { container = el; break; }
            }
            out.screenerHints.containerFound = !!container;
            if (container) {
                out.screenerHints.containerClass = (container.className || '').toString().slice(0, 120);
            }
            const root = container || document.body;

            // Tables: capture header structure + row count.
            root.querySelectorAll('table').forEach((tbl, i) => {
                const headers = Array.from(tbl.querySelectorAll('th'))
                    .map(h => (h.innerText || '').trim().slice(0, 30));
                const rowCount = tbl.querySelectorAll('tbody tr').length;
                out.tables.push({
                    index: i,
                    rowCount,
                    headers: headers.slice(0, 15),
                    classes: (tbl.className || '').toString().slice(0, 60),
                });
            });

            // Visible buttons in the screener container.
            root.querySelectorAll('button').forEach(b => {
                const r = b.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                out.buttons.push({
                    dataName: b.getAttribute('data-name'),
                    ariaLabel: b.getAttribute('aria-label'),
                    title: b.getAttribute('title'),
                    text: (b.innerText || '').trim().slice(0, 60),
                    classes: (b.className || '').toString().slice(0, 60),
                });
            });

            // Inputs (filter inputs, search).
            root.querySelectorAll('input').forEach(inp => {
                const r = inp.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                out.inputs.push({
                    type: inp.type,
                    placeholder: inp.placeholder,
                    name: inp.name,
                    ariaLabel: inp.getAttribute('aria-label'),
                    dataName: inp.getAttribute('data-name'),
                });
            });

            // Tabs (likely Stocks/Crypto/Forex/Futures).
            root.querySelectorAll('[role="tab"], [class*="tab-"]').forEach(t => {
                const r = t.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                out.tabs.push({
                    role: t.getAttribute('role'),
                    dataName: t.getAttribute('data-name'),
                    ariaLabel: t.getAttribute('aria-label'),
                    text: (t.innerText || '').trim().slice(0, 50),
                });
            });

            // All [data-name]s in the screener container — for selector cataloging.
            root.querySelectorAll('[data-name]').forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                out.dataNames.push({
                    dataName: el.getAttribute('data-name'),
                    tag: el.tagName,
                    text: (el.innerText || '').trim().slice(0, 40).replace(/\s+/g, ' '),
                });
            });

            // All [aria-label]s for fallback selectors.
            root.querySelectorAll('[aria-label]').forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                out.ariaLabels.push({
                    ariaLabel: el.getAttribute('aria-label'),
                    tag: el.tagName,
                });
            });
            // Dedup ariaLabels.
            const seen = new Set();
            out.ariaLabels = out.ariaLabels.filter(a => {
                if (seen.has(a.ariaLabel)) return false;
                seen.add(a.ariaLabel);
                return true;
            });

            return out;
        }""")

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"screener-{ts}.json"
        out_path.write_text(json.dumps(info, indent=2))

        print(f"Wrote snapshot to {out_path}", flush=True)
        print(f"URL: {info['url']}", flush=True)
        print(f"Title: {info['title']}", flush=True)
        print(f"Container found: {info['screenerHints'].get('containerFound')}", flush=True)
        if info['screenerHints'].get('containerClass'):
            print(f"  class: {info['screenerHints']['containerClass']}", flush=True)
        print(flush=True)
        print(f"Tables ({len(info['tables'])}):", flush=True)
        for t in info["tables"]:
            print(f"  [{t['index']}] rows={t['rowCount']}  headers={t['headers'][:6]}  classes={t['classes'][:50]!r}", flush=True)
        print(flush=True)
        print(f"Tabs ({len(info['tabs'])}):", flush=True)
        for t in info["tabs"][:15]:
            print(f"  data-name={t['dataName']!r:25s}  role={t['role']!r:6s}  text={t['text']!r}", flush=True)
        print(flush=True)
        print(f"Buttons (first 30 of {len(info['buttons'])}):", flush=True)
        for b in info["buttons"][:30]:
            print(f"  data-name={b['dataName']!r:30s}  aria={b['ariaLabel']!r:25s}  text={b['text']!r}", flush=True)
        print(flush=True)
        print(f"Inputs ({len(info['inputs'])}):", flush=True)
        for inp in info["inputs"]:
            print(f"  placeholder={inp['placeholder']!r:30s}  aria={inp['ariaLabel']!r}", flush=True)
        print(flush=True)
        print(f"Unique [data-name]s ({len({d['dataName'] for d in info['dataNames']})}):", flush=True)
        seen = set()
        for d in info["dataNames"]:
            if d["dataName"] in seen:
                continue
            seen.add(d["dataName"])
            print(f"  data-name={d['dataName']!r:30s}  tag={d['tag']:6s}  text={d['text'][:40]!r}", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
