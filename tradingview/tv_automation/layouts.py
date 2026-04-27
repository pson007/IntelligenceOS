"""Layouts surface — save/load/rename/delete TradingView chart layouts.

A TradingView "layout" is a named saved state of the chart: symbol,
interval, indicators, drawings, order-panel visibility, widget-bar
visibility, etc. Every chart URL of the form
`https://www.tradingview.com/chart/<layout_id>/` references a saved
layout. Switching layouts reloads the whole chart; creating a new
layout starts fresh with TV's defaults.

CLI:
    tv layouts list                    # all saved layouts (from picker)
    tv layouts current                 # active layout name
    tv layouts save                    # ⌘S — save dirty changes
    tv layouts save-as "My Layout"     # new layout + rename
    tv layouts rename "New Name"       # rename the active layout
    tv layouts load "Money Print"      # switch to a saved layout
    tv layouts delete "Old Test"       # delete a saved layout
    tv layouts copy "Money Print 2"    # clone current → new name

Menu items use Unicode U+2026 ellipsis (…) NOT three ASCII dots —
address labels by exact text.
"""

from __future__ import annotations

import argparse
from typing import Any

from playwright.async_api import Locator, Page

from . import config
from .lib import audit, selectors
from .lib.cli import run
from .lib.context import chart_session
from .lib.errors import ChartNotReadyError, ModalError, VerificationFailedError
from .lib.guards import with_lock
from .lib.overlays import dismiss_toasts

# Unicode ellipsis character used in all TV menu labels.
ELL = "\u2026"


# ---------------------------------------------------------------------------
# Menu helpers.
# ---------------------------------------------------------------------------

async def _open_manage_menu(page: Page) -> None:
    """Open the layouts dropdown (top-header 'Manage layouts' button)."""
    await dismiss_toasts(page)
    btn = await selectors.first_visible(
        page, "layouts", "manage_button", timeout_ms=5000,
    )
    await btn.click()
    # Wait for the popup menu.
    try:
        await page.wait_for_selector(
            selectors.candidates("layouts", "dropdown_container")[0],
            state="visible", timeout=3000,
        )
    except Exception as e:
        raise ModalError(f"Layouts dropdown didn't appear: {e}")


async def _click_menu_label(page: Page, label: str) -> None:
    """Click the menu item whose first-line text equals `label`.

    Scoped to the currently-open menuBox popup. Matches by exact text
    (not substring) — `has-text("Save")` would also match "Save
    layout" etc. Uses JS for the exact-text match since Playwright's
    `:text-is` can miss multi-child labels.
    """
    clicked = await page.evaluate(
        r"""(wanted) => {
            const popups = Array.from(document.querySelectorAll(
                '[class*="menuBox-"]'
            )).filter(p => {
                const r = p.getBoundingClientRect();
                return r.width > 50 && r.height > 50;
            });
            if (!popups.length) return {clicked: false, reason: 'no popup'};
            const popup = popups[popups.length - 1];
            // Prefer items whose FIRST LINE equals `wanted` — skip the
            // parent wrapper that contains all labels concatenated.
            const candidates = Array.from(popup.querySelectorAll('*'))
                .filter(n => {
                    const r = n.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return false;
                    const t = (n.innerText || '').trim();
                    if (!t) return false;
                    const firstLine = t.split('\n')[0].trim();
                    return firstLine === wanted && t.length < 80;
                });
            if (!candidates.length) return {
                clicked: false, reason: 'no match', wanted,
            };
            // Click the deepest-DOM candidate (most specific).
            candidates.sort((a, b) => {
                let da = 0, db = 0, p = a;
                while (p) { da++; p = p.parentElement; }
                p = b;
                while (p) { db++; p = p.parentElement; }
                return db - da;
            });
            candidates[0].click();
            return {clicked: true};
        }""",
        label,
    )
    if not clicked.get("clicked"):
        raise ModalError(
            f"Menu item {label!r} not clickable: {clicked.get('reason')}"
        )
    await page.wait_for_timeout(500)


