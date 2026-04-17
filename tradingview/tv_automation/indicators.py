"""Indicators surface — add/list/remove/configure chart indicators.

Programmatic equivalent of TradingView's right-side "Indicators,
metrics, and strategies" dialog (opened by the `/` hotkey). The main
use case is letting an LLM build a chart setup before applying a
Pine strategy — e.g. "add RSI, add VWAP, then run the Pine script."

Two UI surfaces:

  1. **Indicators dialog** — modal picker with categories (Personal,
     Built-In, Community, Store). `add_indicator` opens this via the
     `/` shortcut, fills the search box, clicks the first matching
     list-item row, then closes the modal.

  2. **Chart indicator legend** — the top-left stack on the chart.
     Each entry is a `[data-qa-id="legend-source-item"]` with
     hover-revealed action buttons (settings, delete, show-hide).
     `list` / `remove` / `configure` all work against this.

CLI:
    tv indicators list
    tv indicators add "Relative Strength Index"
    tv indicators remove "RSI"
    tv indicators configure "RSI" '{"length": 21, "overbought": 75}'
"""

from __future__ import annotations

import argparse
import json as json_lib
from typing import Any

from playwright.async_api import Page

from .lib import audit, selectors
from .lib.cli import run
from .lib.context import chart_session
from .lib.errors import ChartNotReadyError, ModalError, VerificationFailedError
from .lib.guards import with_lock
from .lib.modal import fill_by_label, confirm
from .lib.overlays import dismiss_toasts


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

async def _open_indicators_dialog(page: Page) -> None:
    """Open the Indicators picker via the `/` keyboard shortcut.

    Why not click the header button: the `[data-name="open-indicators-dialog"]`
    element is responsive — TV collapses it to icon-only at narrow
    chart widths, and Playwright often reports it "not visible" even
    when it's in the DOM. The keyboard shortcut is deterministic,
    but requires the chart canvas to have focus.
    """
    await dismiss_toasts(page)
    # If the dialog is already open (e.g. from a prior failed run),
    # reuse it — pressing `/` again may do nothing or double-toggle.
    if await selectors.any_visible(page, "indicators_dialog", "dialog"):
        return
    # Focus the chart canvas so `/` is interpreted as the dialog shortcut
    # and not delivered to whatever input happens to be focused.
    canvas = page.locator("canvas").first
    if await canvas.count() == 0:
        raise ChartNotReadyError("No chart canvas on page")
    box = await canvas.bounding_box()
    if box:
        await page.mouse.click(
            int(box["x"] + box["width"] * 0.5),
            int(box["y"] + box["height"] * 0.5),
        )
        await page.wait_for_timeout(200)
    await page.keyboard.press("/")
    try:
        await selectors.first_visible(
            page, "indicators_dialog", "dialog", timeout_ms=5000,
        )
    except Exception as e:
        raise ModalError(
            f"Indicators dialog didn't open within 5s after `/`: {e}"
        )


async def _close_indicators_dialog(page: Page) -> None:
    """Dismiss the Indicators dialog. Escape is the cleanest path."""
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)


async def _ensure_legend_expanded(page: Page) -> None:
    """Ensure the chart's indicator-legend drawer is expanded.

    When the legend is "closed" (default state on many layouts),
    all `legend-source-item` descendants sit inside a parent whose
    `display` is `none`. Clicks dispatched to their buttons fire
    but React's event handlers no-op on non-rendered elements — so
    delete/settings actions silently fail.

    `[data-qa-id="legend-toggler"]` has aria-label="Show indicators
    legend" when closed, "Hide indicators legend" when open. We
    click it only when the sources drawer is actually closed,
    detected by the `closed-` class on `legend-sources-wrapper`.
    """
    is_closed = await page.evaluate(r"""() => {
        const wrap = document.querySelector(
            '[data-qa-id="legend-sources-wrapper"]'
        );
        if (!wrap) return false;
        return typeof wrap.className === 'string'
            && wrap.className.includes('closed');
    }""")
    if not is_closed:
        return
    try:
        toggler = await selectors.first_visible(
            page, "chart_legend", "toggler", timeout_ms=2000,
        )
        await toggler.click()
        await page.wait_for_timeout(400)
    except Exception:
        pass


