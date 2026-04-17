"""Probe the Alerts surface.

Two UI entry points we need to understand:

  1. **Create Alert dialog** — a modal opened by Alt+A on chart (or
     right-click → "Add alert…"). Has sections for Condition, Trigger,
     Expiration, and Notifications (including the webhook URL field,
     which is the Pro+-only control that links TV alerts to the
     `tv-worker/` Cloudflare Worker → `bridge.py` loop).

  2. **Alerts list panel** — the right sidebar's Alerts tab
     (`[data-name="alerts"]`). Shows existing alerts, their enabled
     state, and per-row actions (pause/resume, delete, edit).

The probe opens both, dumps every input / select / button / combobox
inside, and also inspects each dropdown's options (Condition type,
Trigger frequency, Expiration type). It never submits or deletes
anything — strictly read-only.

Output:
  tv_automation/probes/snapshots/alerts-YYYYMMDD-HHMMSS.json

Usage:
  .venv/bin/python -m tv_automation.probes.probe_alerts
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


# JS that dumps every interactive element inside a given root, used twice
# (once on the Create-Alert dialog, once on the right-sidebar alerts
# panel). Return fields include role / id / data-name / aria-label /
# placeholder / value / text / bounding-box, so we can pick the most
# stable handle later.
_DUMP_JS = r"""
(rootSelector) => {
    const root = rootSelector
        ? document.querySelector(rootSelector)
        : document.body;
    if (!root) return {error: 'root not found', rootSelector};
    const out = [];
    root.querySelectorAll(
        'input, button, select, textarea, [role="button"], [role="tab"], '
        + '[role="combobox"], [role="radio"], [role="checkbox"], '
        + '[role="switch"], [role="listbox"], [role="option"], '
        + '[role="menuitem"], [data-name], [aria-label], [title]'
    ).forEach(n => {
        const rect = n.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        out.push({
            tag: n.tagName.toLowerCase(),
            role: n.getAttribute('role'),
            id: n.id || null,
            type: n.getAttribute('type'),
            dataName: n.getAttribute('data-name'),
            ariaLabel: n.getAttribute('aria-label'),
            placeholder: n.getAttribute('placeholder'),
            title: n.getAttribute('title'),
            value: n.tagName === 'INPUT' ? (n.value || null) : null,
            text: (n.innerText || '').trim().slice(0, 120),
            className: typeof n.className === 'string'
                ? n.className.slice(0, 100) : null,
            x: Math.round(rect.x), y: Math.round(rect.y),
            w: Math.round(rect.width), h: Math.round(rect.height),
        });
    });
    return out;
}
"""


async def _dump(page, root_selector: str | None = None) -> list[dict]:
    return await page.evaluate(_DUMP_JS, root_selector)


async def _dump_visible_dialogs(page) -> list[dict]:
    """List every visible div[role=dialog] or data-name$='-dialog' so
    we can identify the alert-creation modal unambiguously."""
    return await page.evaluate(r"""() => {
        const results = [];
        document.querySelectorAll(
            'div[role="dialog"], [data-name$="-dialog"], '
            + '[data-dialog-name]'
        ).forEach(d => {
            const r = d.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;
            results.push({
                tag: d.tagName.toLowerCase(),
                dataName: d.getAttribute('data-name'),
                dataDialogName: d.getAttribute('data-dialog-name'),
                ariaLabel: d.getAttribute('aria-label'),
                className: typeof d.className === 'string'
                    ? d.className.slice(0, 120) : null,
                text: (d.innerText || '').slice(0, 200),
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
            });
        });
        return results;
    }""")


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await find_or_open_chart(ctx)
        await assert_logged_in(page)
        await page.wait_for_selector("canvas", state="visible", timeout=20_000)
        await page.wait_for_timeout(1000)
        await dismiss_toasts(page)

        snapshot: dict = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "url": page.url,
        }

        # ------------------------------------------------------------------
        # Phase 1: trigger the Create-Alert dialog. First open the
        # right-sidebar alerts panel (clicking the alerts icon, but
        # only if not already open), then click
        # `[data-name="set-alert-button"]` — the "+" icon at the top of
        # the panel.
        # ------------------------------------------------------------------
        sidebar_open = await page.locator(
            '[data-name="set-alert-button"]'
        ).first.is_visible().__wrapped__() if False else False
        try:
            if not sidebar_open:
                sidebar_open = await page.evaluate(
                    "() => {"
                    "  const b = document.querySelector('[data-name=\"set-alert-button\"]');"
                    "  return !!(b && b.offsetWidth > 0);"
                    "}"
                )
        except Exception:
            sidebar_open = False

        if not sidebar_open:
            try:
                await page.locator('[data-name="alerts"]').first.click(timeout=3000)
                await page.wait_for_timeout(700)
            except Exception as e:
                snapshot["phase1_sidebar_error"] = f"alerts icon click: {e}"

        # The set-alert button is a <div>, not a <button>.
        try:
            await page.locator('[data-name="set-alert-button"]').first.click(timeout=5000)
            await page.wait_for_timeout(1500)
        except Exception as e:
            snapshot["phase1_set_alert_error"] = f"set-alert-button click: {e}"

        snapshot["phase1_dialogs_after_alt_a"] = await _dump_visible_dialogs(page)

        # Find the alerts dialog — most likely by its distinctive text
        # "Create Alert" or a data-name containing "alert".
        dialog_sel = None
        for candidate in (
            'div[role="dialog"]:has-text("Create alert")',
            'div[role="dialog"]:has-text("Create Alert")',
            '[data-name="alerts-dialog"]',
            '[data-name="create-alert-dialog"]',
            '[data-dialog-name="create-alert"]',
        ):
            loc = page.locator(candidate).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    dialog_sel = candidate
                    break
            except Exception:
                continue

        if dialog_sel is None:
            snapshot["phase1_error"] = (
                "No alert dialog detected after Alt+A. "
                "Check phase1_dialogs_after_alt_a for what appeared."
            )
        else:
            snapshot["phase1_dialog_selector"] = dialog_sel

            # Full dump of the dialog interior.
            snapshot["phase1_dialog_dump"] = await _dump(page, dialog_sel)

            # Now iterate over each combobox/select/dropdown button in the
            # dialog and capture the options by clicking and dumping.
            # IMPORTANT: we must not accidentally submit the alert or
            # change fields irreversibly. We click, dump, and press
            # Escape to close menus.
            dropdowns = await page.evaluate(
                r"""(selector) => {
                    const dlg = document.querySelector(selector);
                    if (!dlg) return [];
                    return Array.from(dlg.querySelectorAll(
                        '[role="combobox"], button[aria-haspopup], '
                        + 'button[class*="select"], button[class*="dropdown"]'
                    )).filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }).map((el, i) => ({
                        index: i,
                        id: el.id || null,
                        dataName: el.getAttribute('data-name'),
                        ariaLabel: el.getAttribute('aria-label'),
                        text: (el.innerText || '').trim().slice(0, 60),
                        y: Math.round(el.getBoundingClientRect().y),
                    }));
                }""",
                dialog_sel,
            )
            snapshot["phase1_dropdowns"] = dropdowns

            dropdown_options = []
            for i, dd in enumerate(dropdowns[:8]):  # cap exploration
                try:
                    # Re-locate the dropdown by its position (index). Build
                    # a locator path inside the dialog.
                    loc = page.locator(
                        f'{dialog_sel} [role="combobox"], '
                        f'{dialog_sel} button[aria-haspopup], '
                        f'{dialog_sel} button[class*="select"], '
                        f'{dialog_sel} button[class*="dropdown"]'
                    ).nth(i)
                    await loc.scroll_into_view_if_needed(timeout=2000)
                    await loc.click(timeout=3000)
                    await page.wait_for_timeout(500)

                    # Capture anything floating that wasn't visible before.
                    opts = await page.evaluate(r"""() => {
                        const out = [];
                        // Any role=option, menuitem, or listbox entry
                        document.querySelectorAll(
                            '[role="option"], [role="menuitem"], '
                            + '[role="menuitemradio"], [role="listbox"] li'
                        ).forEach(n => {
                            const r = n.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) return;
                            out.push({
                                tag: n.tagName.toLowerCase(),
                                role: n.getAttribute('role'),
                                text: (n.innerText || '').trim().slice(0, 80),
                                ariaLabel: n.getAttribute('aria-label'),
                                dataName: n.getAttribute('data-name'),
                                x: Math.round(r.x),
                                y: Math.round(r.y),
                            });
                        });
                        return out;
                    }""")
                    dropdown_options.append({
                        "dropdown": dd,
                        "options": opts,
                    })

                    # Close the dropdown before the next iteration.
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(200)
                except Exception as e:
                    dropdown_options.append({
                        "dropdown": dd,
                        "error": repr(e),
                    })
            snapshot["phase1_dropdown_options"] = dropdown_options

            # Also capture any section/tab structure — the dialog might
            # have tabs like "Settings" / "Notifications" / "Message".
            snapshot["phase1_section_tabs"] = await page.evaluate(
                r"""(selector) => {
                    const dlg = document.querySelector(selector);
                    if (!dlg) return [];
                    return Array.from(dlg.querySelectorAll(
                        '[role="tab"], [role="tablist"] button'
                    )).filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }).map(el => ({
                        text: (el.innerText || '').trim(),
                        selected: el.getAttribute('aria-selected'),
                        dataName: el.getAttribute('data-name'),
                        ariaLabel: el.getAttribute('aria-label'),
                    }));
                }""",
                dialog_sel,
            )

            # Close the Create Alert dialog.
            for _ in range(3):
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(200)

        # ------------------------------------------------------------------
        # Phase 2: open the right-sidebar alerts panel and dump its shape.
        # ------------------------------------------------------------------
        alerts_icon = page.locator('[data-name="alerts"]').first
        try:
            await alerts_icon.click(timeout=3000)
            await page.wait_for_timeout(800)
        except Exception as e:
            snapshot["phase2_error"] = f"Could not click alerts sidebar icon: {e}"

        # The alerts panel usually shows up in the right-sidebar widget
        # area. Best to dump the whole widgetbar region when alerts is
        # active.
        snapshot["phase2_panel_dump"] = await page.evaluate(r"""() => {
            // The widgetbar is the right sidebar container.
            const widgetbar = document.querySelector(
                '[data-name="widgetbar-wrap"], [data-name="widgetbar"]'
            );
            if (!widgetbar) return {error: 'no widgetbar found'};
            const out = [];
            widgetbar.querySelectorAll(
                'input, button, [role="button"], [role="tab"], '
                + '[role="row"], [role="switch"], [data-name], [aria-label]'
            ).forEach(n => {
                const r = n.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                out.push({
                    tag: n.tagName.toLowerCase(),
                    role: n.getAttribute('role'),
                    dataName: n.getAttribute('data-name'),
                    ariaLabel: n.getAttribute('aria-label'),
                    title: n.getAttribute('title'),
                    text: (n.innerText || '').trim().slice(0, 80),
                    x: Math.round(r.x), y: Math.round(r.y),
                });
            });
            return out;
        }""")

        # ------------------------------------------------------------------
        # Write snapshot.
        # ------------------------------------------------------------------
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"alerts-{ts}.json"
        out_path.write_text(json.dumps(snapshot, indent=2))

        print(f"Wrote snapshot to {out_path}")
        print()
        print("Phase 1 dialog found:", bool(snapshot.get("phase1_dialog_selector")))
        if snapshot.get("phase1_dialog_dump"):
            print(f"Phase 1 dialog controls: {len(snapshot['phase1_dialog_dump'])}")
            print(f"Phase 1 dropdowns found: {len(snapshot.get('phase1_dropdowns', []))}")
        print(f"Phase 2 panel entries: {len(snapshot.get('phase2_panel_dump', []))}")
    return 0


if __name__ == "__main__":
    asyncio.run(main())