async def _read_recent_layouts(page: Page) -> list[str]:
    """Read the RECENTLY USED section of the currently-open dropdown."""
    return await page.evaluate(r"""() => {
        const popups = Array.from(document.querySelectorAll(
            '[class*="menuBox-"]'
        )).filter(p => {
            const r = p.getBoundingClientRect();
            return r.width > 50 && r.height > 50;
        });
        if (!popups.length) return [];
        const popup = popups[popups.length - 1];
        if (!(popup.innerText || '').includes('RECENTLY USED')) return [];
        // Walk DOM: once we see the 'RECENTLY USED' section header,
        // every subsequent ellipsis-classed row (up to 'Open layout…')
        // is a layout name.
        const names = [];
        const rows = Array.from(popup.querySelectorAll('[class*="ellipsis-"]'));
        let inRecent = false;
        for (const e of rows) {
            const t = (e.innerText || '').trim();
            if (!t) continue;
            if (t === 'RECENTLY USED') { inRecent = true; continue; }
            if (t === 'Open layout\u2026') break;
            if (!inRecent) continue;
            if (!names.includes(t)) names.push(t);
        }
        return names;
    }""")


async def _dismiss_menu(page: Page) -> None:
    """Close any open dropdown menu."""
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Picker dialog helpers (Open Layout…).
# ---------------------------------------------------------------------------

async def _open_picker(page: Page) -> Locator:
    """Open the full layouts picker dialog. Returns its locator."""
    await _open_manage_menu(page)
    await _click_menu_label(page, f"Open layout{ELL}")
    try:
        dlg = await selectors.first_visible(
            page, "layouts", "open_layout_dialog", timeout_ms=5000,
        )
        return dlg
    except Exception as e:
        raise ModalError(f"Open layout dialog didn't appear: {e}")


async def _picker_rows(page: Page) -> list[dict]:
    """Read all rows from the currently-open picker dialog.

    Rows are `<a data-name="load-chart-dialog-item" role="row">`
    anchors — each holds a two-line cell (name + 'SYMBOL, INTERVAL').
    """
    return await page.evaluate(r"""() => {
        const rows = Array.from(document.querySelectorAll(
            '[data-name="load-chart-dialog-item"]'
        )).filter(n => {
            const r = n.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        });
        return rows.map(r => {
            const lines = (r.innerText || '').split('\n').map(l => l.trim()).filter(l => l);
            return {
                name: lines[0] || '',
                symbol_interval: lines[1] || '',
            };
        });
    }""")


async def _picker_search(page: Page, query: str) -> None:
    """Type a query into the picker's search input. The picker list
    is virtualized — only ~10 rows are in the DOM at any moment, so
    layouts further down the list (or alphabetically later) won't be
    found without filtering first. TV's placeholder is 'Search'."""
    # Target the input directly by placeholder — more robust than
    # the class-prefix selector, which has been hit-or-miss.
    search = page.locator(
        'div[class*="dialog-"] input[placeholder="Search"]'
    ).first
    try:
        await search.wait_for(state="visible", timeout=3000)
    except Exception:
        # Picker may not have rendered its search yet — give it a moment.
        await page.wait_for_timeout(500)
        await search.wait_for(state="visible", timeout=3000)
    await search.fill(query)
    # Let the list re-virtualize after the filter applies.
    await page.wait_for_timeout(800)


async def _click_picker_row(page: Page, name: str) -> dict:
    """Find the picker anchor-row matching `name` (exact first-line
    text) and click it. Targets the `<a data-name="load-chart-dialog-item">`
    element directly — clicking a child cell is a no-op since only the
    anchor carries the navigation handler.

    Caller is expected to have filtered the list via `_picker_search`
    before calling this, so the target row is in the current
    virtualized window."""
    # Find the row's href — the anchor carries
    # href="https://www.tradingview.com/chart/<layout_id>/". Rather than
    # JS-click (which React sometimes swallows), we read the href and
    # navigate the page directly. That's semantically equivalent to
    # the user clicking the link and avoids the stale-click bug.
    href = await page.evaluate(
        r"""(wanted) => {
            const rows = Array.from(document.querySelectorAll(
                '[data-name="load-chart-dialog-item"]'
            )).filter(n => {
                const r = n.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            });
            const rowName = r => {
                const lines = (r.innerText || '')
                    .split('\n').map(l => l.trim()).filter(l => l);
                return lines[0] || '';
            };
            const match = rows.find(r => rowName(r) === wanted);
            if (!match) return {
                found: false,
                candidates: rows.map(rowName),
            };
            return {
                found: true,
                href: match.getAttribute('href'),
                row_text: (match.innerText || '').trim().slice(0, 80),
            };
        }""",
        name,
    )
    if not href.get("found"):
        return {"clicked": False, "reason": "name_not_found",
                "candidates": href.get("candidates")}
    target_href = href.get("href")
    if not target_href:
        return {"clicked": False, "reason": "row_has_no_href"}
    # Navigate — TV's chart SPA handles the layout switch.
    await page.goto(target_href, wait_until="domcontentloaded")
    return {
        "clicked": True,
        "href": target_href,
        "row_text": href.get("row_text"),
    }


