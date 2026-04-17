"""Probe the Layouts surface.

Two UI entry points we need to catalog:

  1. **Layouts dropdown** — `[data-name="save-load-menu"]` (aria-label
     "Manage layouts") in the top header toolbar. Opens a popup with:
       - RECENTLY USED <list of layout names>
       - commands: Save layout (⌘S) / Download chart data…
         / Create new layout… / Open layout… / (Rename… when a saved
         layout is loaded) / (Delete… likewise)

  2. **Open Layout… dialog** — larger modal with the full layout
     picker (RECENTLY USED is capped at ~8; older layouts live here).

The probe opens both, dumps the menu items + picker rows, then
dismisses cleanly. Strictly read-only — no saves or deletes.

Prior art in the repo:
  [create_layout.py](../../create_layout.py) already drives the menu
  for "Create new layout…" + "Rename…". This probe refreshes its
  selectors for the 2026-04-17 build and picks up the newer picker
  dialog.

Output:
  tv_automation/probes/snapshots/layouts-YYYYMMDD-HHMMSS.json
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from preflight import ensure_automation_chromium
from session import tv_context

from ..lib.context import find_or_open_chart
from ..lib.guards import assert_logged_in
from ..lib.overlays import dismiss_toasts

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


async def _dump_menu_items(page) -> list[dict]:
    """Dump every visible menu item inside any currently-open menubox.
    TV uses `menuBox-` class-prefix for the popup wrapper and wraps
    each row with class containing `item-` (with a hash suffix)."""
    return await page.evaluate(r"""() => {
        const popups = Array.from(document.querySelectorAll(
            '[class*="menuBox-"], [class*="menu-"][class*="popup"]'
        )).filter(p => {
            const r = p.getBoundingClientRect();
            return r.width > 50 && r.height > 50;
        });
        if (!popups.length) return [];
        const popup = popups[popups.length - 1];
        // Menu rows: anything with role="menuitem" OR a clickable label.
        const items = Array.from(popup.querySelectorAll(
            '[role="menuitem"], [class*="item-"], [class*="labelRow"]'
        )).filter(n => {
            const r = n.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        });
        return items.slice(0, 80).map(n => ({
            tag: n.tagName.toLowerCase(),
            role: n.getAttribute('role'),
            dataName: n.getAttribute('data-name'),
            text: (n.innerText || '').trim().slice(0, 100),
            className: typeof n.className === 'string'
                ? n.className.slice(0, 100) : null,
            y: Math.round(n.getBoundingClientRect().y),
        }));
    }""")


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await find_or_open_chart(ctx)
        await assert_logged_in(page)
        await page.wait_for_selector("canvas", state="visible", timeout=20_000)
        await page.wait_for_timeout(800)
        await dismiss_toasts(page)

        snapshot: dict = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "url": page.url,
        }

        # ------------------------------------------------------------------
        # Phase 1: header button state — is there a current layout loaded?
        # The save-load-menu button's aria-label or nearby text usually
        # reflects the current layout name.
        # ------------------------------------------------------------------
        snapshot["phase1_header"] = await page.evaluate(r"""() => {
            const btn = document.querySelector('[data-name="save-load-menu"]');
            if (!btn) return null;
            const rect = btn.getBoundingClientRect();
            // The current layout name is usually rendered in a nearby
            // element — walk up and look for it.
            let walker = btn;
            let layoutName = null;
            for (let i = 0; i < 5; i++) {
                walker = walker.parentElement;
                if (!walker) break;
                const t = (walker.innerText || '').trim();
                if (t && t.length < 60) {
                    layoutName = t;
                    break;
                }
            }
            return {
                button_aria: btn.getAttribute('aria-label'),
                layout_name_guess: layoutName,
                x: Math.round(rect.x), y: Math.round(rect.y),
            };
        }""")

        # ------------------------------------------------------------------
        # Phase 2: open the layouts dropdown and dump its items.
        # ------------------------------------------------------------------
        try:
            await page.locator('[data-name="save-load-menu"]').first.click(timeout=5000)
            await page.wait_for_timeout(800)
        except Exception as e:
            snapshot["phase2_error"] = f"save-load-menu click failed: {e}"

        snapshot["phase2_menu_items"] = await _dump_menu_items(page)
        # Extract a cleaner list of command labels (one entry per unique
        # visible command text).
        seen = set()
        commands = []
        for it in snapshot["phase2_menu_items"]:
            t = (it.get("text") or "").split("\n")[0].strip()
            if t and t not in seen and len(t) < 60:
                seen.add(t)
                commands.append({
                    "label": t,
                    "className": it.get("className"),
                    "y": it.get("y"),
                })
        snapshot["phase2_commands"] = commands

        # Before dismissing the menu, ALSO look for "RECENTLY USED" header
        # + the rows beneath it. Each row is the layout name itself.
        snapshot["phase2_recent_layouts"] = await page.evaluate(r"""() => {
            const popups = Array.from(document.querySelectorAll(
                '[class*="menuBox-"]'
            )).filter(p => {
                const r = p.getBoundingClientRect();
                return r.width > 50 && r.height > 50;
            });
            if (!popups.length) return [];
            const popup = popups[popups.length - 1];
            const text = popup.innerText || '';
            if (!text.includes('RECENTLY USED')) return [];
            // Collect ellipsis-classed items (layout names) filtering out
            // the shared command-class hash (Uy_he976 in prior art).
            const rows = Array.from(popup.querySelectorAll('[class*="ellipsis-"]'))
                .filter(e => {
                    const r = e.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                })
                .map(e => ({
                    text: (e.innerText || '').trim(),
                    className: typeof e.className === 'string'
                        ? e.className.slice(0, 60) : null,
                }));
            return rows;
        }""")

        # Dismiss the menu.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # ------------------------------------------------------------------
        # Phase 3: open the "Open layout…" dialog for the full picker view.
        # ------------------------------------------------------------------
        try:
            await page.locator('[data-name="save-load-menu"]').first.click(timeout=3000)
            await page.wait_for_timeout(500)
            # Click "Open layout…" menu item.
            open_item = page.locator(
                '[class*="menuBox-"] div:text-is("Open layout\u2026"), '
                '[class*="menuBox-"] span:text-is("Open layout\u2026")'
            ).first
            await open_item.click(timeout=3000)
            await page.wait_for_timeout(1200)
        except Exception as e:
            snapshot["phase3_error"] = f"Open layout click failed: {e}"

        # Dump whatever dialog / picker appeared.
        snapshot["phase3_picker_dump"] = await page.evaluate(r"""() => {
            const dialogs = Array.from(document.querySelectorAll(
                'div[class*="dialog-"]'
            )).filter(d => {
                const r = d.getBoundingClientRect();
                return r.width > 400 && r.height > 400;
            });
            if (!dialogs.length) return {error: 'no picker dialog'};
            const d = dialogs[dialogs.length - 1];
            // Collect row entries + header controls.
            const rows = Array.from(d.querySelectorAll(
                '[class*="row-"], [class*="item-"], li, tr'
            )).filter(n => {
                const r = n.getBoundingClientRect();
                return r.width > 100 && r.height > 20;
            }).slice(0, 40).map(n => ({
                tag: n.tagName.toLowerCase(),
                role: n.getAttribute('role'),
                text: (n.innerText || '').trim().slice(0, 100),
                className: typeof n.className === 'string'
                    ? n.className.slice(0, 80) : null,
            }));
            const buttons = Array.from(d.querySelectorAll('button')).filter(b => {
                const r = b.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            }).slice(0, 20).map(b => ({
                text: (b.innerText || '').trim().slice(0, 40),
                dataName: b.getAttribute('data-name'),
                ariaLabel: b.getAttribute('aria-label'),
            }));
            const inputs = Array.from(d.querySelectorAll('input')).map(i => ({
                type: i.getAttribute('type'),
                placeholder: i.getAttribute('placeholder'),
            }));
            return {
                dialog_class: (d.className || '').slice(0, 100),
                dialog_title: (d.innerText || '').slice(0, 100),
                rows, buttons, inputs,
            };
        }""")

        # Dismiss.
        for _ in range(3):
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)

        # ------------------------------------------------------------------
        # Write snapshot.
        # ------------------------------------------------------------------
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"layouts-{ts}.json"
        out_path.write_text(json.dumps(snapshot, indent=2))

        print(f"Wrote snapshot to {out_path}")
        print()
        print("=== Phase 2 — dropdown commands ===")
        for c in snapshot.get("phase2_commands", []):
            print(f"  y={c.get('y')!s:>4}  {c['label']!r}")
        print(f"\nRecent layouts: {len(snapshot.get('phase2_recent_layouts', []))}")
        for r in snapshot.get("phase2_recent_layouts", []):
            print(f"  - {r['text']!r}")
        print()
        picker = snapshot.get("phase3_picker_dump", {})
        if isinstance(picker, dict) and "rows" in picker:
            print(f"=== Phase 3 — picker dialog ({len(picker.get('rows', []))} rows) ===")
            print(f"  title hint: {picker.get('dialog_title', '')[:80]!r}")
            for r in picker.get("rows", [])[:10]:
                print(f"  - {r['text'][:80]!r}")
        else:
            print("=== Phase 3 — picker not found:", picker.get("error"))
    return 0


if __name__ == "__main__":
    asyncio.run(main())
