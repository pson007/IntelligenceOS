"""Probe the right-sidebar Watchlist widget.

Goal: catalog the selectors needed for `watchlist.py` — sidebar icon,
widget container, list-selector dropdown, symbol rows (with their
data-symbol attributes), the add-symbol input, and per-row hover-reveal
actions (remove, reorder).

Defensive on purpose: dumps every visible button, data-name, aria-label,
and role-bearing element inside the right-sidebar widgetbar — we pick
the stable selectors after looking at the snapshot.

Run with the chart open:
    python -m tv_automation.probes.probe_watchlist
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
        await page.wait_for_timeout(1500)

        # Step 1 — dump every right-sidebar widgetbar icon, so we can
        # pick the watchlist's `data-name` even if it isn't called
        # "watchlist" in the DOM (it may be "base" or a localized label).
        widgetbar_icons = await page.evaluate(r"""() => {
            const bar = document.querySelector(
                '[class*="widgetbar-"], [data-name="right-toolbar"]'
            );
            if (!bar) return {found: false};
            const out = [];
            bar.querySelectorAll('[data-name], button, [role="button"]').forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                out.push({
                    tag: el.tagName,
                    dataName: el.getAttribute('data-name'),
                    ariaLabel: el.getAttribute('aria-label'),
                    title: el.getAttribute('title'),
                    text: (el.innerText || '').trim().slice(0, 40),
                    classes: (el.className || '').toString().slice(0, 80),
                });
            });
            return {found: true, icons: out};
        }""")

        # Step 2 — try common candidates for the watchlist toggle. TV
        # historically used `[data-name="base"]` for the watchlist
        # widget, but it may be different on Pro+ tier. Try several.
        candidates = [
            '[data-name="base"]',
            '[data-name="watchlists"]',
            '[data-name="watchlist"]',
            'button[aria-label*="atchlist" i]',
            '[data-name="symbol-search"]',
        ]
        opened_via = None
        for sel in candidates:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                try:
                    await loc.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                    # Check if a watchlist-shaped widget appeared.
                    has_watchlist = await page.evaluate(r"""() => {
                        const bar = document.querySelector(
                            '[class*="widgetbar-"], [data-name="right-toolbar"]'
                        );
                        if (!bar) return false;
                        // The watchlist content lives in a sibling panel,
                        // not inside the toolbar. Scan the whole document
                        // for elements with [data-symbol-short] or row-like
                        // structures with ticker text.
                        return !!document.querySelector(
                            '[data-symbol-short], '
                            + '[data-name*="atchlist" i], '
                            + 'div[class*="watchlist" i]'
                        );
                    }""")
                    if has_watchlist:
                        opened_via = sel
                        break
                    # Click again to close, try the next.
                    await loc.click(timeout=3000)
                    await page.wait_for_timeout(500)
                except Exception:
                    continue

        # Step 3 — dump the widget panel contents. From the first probe
        # pass we know the panel anchor is `[data-name="symbol-list-wrap"]`
        # (the scrollable container) or `[data-name="tree"]` (the list root).
        # Walk up to the surrounding widgetbar pages container to capture
        # header + footer too.
        panel_data = await page.evaluate(r"""() => {
            const wrappers = [
                '[data-name="widgetbar-pages-with-tabs"]',
                '[data-name="symbol-list-wrap"]',
                '[data-name="tree"]',
            ];
            let panel = null;
            for (const sel of wrappers) {
                const el = document.querySelector(sel);
                if (el && el.offsetWidth > 100) { panel = el; break; }
            }
            if (!panel) return {found: false};

            const out = {
                found: true,
                wrapperClass: (panel.className || '').toString().slice(0, 120),
                wrapperRect: {
                    x: Math.round(panel.getBoundingClientRect().x),
                    y: Math.round(panel.getBoundingClientRect().y),
                    width: Math.round(panel.getBoundingClientRect().width),
                    height: Math.round(panel.getBoundingClientRect().height),
                },
                buttons: [],
                inputs: [],
                rows: [],
                dataNames: [],
                ariaLabels: [],
            };

            panel.querySelectorAll('button').forEach(b => {
                const r = b.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                out.buttons.push({
                    dataName: b.getAttribute('data-name'),
                    ariaLabel: b.getAttribute('aria-label'),
                    title: b.getAttribute('title'),
                    text: (b.innerText || '').trim().slice(0, 60),
                    classes: (b.className || '').toString().slice(0, 80),
                });
            });

            panel.querySelectorAll('input').forEach(inp => {
                const r = inp.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                out.inputs.push({
                    type: inp.type,
                    name: inp.name,
                    placeholder: inp.placeholder,
                    ariaLabel: inp.getAttribute('aria-label'),
                    dataName: inp.getAttribute('data-name'),
                    classes: (inp.className || '').toString().slice(0, 80),
                });
            });

            // Symbol rows. Walk every descendant that looks like a row.
            // Symbols may sit on the row itself, or on a child symbol-cell.
            // Capture EVERY data-* attribute so we see exactly how rows
            // are addressable.
            const rowDescendants = Array.from(panel.querySelectorAll('[role="row"], [class*="symbolRow"], [class*="row-"]'))
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 50 && r.height > 8 && r.height < 60;
                });
            const seen = new Set();
            rowDescendants.forEach(r => {
                if (seen.has(r)) return;
                seen.add(r);
                const attrs = {};
                Array.from(r.attributes).forEach(a => {
                    if (a.name.startsWith('data-') || a.name === 'role')
                        attrs[a.name] = a.value;
                });
                out.rows.push({
                    tag: r.tagName,
                    attrs,
                    classes: (r.className || '').toString().slice(0, 80),
                    text: (r.innerText || '').trim().slice(0, 80).replace(/\s+/g, ' '),
                });
            });

            // Catalog every [data-name] in the panel for stability.
            panel.querySelectorAll('[data-name]').forEach(el => {
                out.dataNames.push({
                    dataName: el.getAttribute('data-name'),
                    tag: el.tagName,
                    text: (el.innerText || '').trim().slice(0, 40).replace(/\s+/g, ' '),
                });
            });

            // Catalog every [aria-label] in the panel.
            panel.querySelectorAll('[aria-label]').forEach(el => {
                out.ariaLabels.push({
                    ariaLabel: el.getAttribute('aria-label'),
                    tag: el.tagName,
                });
            });

            return out;
        }""")

        # Step 4 — capture menus. Each click here may dismiss the
        # previous popup, so we capture sequentially.
        async def _capture_menu(label: str, sel: str):
            loc = page.locator(sel).first
            if await loc.count() == 0 or not await loc.is_visible():
                return {label: f"button {sel} not visible"}
            try:
                await loc.click(timeout=3000)
                await page.wait_for_timeout(500)
            except Exception as e:
                return {label: f"click failed: {e}"}
            items = await page.evaluate(r"""() => {
                // Find any visible menu/popup that just appeared.
                const popups = Array.from(document.querySelectorAll(
                    '[class*="menuBox-"], [class*="menu-"][role="menu"], '
                    + '[class*="dropdown-"][role="menu"], div[role="menu"]'
                )).filter(p => {
                    const r = p.getBoundingClientRect();
                    return r.width > 80 && r.height > 40;
                });
                if (!popups.length) return {found: false};
                const popup = popups[popups.length - 1];
                const items = [];
                popup.querySelectorAll('[role="menuitem"], [class*="item-"], button, div').forEach(it => {
                    const r = it.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    const t = (it.innerText || '').trim();
                    if (!t || t.length > 80) return;
                    if (t.includes('\n')) return;  // skip aggregate labels
                    items.push({
                        tag: it.tagName,
                        dataName: it.getAttribute('data-name'),
                        ariaLabel: it.getAttribute('aria-label'),
                        role: it.getAttribute('role'),
                        text: t,
                    });
                });
                // Dedup by text.
                const seen = new Set();
                const uniq = items.filter(i => {
                    if (seen.has(i.text)) return false;
                    seen.add(i.text);
                    return true;
                });
                return {found: true, popupClass: popup.className.slice(0, 80), items: uniq};
            }""")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return {label: items}

        list_menu = await _capture_menu("watchlists_button", '[data-name="watchlists-button"]')
        settings_menu = await _capture_menu("settings_button",
            '[data-name="widgetbar-pages-with-tabs"] [data-name="settings-button"]')
        list_menu_data = {**list_menu, **settings_menu}

        snapshot = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "url": page.url,
            "opened_via": opened_via,
            "widgetbar_icons": widgetbar_icons,
            "panel": panel_data,
            "list_menu_candidates": list_menu_data,
        }

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"watchlist-{ts}.json"
        out_path.write_text(json.dumps(snapshot, indent=2))

        print(f"Wrote snapshot to {out_path}", flush=True)
        print(f"opened_via: {opened_via}", flush=True)
        print(flush=True)

        if not panel_data.get("found"):
            print("PANEL NOT FOUND — try opening the watchlist sidebar manually.", flush=True)
            return 1

        print(f"Panel: {panel_data['wrapperRect']}", flush=True)
        print(f"  class: {panel_data['wrapperClass']}", flush=True)
        print(flush=True)
        print(f"Buttons in panel ({len(panel_data['buttons'])}):", flush=True)
        for b in panel_data["buttons"][:30]:
            print(
                f"  data-name={b['dataName']!r:30s}  "
                f"aria={b['ariaLabel']!r:30s}  text={b['text']!r}",
                flush=True,
            )
        print(flush=True)
        print(f"Inputs ({len(panel_data['inputs'])}):", flush=True)
        for i in panel_data["inputs"]:
            print(f"  placeholder={i['placeholder']!r}  aria={i['ariaLabel']!r}", flush=True)
        print(flush=True)
        print(f"Symbol rows ({len(panel_data['rows'])}):", flush=True)
        for r in panel_data["rows"][:10]:
            print(
                f"  symbol={r['dataSymbolShort']!r:15s}  "
                f"text={r['text'][:60]!r}",
                flush=True,
            )
        print(flush=True)
        print(f"Unique [data-name]s ({len({d['dataName'] for d in panel_data['dataNames']})}):", flush=True)
        seen = set()
        for d in panel_data["dataNames"]:
            if d["dataName"] in seen:
                continue
            seen.add(d["dataName"])
            print(f"  data-name={d['dataName']!r:30s}  tag={d['tag']:6s}  text={d['text']!r}", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