# ---------------------------------------------------------------------------
# Rename flow (shared by save-as + rename).
# ---------------------------------------------------------------------------

async def _rename_via_dialog(page: Page, new_name: str) -> None:
    """Click Rename…, fill the dialog, press Enter. Assumes the
    rename option is present in the currently-open (or about-to-open)
    menu — we open the menu, click Rename, then drive the input."""
    await _open_manage_menu(page)
    await _click_menu_label(page, f"Rename{ELL}")
    await page.wait_for_timeout(600)

    # The rename dialog focuses its text input with the existing name
    # selected. Select-all, type the new name, press Enter.
    focused_tag = await page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    if focused_tag == "INPUT":
        await page.keyboard.press("ControlOrMeta+a")
        await page.keyboard.type(new_name)
    else:
        # Fallback: find the input directly.
        inp = page.locator(
            'div[class*="dialog"] input[type="text"], '
            'input[data-name="name-input"]'
        ).first
        await inp.wait_for(state="visible", timeout=3000)
        await inp.fill(new_name)

    await page.keyboard.press("Enter")
    await page.wait_for_timeout(1200)


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------

async def current_layout() -> dict:
    """Read the active layout name from the header toolbar.

    The layout name is rendered as a sibling of the 'Manage layouts'
    button (inside the same toolbar group). We find it by looking for
    a text-bearing `<span>` or `<button>` immediately preceding the
    manage button within its parent row — avoids the walker grabbing
    unrelated toolbar text like 'Save' or 'Open menu'.
    """
    async with chart_session() as (_ctx, page):
        info = await page.evaluate(r"""() => {
            const btn = document.querySelector('[data-name="save-load-menu"]');
            if (!btn) return null;
            const btnRect = btn.getBoundingClientRect();
            // Scan the whole document for short-text elements in the
            // same header row (y within ±20px of the manage button)
            // and to the left of it. The closest such element (in x)
            // is the layout name rendered by TV's toolbar.
            const all = Array.from(document.querySelectorAll('span, div, button'))
                .filter(n => {
                    const r = n.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return false;
                    if (Math.abs(r.y - btnRect.y) > 20) return false;
                    if (r.x >= btnRect.x) return false;
                    const t = (n.innerText || '').trim();
                    // Single-line short text — not an interval button like "1m".
                    if (!t || t.length < 2 || t.length > 50) return false;
                    if (t.includes('\n')) return false;
                    // Skip "1m", "5m", "1h", "D" etc. (interval buttons).
                    if (/^\d+[mhdD]$|^D$|^W$|^M$/.test(t)) return false;
                    // Skip symbol ticker area to far left (typically x<500).
                    // The layout name renders at x~900-1100 in a standard layout.
                    return r.x > 700;
                });
            if (all.length === 0) return {layout_name: null};
            // Closest to manage button (rightmost).
            all.sort((a, b) => b.getBoundingClientRect().x - a.getBoundingClientRect().x);
            return {layout_name: (all[0].innerText || '').trim()};
        }""")
        name = (info or {}).get("layout_name")
        # URL encodes the layout id (the /chart/<id>/ segment).
        url = page.url
        layout_id = None
        import re
        m = re.search(r"/chart/([^/?]+)", url)
        if m and m.group(1):
            layout_id = m.group(1)
        audit.log("layouts.current", name=name, layout_id=layout_id)
        return {"ok": True, "name": name, "layout_id": layout_id, "url": url}


async def list_layouts() -> dict:
    """List all saved layouts from the Open Layout… picker dialog.
    This is the FULL list — not limited like the RECENTLY USED
    section of the dropdown (which caps at ~8)."""
    async with chart_session() as (_ctx, page):
        await _open_picker(page)
        rows = await _picker_rows(page)
        # Also grab the RECENTLY USED shortlist for context.
        # Picker occludes the dropdown, so close picker first, then
        # open dropdown, then close dropdown.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        await _open_manage_menu(page)
        recent = await _read_recent_layouts(page)
        await _dismiss_menu(page)
        audit.log("layouts.list", count=len(rows))
        return {
            "ok": True, "count": len(rows),
            "layouts": rows, "recently_used": recent,
        }


