"""Probe the Indicators surface.

Three UI pieces we need to catalog:

  1. **Indicators dialog** — opened by `[data-name="open-indicators-dialog"]`
     in the top header toolbar. A modal with:
       - search input at top
       - category tabs (Built-ins / Community / Invite-only / …)
       - scrollable results list (anchor-like rows)
       - Add-to-chart action per row

  2. **Chart indicator legend** — small panel at top-left of the
     chart showing loaded indicators. Each entry has hover-reveal
     controls (eye, settings gear, delete X) we'll need for list /
     remove / configure.

  3. **Indicator settings modal** — opened by clicking the settings
     gear on a legend entry. Label + input pairs that `lib/modal.py`
     can fill via `fill_by_label`.

Strictly read-only — we never add or remove anything during the probe.

Output:
  tv_automation/probes/snapshots/indicators-YYYYMMDD-HHMMSS.json
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


async def _dump_large_dialogs(page) -> list[dict]:
    """List every on-screen dialog-like container (role=dialog OR
    class prefix 'dialog-') that's big enough to be a real modal."""
    return await page.evaluate(r"""() => {
        const out = [];
        document.querySelectorAll(
            'div[role="dialog"], div[class*="dialog-"], [data-dialog-name]'
        ).forEach(d => {
            const r = d.getBoundingClientRect();
            if (r.width < 200 || r.height < 150) return;
            out.push({
                tag: d.tagName.toLowerCase(),
                dataName: d.getAttribute('data-name'),
                dataDialogName: d.getAttribute('data-dialog-name'),
                role: d.getAttribute('role'),
                className: typeof d.className === 'string'
                    ? d.className.slice(0, 100) : null,
                text: (d.innerText || '').slice(0, 200),
                w: Math.round(r.width), h: Math.round(r.height),
            });
        });
        return out;
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
        # Phase 1: chart indicator legend (existing indicators on the
        # loaded chart). TV puts the legend at top-left as a stack of
        # "source items" — one per indicator/strategy.
        # ------------------------------------------------------------------
        snapshot["phase1_legend"] = await page.evaluate(r"""() => {
            // Legend items live inside the chart-gui legend wrapper.
            const legends = Array.from(document.querySelectorAll(
                '[data-qa-id="legend"], [class*="legend-"]'
            )).filter(n => {
                const r = n.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.x < 400;
            });
            if (!legends.length) return {error: 'no legend container'};
            // Each indicator is a legend-source-item.
            const items = Array.from(legends[0].querySelectorAll(
                '[data-qa-id="legend-source-item"]'
            )).map(it => ({
                qa: it.getAttribute('data-qa-id'),
                title: it.querySelector('[data-qa-id="legend-source-title"]')?.innerText || null,
                description: it.querySelector('[data-qa-id="legend-source-description"]')?.innerText || null,
                text: (it.innerText || '').trim().slice(0, 120),
                // Any child buttons (hover-revealed actions).
                buttons: Array.from(it.querySelectorAll('button, [role="button"]')).map(b => ({
                    dataQa: b.getAttribute('data-qa-id'),
                    ariaLabel: b.getAttribute('aria-label'),
                    title: b.getAttribute('title'),
                })),
            }));
            return items;
        }""")

        # ------------------------------------------------------------------
        # Phase 2: open Indicators dialog, dump structure.
        # ------------------------------------------------------------------
        try:
            btn = page.locator('[data-name="open-indicators-dialog"]').first
            await btn.click(timeout=5000)
            await page.wait_for_timeout(1200)
        except Exception as e:
            snapshot["phase2_error"] = f"open-indicators-dialog click: {e}"

        snapshot["phase2_visible_dialogs"] = await _dump_large_dialogs(page)

        # Identify the Indicators dialog — it has distinctive text
        # "Indicators, metrics" or "Indicators" header.
        dialog_present = any(
            "ndicator" in (d.get("text") or "")
            for d in snapshot["phase2_visible_dialogs"]
        )
        snapshot["phase2_dialog_found"] = dialog_present

        if dialog_present:
            # Dump controls inside the largest indicator-dialog candidate.
            snapshot["phase2_dialog_controls"] = await page.evaluate(r"""() => {
                const dialogs = Array.from(document.querySelectorAll(
                    'div[role="dialog"], div[class*="dialog-"], [data-dialog-name]'
                )).filter(d => {
                    const r = d.getBoundingClientRect();
                    return r.width > 400 && r.height > 400
                        && (d.innerText || '').includes('ndicator');
                });
                if (!dialogs.length) return null;
                const dlg = dialogs[0];
                const controls = Array.from(dlg.querySelectorAll(
                    'input, button, [role="tab"], [role="button"], '
                    + '[data-name], [aria-label]'
                )).filter(n => {
                    const r = n.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }).slice(0, 60).map(n => ({
                    tag: n.tagName.toLowerCase(),
                    role: n.getAttribute('role'),
                    id: n.id || null,
                    type: n.getAttribute('type'),
                    dataName: n.getAttribute('data-name'),
                    ariaLabel: n.getAttribute('aria-label'),
                    placeholder: n.getAttribute('placeholder'),
                    text: (n.innerText || '').trim().slice(0, 60),
                    y: Math.round(n.getBoundingClientRect().y),
                }));
                return {
                    dialog_class: (dlg.className || '').slice(0, 100),
                    dialog_title: (dlg.innerText || '').split('\n').slice(0, 4).join(' | '),
                    controls,
                };
            }""")

            # Fill the search box so the results list populates —
            # without a query it shows favorites/built-ins sections.
            try:
                search = page.locator(
                    'div[role="dialog"] input[data-name="search-input"], '
                    'div[class*="dialog-"] input[placeholder*="earch" i]'
                ).first
                await search.fill("rsi")
                await page.wait_for_timeout(800)
                # Dump results after filter.
                snapshot["phase2_rsi_results"] = await page.evaluate(r"""() => {
                    const dialogs = Array.from(document.querySelectorAll(
                        'div[role="dialog"], div[class*="dialog-"]'
                    )).filter(d => {
                        const r = d.getBoundingClientRect();
                        return r.width > 400 && (d.innerText || '').includes('ndicator');
                    });
                    if (!dialogs.length) return [];
                    const dlg = dialogs[0];
                    // Results typically are clickable rows. TV uses
                    // various row markers (data-role, data-active, etc.)
                    const rows = Array.from(dlg.querySelectorAll(
                        '[data-role="list-item"], [role="row"], [role="option"], '
                        + '[class*="item-"]'
                    )).filter(n => {
                        const r = n.getBoundingClientRect();
                        return r.width > 100 && r.height > 20 && r.height < 80;
                    }).slice(0, 20);
                    return rows.map(n => ({
                        tag: n.tagName.toLowerCase(),
                        role: n.getAttribute('role'),
                        dataName: n.getAttribute('data-name'),
                        ariaLabel: n.getAttribute('aria-label'),
                        dataRole: n.getAttribute('data-role'),
                        text: (n.innerText || '').trim().slice(0, 80),
                        cls: typeof n.className === 'string'
                            ? n.className.slice(0, 60) : null,
                    }));
                }""")
            except Exception as e:
                snapshot["phase2_search_error"] = str(e)

        # Close the dialog.
        for _ in range(3):
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)

        # ------------------------------------------------------------------
        # Phase 3: if any indicator exists in the legend, hover one and
        # capture its reveal-on-hover action buttons (eye / settings /
        # delete). Also try opening its settings modal briefly.
        # ------------------------------------------------------------------
        # Hover on the first non-main legend item (main is the symbol/price
        # series itself; indicators come after).
        hover_buttons = await page.evaluate(r"""() => {
            const items = Array.from(document.querySelectorAll(
                '[data-qa-id="legend-source-item"]'
            ));
            // Skip the first item (main series — the symbol itself).
            if (items.length < 2) return {skip_reason: 'only_main_series'};
            const target = items[1];
            target.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            target.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
            return {
                target_title: target.querySelector(
                    '[data-qa-id="legend-source-title"]'
                )?.innerText || null,
                buttons: Array.from(target.querySelectorAll(
                    'button, [role="button"]'
                )).map(b => ({
                    dataQa: b.getAttribute('data-qa-id'),
                    ariaLabel: b.getAttribute('aria-label'),
                    title: b.getAttribute('title'),
                    text: (b.innerText || '').trim().slice(0, 30),
                    visible: b.offsetWidth > 0 || b.offsetHeight > 0,
                })),
            };
        }""")
        snapshot["phase3_hover_legend_buttons"] = hover_buttons

        # ------------------------------------------------------------------
        # Write snapshot.
        # ------------------------------------------------------------------
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"indicators-{ts}.json"
        out_path.write_text(json.dumps(snapshot, indent=2))

        print(f"Wrote snapshot to {out_path}")
        print()
        legend = snapshot.get("phase1_legend", {})
        if isinstance(legend, list):
            print(f"Phase 1 legend items: {len(legend)}")
            for it in legend:
                print(f"  - {it.get('title')!r}  desc={it.get('description')!r}")
        print(f"Phase 2 dialog found: {snapshot.get('phase2_dialog_found')}")
        controls = snapshot.get("phase2_dialog_controls") or {}
        if controls:
            print(f"Phase 2 dialog title: {controls.get('dialog_title')[:60]!r}")
            print(f"Phase 2 dialog controls: {len(controls.get('controls', []))}")
        results = snapshot.get("phase2_rsi_results") or []
        print(f"Phase 2 RSI-search results: {len(results)}")
        for r in results[:5]:
            print(f"  - {r.get('text')!r}")
        print(f"Phase 3 hover buttons: {snapshot.get('phase3_hover_legend_buttons')}")
    return 0


if __name__ == "__main__":
    asyncio.run(main())