async def _fire_click_events(page: Page, element_selector: str) -> bool:
    """Dispatch the full pointer/mouse event sequence TV's legend
    buttons require to actually fire their React click handlers.

    A plain `.click()` or `element.click()` doesn't work because:
      1. The chart's `pane-top-canvas` is stacked above the legend
         area, intercepting all real pointer events that target the
         legend buttons' screen coords.
      2. TV's React handlers are wired for the full sequence
         (pointerdown → mousedown → pointerup → mouseup → click) —
         a lone `click` dispatches but no listener fires.

    Dispatching the full synthetic sequence via JS bypasses hit-test
    and satisfies the handler — verified 2026-04-17 against
    `legend-delete-action`.
    """
    return await page.evaluate(
        r"""(sel) => {
            const btn = document.querySelector(sel);
            if (!btn) return false;
            const r = btn.getBoundingClientRect();
            const opts = {
                bubbles: true,
                clientX: r.x + r.width / 2,
                clientY: r.y + r.height / 2,
                button: 0,
            };
            try { btn.dispatchEvent(new PointerEvent('pointerdown', opts)); }
            catch (e) {}
            btn.dispatchEvent(new MouseEvent('mousedown', opts));
            try { btn.dispatchEvent(new PointerEvent('pointerup', opts)); }
            catch (e) {}
            btn.dispatchEvent(new MouseEvent('mouseup', opts));
            btn.dispatchEvent(new MouseEvent('click', opts));
            return true;
        }""",
        element_selector,
    )


async def _read_legend_items(page: Page) -> list[dict]:
    """Return every indicator visible in the chart's top-left legend.

    The first item is usually the main price series (the symbol
    itself); we flag that via `is_main_series: true`. Other items are
    built-in indicators or Pine scripts.
    """
    return await page.evaluate(r"""() => {
        const items = Array.from(document.querySelectorAll(
            '[data-qa-id="legend-source-item"]'
        ));
        return items.map((it, idx) => {
            // The first line of innerText is usually the indicator
            // name. For the main series, it's the symbol (e.g. 'MNQ1!'
            // or 'Ultima MNQ+' for a Pine strategy at index 0).
            // Price / value suffixes are appended without whitespace
            // (e.g. 'Ultima MNQ+0.000.00') — split on first digit-run
            // to isolate the name.
            const raw = (it.innerText || '').trim();
            // Name heuristic: take characters until we hit a digit or
            // a status/value-like character sequence. Works for most
            // plain indicator names; Pine strategies with numeric
            // names would need manual parsing.
            const firstLine = raw.split('\n')[0];
            // Stop at first position where digit / empty-set symbol
            // begins a value. '\u2205' = ∅ (TV's 'no value' char).
            const m = firstLine.match(/^([^\d\u2205]*?)(?:[-+]?\d|\u2205)/);
            const name = (m ? m[1] : firstLine).trim();
            return {
                index: idx,
                is_main_series: idx === 0,
                name: name || firstLine,
                raw_text: raw.slice(0, 120),
                has_status: !!it.querySelector(
                    '[data-qa-id="legend-source-item-status"]'
                ),
            };
        });
    }""")


async def _fill_search(page: Page, query: str) -> None:
    """Fill the indicators-dialog search box and let results re-render."""
    inp = await selectors.first_visible(
        page, "indicators_dialog", "search_input", timeout_ms=3000,
    )
    await inp.fill(query)
    # Dialog debounces search by ~500ms — wait for the list to update.
    await page.wait_for_timeout(700)


async def _click_first_result(page: Page) -> dict:
    """Click the first row in the results list. Returns row info."""
    info = await page.evaluate(r"""() => {
        const dlg = document.querySelector('[data-name="indicators-dialog"]');
        if (!dlg) return {clicked: false, reason: 'no_dialog'};
        const rows = Array.from(dlg.querySelectorAll('[data-role="list-item"]'))
            .filter(n => {
                const r = n.getBoundingClientRect();
                return r.width > 100 && r.height > 20;
            });
        if (!rows.length) return {clicked: false, reason: 'no_results'};
        const row = rows[0];
        row.click();
        return {
            clicked: true,
            row_text: (row.innerText || '').trim().slice(0, 80),
        };
    }""")
    return info


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------

async def list_indicators() -> dict:
    """Read the chart's indicator legend. Returns a list of dicts with
    `name` / `index` / `is_main_series` keys."""
    async with chart_session() as (_ctx, page):
        items = await _read_legend_items(page)
        audit.log("indicators.list", count=len(items))
        return {"ok": True, "count": len(items), "indicators": items}