async def save() -> dict:
    """Save the current chart state to the currently-loaded layout."""
    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("layouts.save"):
                await _open_manage_menu(page)
                await _click_menu_label(page, "Save layout")
                await page.wait_for_timeout(800)
                return {"ok": True}


async def save_as(new_name: str) -> dict:
    """Create a new layout with the given name. Delegates to
    [create_layout.py](../create_layout.py)'s proven flow:
    Create new layout… → wait for canvas re-paint → dismiss welcome
    overlay → Rename… → type new name → Enter."""
    if not new_name or not new_name.strip():
        raise ValueError("new_name must be non-empty")
    if len(new_name) > 60:
        raise ValueError("new_name too long (max 60 chars)")

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("layouts.save_as", new_name=new_name) as ac:
                # Verify uniqueness against picker list BEFORE creating,
                # so we don't end up with a duplicate-name layout.
                await _open_picker(page)
                existing = await _picker_rows(page)
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)
                if any(r.get("name") == new_name for r in existing):
                    raise VerificationFailedError(
                        "save_as uniqueness",
                        expected=f"no existing layout named {new_name!r}",
                        actual=f"found one in picker",
                    )

                # Capture saved-chart count via TV's JS API BEFORE the
                # create step. This is the safety net against a
                # data-destruction class of bug observed 2026-04-26: in
                # CDP-attach mode the "Create new layout..." menu click
                # has been observed to silently no-op (chart appears to
                # reload but no new chart is registered backend-side).
                # Without the post-create count check, the subsequent
                # rename then hits the ACTIVE layout — overwriting the
                # user's working layout (e.g. "1run Automation") with
                # the new_name.
                async def _saved_chart_count() -> int:
                    return await page.evaluate(r"""() => new Promise(r => {
                        try {
                            window.TradingViewApi.getSavedCharts(charts =>
                                r((charts||[]).length));
                            setTimeout(() => r(-1), 5000);
                        } catch (e) { r(-1); }
                    })""")

                before_count = await _saved_chart_count()

                # Step 1: Create new blank layout.
                await _open_manage_menu(page)
                await _click_menu_label(page, f"Create new layout{ELL}")
                await page.wait_for_timeout(2500)
                await page.wait_for_selector(
                    "canvas", state="visible", timeout=15_000,
                )

                # Verify a NEW layout was actually created backend-side
                # before doing anything destructive. Hard-fail if the
                # count didn't increase — the in-progress rename would
                # otherwise damage the active layout.
                await page.wait_for_timeout(1500)
                after_count = await _saved_chart_count()
                if before_count >= 0 and after_count <= before_count:
                    audit.log("layouts.save_as.create_no_op",
                              before_count=before_count,
                              after_count=after_count,
                              attempted_name=new_name)
                    raise VerificationFailedError(
                        "save_as.create_layout",
                        expected=f"layout count > {before_count}",
                        actual=f"got {after_count} — create_new_layout "
                               f"silently no-op'd; aborting BEFORE rename "
                               f"to protect the active layout",
                    )

                # Step 2: dismiss TV's welcome-video overlay if present.
                video = page.locator('[class*="isShowVideo"]').first
                if await video.count() > 0:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)

                # Step 3: rename.
                await _rename_via_dialog(page, new_name)
                await page.wait_for_timeout(800)

                # Verify new layout is now current.
                info = await current_layout()
                ac["verified_name"] = info.get("name")
                return {
                    "ok": True, "new_name": new_name,
                    "verified_name": info.get("name"),
                    "layout_id": info.get("layout_id"),
                }


async def rename(new_name: str) -> dict:
    """Rename the currently-loaded layout."""
    if not new_name or not new_name.strip():
        raise ValueError("new_name must be non-empty")
    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("layouts.rename", new_name=new_name):
                await _rename_via_dialog(page, new_name)
                info = await current_layout()
                return {
                    "ok": True, "new_name": new_name,
                    "verified_name": info.get("name"),
                }


