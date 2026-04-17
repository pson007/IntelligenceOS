"""Probe the on-chart ORDER TICKET dialog.

Purpose: the Tier 1 quick-trade bar only fires MARKET orders. Limit, stop,
stop-limit, and bracket orders require TradingView's full order-ticket
modal. We don't have selectors for it yet — this probe opens the ticket,
dumps every input / select / button / label / radio inside, and writes
the snapshot to probes/snapshots/orders-YYYYMMDD-HHMMSS.json so we can
wire selectors.yaml without guessing.

Strategy (all strictly read-only — MUST NOT place or cancel anything):

  1. Catalog any always-visible DOM elements whose data-name / aria-label
     / visible text mentions "order" or "limit" or "stop" or "ticket" or
     "trade". These surface hidden buttons we might have missed.

  2. Right-click the chart canvas → the "Trade" submenu appears. Dump
     every menu item under it. Then select "Create limit order…"
     (or whichever menu item matches first) and capture the resulting
     modal. Escape out.

  3. Also snapshot the orders-table row structure if any pending orders
     exist — specifically to discover the cancel-button selector inside
     `settings-column` cells, resolving ROADMAP §5a.

Usage (sign in first, and have Paper Trading active):
    .venv/bin/python -m tv_automation.probes.probe_orders

Output: tv_automation/probes/snapshots/orders-YYYYMMDD-HHMMSS.json
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from preflight import ensure_automation_chromium
from session import tv_context

from ..lib.context import find_or_open_chart
from ..lib.guards import assert_logged_in, assert_paper_trading

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# JS: generic DOM-element attribute dumper. Reused across phases.
_DUMP_JS = r"""
(rootSelector) => {
    const root = rootSelector
        ? document.querySelector(rootSelector)
        : document.body;
    if (!root) return { error: 'root not found', rootSelector };
    const out = [];
    const seen = new Set();
    root.querySelectorAll('*').forEach(n => {
        if (seen.has(n)) return;
        seen.add(n);
        const tag = n.tagName.toLowerCase();
        const role = n.getAttribute('role');
        const dn = n.getAttribute('data-name');
        const al = n.getAttribute('aria-label');
        const ph = n.getAttribute('placeholder');
        const title = n.getAttribute('title');
        const type = n.getAttribute('type');
        const id = n.id || null;
        const text = (n.innerText || '').trim().slice(0, 120);
        // Only interesting elements: must have *some* identifier OR be an
        // input/button/select. Skips the millions of divs with no attrs.
        const interesting =
            dn || al || ph || title || role ||
            tag === 'input' || tag === 'button' || tag === 'select' ||
            tag === 'textarea';
        if (!interesting) return;
        const rect = n.getBoundingClientRect();
        out.push({
            tag, role, id, type,
            dataName: dn, ariaLabel: al, placeholder: ph, title,
            className: typeof n.className === 'string'
                ? n.className.slice(0, 100) : null,
            text,
            visible: !!(n.offsetWidth || n.offsetHeight),
            x: Math.round(rect.x), y: Math.round(rect.y),
            w: Math.round(rect.width), h: Math.round(rect.height),
        });
    });
    return out;
}
"""


async def _dump(page, root_selector: str | None = None) -> list[dict]:
    return await page.evaluate(_DUMP_JS, root_selector)


async def _filter_keywords(entries: list[dict], *keywords: str) -> list[dict]:
    needles = [k.lower() for k in keywords]

    def hit(s: str | None) -> bool:
        if not s:
            return False
        low = s.lower()
        return any(k in low for k in needles)

    return [
        e for e in entries
        if hit(e.get("dataName")) or hit(e.get("ariaLabel")) or
        hit(e.get("text")) or hit(e.get("placeholder")) or
        hit(e.get("title"))
    ]


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await find_or_open_chart(ctx)
        await assert_logged_in(page)
        await assert_paper_trading(page)
        await page.wait_for_selector("canvas", state="visible", timeout=20_000)
        await page.wait_for_timeout(1500)

        snapshot: dict = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "url": page.url,
        }

        # ------------------------------------------------------------------
        # Phase 1: pre-ticket keyword sweep — discover any always-visible
        # buttons we've missed. Looking for a "+" on the quick-trade bar,
        # a hidden order-ticket shortcut, etc.
        # ------------------------------------------------------------------
        all_entries = await _dump(page)
        snapshot["phase1_keyword_hits"] = await _filter_keywords(
            all_entries, "order", "limit", "stop", "ticket", "trade",
            "bracket", "protect", "tp", "sl",
        )

        # ------------------------------------------------------------------
        # Phase 2: open the order ticket via SHIFT+click on the chart canvas.
        # TradingView's documented gesture: SHIFT+click at a price level on
        # the chart creates a BUY LIMIT order at that price. Clicking below
        # current price = buy limit; above = sell limit. Opens the on-chart
        # order line with a small ticket. The ticket is DOM, so we can
        # dump it. (Tested alternatives that failed: right-click on canvas
        # hits TV's canvas-drawn menu which isn't DOM; clicking the header
        # "Trade" button just toggles the Account Manager bottom panel.)
        # ------------------------------------------------------------------
        canvas = page.locator("canvas").first
        cbox = await canvas.bounding_box()
        if cbox is None:
            snapshot["phase2_error"] = "canvas has no bounding box"
        else:
            # Click well below midpoint — that's a BUY LIMIT setup, which
            # won't execute until the price drops (very unlikely in 500ms).
            cx = int(cbox["x"] + cbox["width"] / 2)
            cy = int(cbox["y"] + cbox["height"] * 0.80)
            try:
                await page.keyboard.down("Shift")
                await page.mouse.click(cx, cy)
                await page.keyboard.up("Shift")
                snapshot["phase2_shift_click_pos"] = {"x": cx, "y": cy}
            except Exception as e:
                snapshot["phase2_shift_click_error"] = repr(e)

            await page.wait_for_timeout(1200)

            # After clicking, either a dialog opens or a dropdown appears.
            # Dump both: dialogs AND any floating-menu items.
            ctx_menu_entries = await page.evaluate(r"""
                () => {
                    // TV's floating menu root — usually several candidates.
                    const out = [];
                    const selectors = [
                        '[role="menu"]',
                        '[data-name*="menu"]',
                        '[class*="menu-"][class*="visible"]',
                        '.menuWrap-hKySSDmA',  // hash-based fallback
                    ];
                    const roots = new Set();
                    selectors.forEach(s =>
                        document.querySelectorAll(s).forEach(n => roots.add(n))
                    );
                    // Fallback: any element with role=menuitem anywhere.
                    roots.add(document.body);
                    const seen = new Set();
                    roots.forEach(r => r.querySelectorAll(
                        '[role="menuitem"], [role="menuitemcheckbox"], [role="menu"] button, [data-name*="menu"] [role="button"]'
                    ).forEach(n => {
                        if (seen.has(n)) return;
                        seen.add(n);
                        const rect = n.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0) return;
                        out.push({
                            tag: n.tagName.toLowerCase(),
                            role: n.getAttribute('role'),
                            dataName: n.getAttribute('data-name'),
                            ariaLabel: n.getAttribute('aria-label'),
                            text: (n.innerText || '').trim().slice(0, 100),
                            x: Math.round(rect.x), y: Math.round(rect.y),
                        });
                    }));
                    return out;
                }
            """)
            snapshot["phase2_context_menu_items"] = ctx_menu_entries

            # Hover the "Trade" item to open its submenu (TV uses hover
            # for submenus, not click).
            trade_item = None
            for it in ctx_menu_entries:
                txt = (it.get("text") or "").strip().lower()
                if txt == "trade" or txt.startswith("trade"):
                    trade_item = it
                    break

            if trade_item:
                # Re-locate and hover — coordinates from the dump are stale
                # after animations, so prefer a text-based locator.
                try:
                    await page.locator(
                        '[role="menuitem"]:has-text("Trade"):visible'
                    ).first.hover(timeout=3000)
                    await page.wait_for_timeout(500)

                    # Dump the now-visible submenu.
                    submenu_entries = await page.evaluate(r"""
                        () => {
                            const out = [];
                            document.querySelectorAll(
                                '[role="menuitem"], [role="menuitem"] *'
                            ).forEach(n => {
                                const rect = n.getBoundingClientRect();
                                if (rect.width === 0 && rect.height === 0) return;
                                if (n.getAttribute('role') !== 'menuitem') return;
                                out.push({
                                    tag: n.tagName.toLowerCase(),
                                    role: n.getAttribute('role'),
                                    dataName: n.getAttribute('data-name'),
                                    ariaLabel: n.getAttribute('aria-label'),
                                    text: (n.innerText || '').trim().slice(0, 120),
                                    x: Math.round(rect.x), y: Math.round(rect.y),
                                });
                            });
                            return out;
                        }
                    """)
                    snapshot["phase2_trade_submenu_items"] = submenu_entries

                    # Click a limit-order creator if present. Try several
                    # likely labels.
                    clicked_label = None
                    for label in (
                        "Create limit order",
                        "Create new limit order",
                        "Buy limit",
                        "Limit order",
                        "Create order",
                    ):
                        loc = page.locator(
                            f'[role="menuitem"]:has-text("{label}"):visible'
                        ).first
                        if await loc.count() > 0:
                            try:
                                await loc.click(timeout=2000)
                                clicked_label = label
                                break
                            except Exception:
                                continue
                    snapshot["phase2_clicked_item"] = clicked_label

                    if clicked_label:
                        await page.wait_for_timeout(1200)

                        # Dump every visible dialog on the page — the order
                        # ticket is typically a large div[role="dialog"].
                        dialogs = await page.evaluate(r"""
                            () => {
                                const results = [];
                                document.querySelectorAll(
                                    'div[role="dialog"], [data-name$="-dialog"], '
                                    + '[data-name$="-ticket"], [data-name$="-content"]'
                                ).forEach(d => {
                                    const rect = d.getBoundingClientRect();
                                    if (rect.width === 0 && rect.height === 0) return;
                                    results.push({
                                        tag: d.tagName.toLowerCase(),
                                        dataName: d.getAttribute('data-name'),
                                        ariaLabel: d.getAttribute('aria-label'),
                                        role: d.getAttribute('role'),
                                        className: typeof d.className === 'string'
                                            ? d.className.slice(0, 120) : null,
                                        text: (d.innerText || '').trim().slice(0, 200),
                                        x: Math.round(rect.x), y: Math.round(rect.y),
                                        w: Math.round(rect.width), h: Math.round(rect.height),
                                    });
                                });
                                return results;
                            }
                        """)
                        snapshot["phase2_visible_dialogs"] = dialogs

                        # Deep-dump the topmost dialog's interactive elements.
                        dialog_dump = await page.evaluate(r"""
                            () => {
                                const dialogs = Array.from(document.querySelectorAll(
                                    'div[role="dialog"], [data-name$="-dialog"], '
                                    + '[data-name$="-ticket"]'
                                )).filter(d => {
                                    const r = d.getBoundingClientRect();
                                    return r.width > 0 && r.height > 0;
                                });
                                if (dialogs.length === 0) return null;
                                // Take the last (topmost) dialog.
                                const d = dialogs[dialogs.length - 1];
                                const out = [];
                                d.querySelectorAll(
                                    'input, button, select, textarea, '
                                    + '[role="button"], [role="tab"], '
                                    + '[role="radio"], [role="checkbox"], '
                                    + '[data-name], [aria-label], [title]'
                                ).forEach(n => {
                                    const rect = n.getBoundingClientRect();
                                    out.push({
                                        tag: n.tagName.toLowerCase(),
                                        role: n.getAttribute('role'),
                                        id: n.id || null,
                                        type: n.getAttribute('type'),
                                        dataName: n.getAttribute('data-name'),
                                        ariaLabel: n.getAttribute('aria-label'),
                                        placeholder: n.getAttribute('placeholder'),
                                        title: n.getAttribute('title'),
                                        value: n.tagName === 'INPUT'
                                            ? (n.value || null) : null,
                                        text: (n.innerText || '').trim().slice(0, 120),
                                        className: typeof n.className === 'string'
                                            ? n.className.slice(0, 100) : null,
                                        visible: rect.width > 0 && rect.height > 0,
                                        x: Math.round(rect.x), y: Math.round(rect.y),
                                    });
                                });
                                return {
                                    dialog: {
                                        dataName: d.getAttribute('data-name'),
                                        ariaLabel: d.getAttribute('aria-label'),
                                        className: typeof d.className === 'string'
                                            ? d.className.slice(0, 120) : null,
                                    },
                                    entries: out,
                                };
                            }
                        """)
                        snapshot["phase2_order_ticket_dump"] = dialog_dump
                except Exception as e:
                    snapshot["phase2_trade_submenu_error"] = repr(e)

            # Clean up — press Escape twice to close any open dialogs /
            # menus. We are strictly read-only; do NOT submit anything.
            for _ in range(3):
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(200)

        # ------------------------------------------------------------------
        # Phase 3: orders-table cancel button discovery. If there are any
        # pending orders, hover each row and capture the reveal-on-hover
        # buttons in settings-column. If table is empty, log that and skip.
        # ------------------------------------------------------------------
        orders_table_dump = await page.evaluate(r"""
            () => {
                const t = document.querySelector('[data-name="Paper.orders-table"]');
                if (!t) return { present: false };
                const rows = Array.from(t.querySelectorAll('tbody tr'))
                    .filter(r => !r.className.includes('emptyStateRow'));
                const headers = Array.from(t.querySelectorAll('thead th')).map(h => ({
                    dataName: h.getAttribute('data-name'),
                    text: (h.innerText || '').trim(),
                }));
                const rowDumps = rows.slice(0, 3).map(r => {
                    const cells = Array.from(r.querySelectorAll('td'));
                    // Find all buttons inside the row (including hidden).
                    const btns = Array.from(r.querySelectorAll('button, [role="button"]'))
                        .map(b => ({
                            dataName: b.getAttribute('data-name'),
                            ariaLabel: b.getAttribute('aria-label'),
                            text: (b.innerText || '').trim().slice(0, 40),
                            className: typeof b.className === 'string'
                                ? b.className.slice(0, 80) : null,
                            visible: b.offsetWidth > 0 || b.offsetHeight > 0,
                        }));
                    return {
                        cells: cells.map(c => ({
                            dataName: c.getAttribute('data-name'),
                            text: (c.innerText || '').trim().slice(0, 60),
                        })),
                        buttons: btns,
                    };
                });
                return {
                    present: true,
                    visible: t.offsetWidth > 0,
                    headers,
                    row_count: rows.length,
                    sample_rows: rowDumps,
                };
            }
        """)
        snapshot["phase3_orders_table"] = orders_table_dump

        # If there are pending orders, hover the first one and re-dump —
        # reveal-on-hover buttons show up only then.
        if (isinstance(orders_table_dump, dict)
                and orders_table_dump.get("row_count", 0) > 0):
            try:
                row_loc = page.locator(
                    '[data-name="Paper.orders-table"] tbody tr:not(.emptyStateRow-pnigL71h)'
                ).first
                # Use dispatchEvent to bypass pointer-event interception
                # that the ROADMAP flagged as blocking .hover().
                await row_loc.evaluate(
                    "el => el.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}))"
                )
                await page.wait_for_timeout(400)
                hover_dump = await page.evaluate(r"""
                    () => {
                        const t = document.querySelector('[data-name="Paper.orders-table"]');
                        if (!t) return null;
                        const firstRow = t.querySelector('tbody tr:not(.emptyStateRow-pnigL71h)');
                        if (!firstRow) return null;
                        return Array.from(
                            firstRow.querySelectorAll('button, [role="button"]')
                        ).map(b => ({
                            dataName: b.getAttribute('data-name'),
                            ariaLabel: b.getAttribute('aria-label'),
                            text: (b.innerText || '').trim().slice(0, 40),
                            visible: b.offsetWidth > 0 || b.offsetHeight > 0,
                        }));
                    }
                """)
                snapshot["phase3_orders_row_hover_buttons"] = hover_dump
            except Exception as e:
                snapshot["phase3_hover_error"] = repr(e)

        # ------------------------------------------------------------------
        # Write snapshot.
        # ------------------------------------------------------------------
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"orders-{ts}.json"
        out_path.write_text(json.dumps(snapshot, indent=2))

        print(f"Wrote snapshot to {out_path}")
        print()
        print("Phase 1 keyword hits (order/limit/stop/...):",
              len(snapshot.get("phase1_keyword_hits", [])))
        print("Phase 2 context menu items:",
              len(snapshot.get("phase2_context_menu_items", [])))
        print("Phase 2 trade submenu items:",
              len(snapshot.get("phase2_trade_submenu_items", [])))
        print("Phase 2 clicked:",
              snapshot.get("phase2_clicked_item"))
        dumped = snapshot.get("phase2_order_ticket_dump")
        if dumped:
            print(f"Phase 2 order-ticket entries: {len(dumped.get('entries', []))}")
            print(f"Phase 2 dialog data-name: {dumped['dialog'].get('dataName')}")
        print("Phase 3 orders table:",
              orders_table_dump.get("row_count"), "rows")
    return 0


if __name__ == "__main__":
    asyncio.run(main())