async def add_indicator(query: str, *, dry_run: bool = False) -> dict:
    """Add an indicator to the chart.

    `query` is the search string. TV's search is fuzzy — "rsi" matches
    "Relative Strength Index" as the top built-in result. Pass a
    specific exact name (e.g. "Volume Weighted Average Price") when
    you need determinism, or the generic short form otherwise.

    Returns the new legend state. `verified` is True when the legend
    row count grew by at least 1 after the add.
    """
    if not query or not query.strip():
        raise ValueError("query must be non-empty")

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed(
                "indicators.add", query=query, dry_run=dry_run,
            ) as ac:
                # Snapshot legend before add.
                before = await _read_legend_items(page)
                before_names = [it.get("name") for it in before]

                await _open_indicators_dialog(page)
                await _fill_search(page, query)

                # Peek the first result to verify it looks plausible
                # before clicking.
                first_text = await page.evaluate(r"""() => {
                    const dlg = document.querySelector('[data-name="indicators-dialog"]');
                    if (!dlg) return null;
                    const rows = Array.from(dlg.querySelectorAll('[data-role="list-item"]'));
                    return rows[0] ? (rows[0].innerText || '').trim().slice(0, 80) : null;
                }""")
                ac["first_result_preview"] = first_text

                if dry_run:
                    await _close_indicators_dialog(page)
                    return {
                        "ok": True, "dry_run": True,
                        "query": query,
                        "first_result": first_text,
                        "before_count": len(before),
                    }

                click = await _click_first_result(page)
                ac["click_result"] = click
                if not click.get("clicked"):
                    await _close_indicators_dialog(page)
                    return {
                        "ok": False, "query": query,
                        "reason": click.get("reason"),
                    }
                # TV closes the modal automatically on add in some builds,
                # and keeps it open (ready to add multiple) in others.
                # Close explicitly either way.
                await page.wait_for_timeout(800)
                await _close_indicators_dialog(page)

                # Verify — legend gained an item.
                after = await _read_legend_items(page)
                added = [
                    it for it in after
                    if it.get("name") not in before_names
                ]
                verified = len(after) > len(before)
                ac["verified"] = verified
                return {
                    "ok": True, "dry_run": False, "verified": verified,
                    "query": query,
                    "added": added,
                    "count_before": len(before),
                    "count_after": len(after),
                }


async def remove_indicator(name: str, *, dry_run: bool = False) -> dict:
    """Remove an indicator from the chart by name (substring match
    against the legend item's parsed name)."""
    if not name or not name.strip():
        raise ValueError("name must be non-empty")

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed(
                "indicators.remove", name=name, dry_run=dry_run,
            ) as ac:
                # Expand the legend before touching per-row buttons —
                # when the drawer is closed, button clicks no-op.
                await _ensure_legend_expanded(page)
                before = await _read_legend_items(page)
                matches = [
                    it for it in before
                    if name.lower() in (it.get("name") or "").lower()
                ]
                if not matches:
                    return {
                        "ok": False, "reason": "name_not_found",
                        "name": name,
                        "available": [it.get("name") for it in before],
                    }
                if matches[0].get("is_main_series"):
                    return {
                        "ok": False, "reason": "cannot_remove_main_series",
                        "name": name,
                    }

                target_index = matches[0]["index"]
                ac["target_index"] = target_index
                ac["target_name"] = matches[0].get("name")

                if dry_run:
                    return {
                        "ok": True, "dry_run": True,
                        "name": name, "would_remove": matches[0],
                    }

                # Mark the target button so we can address it uniquely,
                # then fire the full pointer-event sequence. A lone
                # `btn.click()` doesn't work (see `_fire_click_events`).
                marker_set = await page.evaluate(
                    r"""(idx) => {
                        const items = Array.from(document.querySelectorAll(
                            '[data-qa-id="legend-source-item"]'
                        ));
                        if (!items[idx]) return false;
                        const item = items[idx];
                        item.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                        const btn = item.querySelector(
                            '[data-qa-id="legend-delete-action"]'
                        );
                        if (!btn) return false;
                        // Clear any prior marker, set a fresh one.
                        document.querySelectorAll(
                            '[data-tv-auto-target]'
                        ).forEach(n => n.removeAttribute('data-tv-auto-target'));
                        btn.setAttribute('data-tv-auto-target', 'remove-btn');
                        return true;
                    }""",
                    target_index,
                )
                if not marker_set:
                    return {
                        "ok": False, "name": name,
                        "reason": "no_delete_button",
                    }
                fired = await _fire_click_events(
                    page, '[data-tv-auto-target="remove-btn"]',
                )
                ac["fired"] = fired
                if not fired:
                    return {
                        "ok": False, "name": name,
                        "reason": "click_dispatch_failed",
                    }

                await page.wait_for_timeout(600)
                after = await _read_legend_items(page)
                gone = not any(
                    name.lower() in (it.get("name") or "").lower()
                    for it in after
                )
                return {
                    "ok": True, "dry_run": False, "verified": gone,
                    "name": name,
                    "count_before": len(before), "count_after": len(after),
                }