async def load(name: str) -> dict:
    """Load a saved layout by name. Opens the picker, clicks the row,
    waits for the chart to reload."""
    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("layouts.load", name=name) as ac:
                prev_url = page.url
                await _open_picker(page)
                await _picker_search(page, name)
                result = await _click_picker_row(page, name)
                ac["click_result"] = result
                if not result.get("clicked"):
                    return {
                        "ok": False, "name": name,
                        "reason": result.get("reason"),
                    }
                # After the href-navigate, TV reloads the chart. Wait
                # for URL to change AND canvas to repaint AND the
                # toolbar layout-name to update before verifying.
                for _ in range(20):
                    await page.wait_for_timeout(300)
                    if page.url != prev_url:
                        break
                await page.wait_for_selector(
                    "canvas", state="visible", timeout=15_000,
                )
                # Poll the toolbar name — React-rendered, hydrates
                # asynchronously after canvas reappears.
                verified_name: str | None = None
                for _ in range(10):
                    await page.wait_for_timeout(400)
                    info = await page.evaluate(r"""() => {
                        const btn = document.querySelector('[data-name="save-load-menu"]');
                        if (!btn) return null;
                        const btnRect = btn.getBoundingClientRect();
                        const all = Array.from(document.querySelectorAll('span, div, button'))
                            .filter(n => {
                                const r = n.getBoundingClientRect();
                                if (r.width === 0 || r.height === 0) return false;
                                if (Math.abs(r.y - btnRect.y) > 20) return false;
                                if (r.x >= btnRect.x) return false;
                                const t = (n.innerText || '').trim();
                                if (!t || t.length < 2 || t.length > 50) return false;
                                if (t.includes('\n')) return false;
                                if (/^\d+[mhdD]$|^D$|^W$|^M$/.test(t)) return false;
                                return r.x > 700;
                            });
                        if (!all.length) return null;
                        all.sort((a, b) => b.getBoundingClientRect().x - a.getBoundingClientRect().x);
                        return (all[0].innerText || '').trim();
                    }""")
                    if info:
                        verified_name = info
                        break

                import re
                m = re.search(r"/chart/([^/?]+)", page.url)
                layout_id = m.group(1) if m and m.group(1) else None
                return {
                    "ok": True, "name": name,
                    "verified_name": verified_name,
                    "layout_id": layout_id,
                    "url": page.url,
                }


async def copy(new_name: str) -> dict:
    """Clone the currently-loaded layout as a new layout with the
    given name. Uses TV's 'Make a copy…' menu action."""
    if not new_name or not new_name.strip():
        raise ValueError("new_name must be non-empty")
    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("layouts.copy", new_name=new_name):
                await _open_manage_menu(page)
                await _click_menu_label(page, f"Make a copy{ELL}")
                await page.wait_for_timeout(1200)
                # The copy typically opens a name dialog. If it does,
                # fill the new name. If it just creates with auto-name,
                # the follow-up Rename… handles it.
                focused_tag = await page.evaluate(
                    "() => document.activeElement ? document.activeElement.tagName : null"
                )
                if focused_tag == "INPUT":
                    await page.keyboard.press("ControlOrMeta+a")
                    await page.keyboard.type(new_name)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1200)
                else:
                    # No dialog — auto-created. Rename the new active layout.
                    await _rename_via_dialog(page, new_name)
                info = await current_layout()
                return {
                    "ok": True, "new_name": new_name,
                    "verified_name": info.get("name"),
                }