async def configure_indicator(name: str, inputs: dict) -> dict:
    """Open the indicator's settings modal and fill its fields.

    `inputs` is a dict mapping label-text → value. Uses
    `lib.modal.fill_by_label` which finds each field by its visible
    label and fills a string / number / bool as appropriate. After
    filling all fields we click the modal's OK/Apply button.
    """
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("inputs must be a non-empty dict of label→value")

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed(
                "indicators.configure", name=name, inputs=inputs,
            ) as ac:
                await _ensure_legend_expanded(page)
                items = await _read_legend_items(page)
                matches = [
                    it for it in items
                    if name.lower() in (it.get("name") or "").lower()
                ]
                if not matches:
                    return {
                        "ok": False, "reason": "name_not_found",
                        "name": name,
                        "available": [it.get("name") for it in items],
                    }
                if matches[0].get("is_main_series"):
                    return {
                        "ok": False, "reason": "cannot_configure_main_series",
                        "name": name,
                    }

                target_index = matches[0]["index"]

                # Open the settings modal via the full event sequence.
                marker_set = await page.evaluate(
                    r"""(idx) => {
                        const items = Array.from(document.querySelectorAll(
                            '[data-qa-id="legend-source-item"]'
                        ));
                        if (!items[idx]) return false;
                        const item = items[idx];
                        item.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                        const btn = item.querySelector(
                            '[data-qa-id="legend-settings-action"]'
                        );
                        if (!btn) return false;
                        document.querySelectorAll(
                            '[data-tv-auto-target]'
                        ).forEach(n => n.removeAttribute('data-tv-auto-target'));
                        btn.setAttribute('data-tv-auto-target', 'settings-btn');
                        return true;
                    }""",
                    target_index,
                )
                if not marker_set:
                    return {"ok": False, "reason": "no_settings_button"}
                opened = await _fire_click_events(
                    page, '[data-tv-auto-target="settings-btn"]',
                )
                if not opened:
                    return {"ok": False, "reason": "click_dispatch_failed"}

                # Wait for the modal.
                from .lib.modal import wait_for_modal
                try:
                    modal = await wait_for_modal(page, timeout_ms=5000)
                except Exception as e:
                    return {"ok": False, "reason": f"modal_not_found: {e}"}

                # Fill each label→value.
                filled = {}
                errors = {}
                for label, value in inputs.items():
                    try:
                        await fill_by_label(modal, label, value)
                        filled[label] = value
                    except Exception as e:
                        errors[label] = str(e)

                ac["filled"] = filled
                ac["errors"] = errors

                if errors:
                    # Cancel the modal — don't commit a partial fill.
                    await page.keyboard.press("Escape")
                    return {
                        "ok": False, "reason": "partial_fill",
                        "filled": filled, "errors": errors,
                    }

                # Commit.
                try:
                    await confirm(modal, "OK")
                except Exception:
                    # Some indicators use 'Apply' or other labels.
                    for label in ("Apply", "Save"):
                        try:
                            await confirm(modal, label)
                            break
                        except Exception:
                            continue

                await page.wait_for_timeout(500)
                return {
                    "ok": True, "name": name, "filled": filled,
                }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.indicators")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List indicators on the current chart")

    ad = sub.add_parser("add", help="Add an indicator (fuzzy name match)")
    ad.add_argument("query", help='e.g. "RSI" or "Relative Strength Index"')
    ad.add_argument("--dry-run", action="store_true")

    rm = sub.add_parser("remove", help="Remove an indicator by name")
    rm.add_argument("name")
    rm.add_argument("--dry-run", action="store_true")

    cfg = sub.add_parser("configure", help="Fill indicator settings fields")
    cfg.add_argument("name")
    cfg.add_argument("inputs_json",
                     help='JSON dict of label→value, e.g. \'{"length": 21}\'')

    args = p.parse_args()
    if args.cmd == "list":
        run(lambda: list_indicators())
    elif args.cmd == "add":
        run(lambda: add_indicator(args.query, dry_run=args.dry_run))
    elif args.cmd == "remove":
        run(lambda: remove_indicator(args.name, dry_run=args.dry_run))
    elif args.cmd == "configure":
        try:
            inputs = json_lib.loads(args.inputs_json)
        except Exception as e:
            raise SystemExit(f"inputs_json must be valid JSON: {e}")
        run(lambda: configure_indicator(args.name, inputs))


if __name__ == "__main__":
    _main()