async def delete_layout(name: str, *, dry_run: bool = False) -> dict:
    """Delete a saved layout by name.

    Delete UI is exposed per-row in the picker — hover reveals a trash
    icon. We dispatch mouseenter to force the reveal, click the trash,
    then click the confirm in the destructive-action dialog (same
    pattern as alerts.delete).
    """
    async with chart_session() as (_ctx, page):
        await _open_picker(page)
        if dry_run:
            rows = await _picker_rows(page)
            found = any(r.get("name") == name for r in rows)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
            return {
                "ok": found, "dry_run": True, "name": name,
                "would_delete": found,
            }

        async with with_lock("tv_browser"):
            with audit.timed("layouts.delete", name=name) as ac:
                # Find + hover + click the delete button.
                click_result = await page.evaluate(
                    r"""(wanted) => {
                        const dialogs = Array.from(document.querySelectorAll(
                            'div[class*="dialog-"]'
                        )).filter(d => {
                            const r = d.getBoundingClientRect();
                            return r.width > 400 && (d.innerText || '').includes('LAYOUT NAME');
                        });
                        if (!dialogs.length) return {clicked: false, reason: 'no_picker'};
                        const dlg = dialogs[dialogs.length - 1];
                        const rows = Array.from(dlg.querySelectorAll('*'))
                            .filter(n => {
                                const r = n.getBoundingClientRect();
                                if (r.width < 100 || r.height < 20 || r.height > 80) return false;
                                const lines = (n.innerText || '').split('\n').map(l => l.trim()).filter(l => l);
                                return lines.length >= 2 && lines[0] === wanted && lines[1].includes(',');
                            });
                        if (!rows.length) return {clicked: false, reason: 'name_not_found'};
                        const row = rows[0];
                        row.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                        // Look for a delete/trash button inside the row.
                        const btn = row.querySelector(
                            'button[aria-label*="elete" i], '
                            + 'button[aria-label*="emove" i], '
                            + '[data-name*="delete" i], '
                            + '[data-name*="trash" i], '
                            + 'button[title*="elete" i]'
                        );
                        if (!btn) {
                            // Maybe the trash is in a parent row wrapper
                            // that also holds hover-reveal buttons.
                            let parent = row.parentElement;
                            for (let i = 0; i < 3 && parent; i++) {
                                const p = parent.querySelector(
                                    'button[aria-label*="elete" i], '
                                    + 'button[title*="elete" i]'
                                );
                                if (p) { p.click(); return {clicked: true, via: 'parent'}; }
                                parent = parent.parentElement;
                            }
                            // List any visible buttons in the row for debugging.
                            const btns = Array.from(row.querySelectorAll('button'))
                                .map(b => ({
                                    aria: b.getAttribute('aria-label'),
                                    title: b.getAttribute('title'),
                                    dn: b.getAttribute('data-name'),
                                }));
                            return {clicked: false, reason: 'no_delete_button', buttons_in_row: btns};
                        }
                        btn.click();
                        return {clicked: true};
                    }""",
                    name,
                )
                ac["click_result"] = click_result
                if not click_result.get("clicked"):
                    await page.keyboard.press("Escape")
                    return {
                        "ok": False, "name": name,
                        "reason": click_result.get("reason"),
                        "debug": click_result,
                    }

                # Confirm the destructive action.
                await page.wait_for_timeout(500)
                confirmed = await page.evaluate(r"""() => {
                    const POS = ['Delete', 'Yes, delete', 'Yes', 'Remove', 'Confirm'];
                    const dialogs = Array.from(document.querySelectorAll(
                        'div[class*="dialog-"]'
                    )).filter(d => {
                        const r = d.getBoundingClientRect();
                        return r.width > 200 && r.height > 100;
                    });
                    for (const dlg of dialogs) {
                        const btns = Array.from(dlg.querySelectorAll('button'));
                        for (const label of POS) {
                            const m = btns.find(b => (b.innerText || '').trim() === label);
                            if (m) { m.click(); return label; }
                        }
                    }
                    return null;
                }""")
                ac["confirmed"] = confirmed

                # Verify disappearance.
                await page.wait_for_timeout(1200)
                remaining = await _picker_rows(page)
                gone = not any(r.get("name") == name for r in remaining)
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)
                return {
                    "ok": True, "dry_run": False, "name": name,
                    "verified": gone, "confirmed": confirmed,
                }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.layouts")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all saved layouts")
    sub.add_parser("current", help="Show the currently-loaded layout")
    sub.add_parser("save", help="Save dirty changes to the current layout")

    sa = sub.add_parser("save-as", help="Create new layout with name")
    sa.add_argument("name")

    rn = sub.add_parser("rename", help="Rename the current layout")
    rn.add_argument("new_name")

    ld = sub.add_parser("load", help="Load a saved layout by name")
    ld.add_argument("name")

    cp = sub.add_parser("copy", help="Clone current layout as new name")
    cp.add_argument("new_name")

    dl = sub.add_parser("delete", help="Delete a saved layout")
    dl.add_argument("name")
    dl.add_argument("--dry-run", action="store_true")

    args = p.parse_args()
    if args.cmd == "list":
        run(lambda: list_layouts())
    elif args.cmd == "current":
        run(lambda: current_layout())
    elif args.cmd == "save":
        run(lambda: save())
    elif args.cmd == "save-as":
        run(lambda: save_as(args.name))
    elif args.cmd == "rename":
        run(lambda: rename(args.new_name))
    elif args.cmd == "load":
        run(lambda: load(args.name))
    elif args.cmd == "copy":
        run(lambda: copy(args.new_name))
    elif args.cmd == "delete":
        run(lambda: delete_layout(args.name, dry_run=args.dry_run))


if __name__ == "__main__":
    _main()
