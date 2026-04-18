"""Watchlist surface — programmatic management of TradingView's right-sidebar
Watchlist widget.

The watchlist is TV's "set of symbols I care about" surface. Each named
list (e.g. "Tech", "Crypto Watch") stores an ordered sequence of symbols
displayed in the sidebar with realtime quote columns. This module makes
it scriptable so workflows like "morning prep: build today's watchlist
from a screener result" don't require clicking through the UI.

CLI:
    tv watchlist current                # name of the active list
    tv watchlist contents                # symbols in the active list
    tv watchlist add MNQ1!               # add a symbol to the active list
    tv watchlist clear                   # remove ALL symbols (with confirmation)
    tv watchlist create "Tech Watch"     # new list, switches to it
    tv watchlist rename "New Name"       # rename the active list
    tv watchlist load "Tech Watch"       # switch to a saved list
    tv watchlist copy "Tech Watch v2"    # duplicate the active list
    tv watchlist list                    # all named lists from the picker

Deferred (need follow-up probes):
    * remove <symbol> — per-row delete is hover-reveal-only and TV's
      React handlers don't fire on JS-dispatched mouseenter (same
      pattern blocking the indicators legend in 7c). Requires real
      pointer events + hit-test coordinates. Workaround: `clear` then
      re-add the symbols you want to keep.
    * delete <list> — no obvious "Delete" in the operations menu;
      probably needs a hover-reveal trash inside the picker (similar
      to layouts.delete). Workaround: rename and reuse.
    * reorder — drag-and-drop on canvas-coordinates; complex.
"""

from __future__ import annotations

import argparse

from playwright.async_api import Locator, Page

from .lib import audit, selectors
from .lib.cli import run
from .lib.context import chart_session
from .lib.errors import ModalError
from .lib.guards import with_lock
from .lib.overlays import bypass_overlap_intercept, dismiss_toasts

# TV's menus use the Unicode ellipsis character U+2026 (one glyph), NOT
# three ASCII dots. Match exactly for the menu-item text comparisons.
ELL = "\u2026"


# ---------------------------------------------------------------------------
# Sidebar / panel helpers.
# ---------------------------------------------------------------------------

async def _ensure_sidebar_open(page: Page) -> None:
    """Open the right-sidebar Watchlist widget if it's not already.

    Detection: the watchlists-button (a watchlist-specific header
    control) is visible. The generic `panel_container` is shared by
    alerts/details/news so it can't disambiguate WHICH widget is
    currently expanded.

    The icon click is wrapped in `bypass_overlap_intercept` so a
    right-docked Pine Editor's wrapper inside `overlap-manager-root`
    doesn't intercept the pointer event."""
    if await selectors.any_visible(page, "watchlist", "watchlists_button"):
        return
    await dismiss_toasts(page)
    icon = await selectors.first_visible(
        page, "watchlist", "sidebar_icon", timeout_ms=5000,
    )
    async with bypass_overlap_intercept(page):
        await icon.click()
    await selectors.first_visible(
        page, "watchlist", "watchlists_button", timeout_ms=5000,
    )


async def _open_operations_menu(page: Page) -> None:
    """Click the watchlists-button to open the operations menu (Rename,
    Make a copy, Clear list, Create new list, Open list, etc.). Waits
    for the menuBox popup to appear."""
    await _ensure_sidebar_open(page)
    btn = await selectors.first_visible(
        page, "watchlist", "watchlists_button", timeout_ms=5000,
    )
    await btn.click()
    try:
        await page.wait_for_selector(
            selectors.candidates("watchlist_menu", "container")[0],
            state="visible", timeout=3000,
        )
    except Exception as e:
        raise ModalError(f"Watchlist operations menu didn't appear: {e}")
    await page.wait_for_timeout(200)


async def _click_menu_item(page: Page, label: str) -> None:
    """Click the menu item whose visible text equals `label`. Scoped to
    the most-recently-opened menuBox popup. Uses JS for an exact match
    on the first line of text — the sub-elements duplicate the label
    so a substring/has-text match is ambiguous."""
    clicked = await page.evaluate(
        r"""(wanted) => {
            const popups = Array.from(document.querySelectorAll(
                '[class*="menuBox-"]'
            )).filter(p => {
                const r = p.getBoundingClientRect();
                return r.width > 50 && r.height > 50;
            });
            if (!popups.length) return {clicked: false, reason: 'no_popup'};
            const popup = popups[popups.length - 1];
            // Items use class prefix item-jFqVJoPk (verified 2026-04-17).
            const items = Array.from(popup.querySelectorAll('[class*="item-jFqVJoPk"]'));
            const match = items.find(it => {
                const t = (it.innerText || '').trim();
                const firstLine = t.split('\n')[0].trim();
                // Allow trailing keyboard-shortcut subtext (e.g. "Open list…  ⇧ W").
                return firstLine === wanted || firstLine.startsWith(wanted + ' ');
            });
            if (!match) {
                return {
                    clicked: false, reason: 'item_not_found',
                    available: items.map(i => (i.innerText || '').trim().split('\n')[0]),
                };
            }
            match.click();
            return {clicked: true};
        }""",
        label,
    )
    if not clicked.get("clicked"):
        raise ModalError(
            f"Menu item {label!r} not found: {clicked.get('reason')} "
            f"(available: {clicked.get('available')})"
        )
    await page.wait_for_timeout(400)


async def _dismiss_menu(page: Page) -> None:
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(200)


# ---------------------------------------------------------------------------
# Picker dialog (Open list…) helpers.
# ---------------------------------------------------------------------------

async def _open_picker(page: Page) -> Locator:
    """Open the Open list… picker via the operations menu. Returns the
    dialog locator. Picker has tabs (My watchlists / Hotlists) and a
    search input."""
    await _open_operations_menu(page)
    await _click_menu_item(page, f"Open list{ELL}")
    try:
        dlg = await selectors.first_visible(
            page, "watchlists_dialog", "container", timeout_ms=5000,
        )
        return dlg
    except Exception as e:
        raise ModalError(f"Open list dialog didn't appear: {e}")


async def _picker_rows(page: Page) -> list[dict]:
    """Read the named-list rows from the currently-open picker dialog.

    The "My watchlists" tab shows user-created lists under a CREATED
    LISTS section header. Each row is a clickable element whose inner
    text is the list name (sometimes with a count suffix). We scan every
    visible descendant of the dialog and filter to row-shaped items
    sitting below the CREATED LISTS header."""
    return await page.evaluate(r"""() => {
        const dlg = document.querySelector('[data-dialog-name="Watchlists"]');
        if (!dlg) return [];
        // Find the CREATED LISTS section header to anchor the row scan.
        const headers = Array.from(dlg.querySelectorAll('*'))
            .filter(el => (el.innerText || '').trim() === 'CREATED LISTS');
        if (!headers.length) return [];
        const header = headers[0];
        // Find the closest section container that holds both the header
        // AND the row list — typically the header's parent or grandparent.
        let section = header.parentElement;
        while (section && section.querySelectorAll('*').length < 5) {
            section = section.parentElement;
        }
        if (!section) return [];
        // Each row is a single-line element that is NOT the header itself.
        const candidates = Array.from(section.querySelectorAll('*')).filter(el => {
            const r = el.getBoundingClientRect();
            if (r.width < 100 || r.height < 18 || r.height > 60) return false;
            const t = (el.innerText || '').trim();
            if (!t || t.includes('\n') || t.length > 80) return false;
            if (t === 'CREATED LISTS' || t === 'SYMBOLS') return false;
            // Clickable hint: tag is BUTTON/A/DIV with click handler-ish class.
            return ['BUTTON', 'A', 'DIV'].includes(el.tagName);
        });
        const seen = new Set();
        const out = [];
        for (const el of candidates) {
            const t = (el.innerText || '').trim();
            if (seen.has(t)) continue;
            seen.add(t);
            out.push({
                tag: el.tagName,
                name: t,
                classes: (el.className || '').toString().slice(0, 80),
            });
        }
        return out;
    }""")


async def _click_picker_row(page: Page, name: str) -> dict:
    """Find a named-list row in the open picker and click it."""
    result = await page.evaluate(
        r"""(wanted) => {
            const dlg = document.querySelector('[data-dialog-name="Watchlists"]');
            if (!dlg) return {clicked: false, reason: 'no_dialog'};
            const headers = Array.from(dlg.querySelectorAll('*'))
                .filter(el => (el.innerText || '').trim() === 'CREATED LISTS');
            const root = headers.length ? (() => {
                let s = headers[0].parentElement;
                while (s && s.querySelectorAll('*').length < 5) s = s.parentElement;
                return s;
            })() : dlg;
            if (!root) return {clicked: false, reason: 'no_section'};
            const candidates = Array.from(root.querySelectorAll('*')).filter(el => {
                const r = el.getBoundingClientRect();
                if (r.width < 100 || r.height < 18 || r.height > 60) return false;
                const t = (el.innerText || '').trim();
                return t === wanted;
            });
            if (!candidates.length) return {
                clicked: false, reason: 'name_not_found',
                available: Array.from(root.querySelectorAll('*'))
                    .map(e => (e.innerText || '').trim())
                    .filter(t => t && !t.includes('\n') && t.length < 60)
                    .slice(0, 20),
            };
            // Click the deepest match (most specific).
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
        name,
    )
    if result.get("clicked"):
        await page.wait_for_timeout(800)
    return result


# ---------------------------------------------------------------------------
# Confirm-dialog helper (Clear list, etc.)
# ---------------------------------------------------------------------------

async def _confirm_destructive(page: Page) -> str | None:
    """Click the affirmative button in a destructive-action confirmation
    dialog. Returns the button text clicked, or None if no dialog was
    found. Mirrors the same pattern in alerts.delete and layouts.delete."""
    await page.wait_for_timeout(400)
    confirmed = await page.evaluate(r"""() => {
        const POS = ['Yes, clear all', 'Clear all', 'Delete', 'Yes, delete', 'Yes', 'Confirm', 'OK'];
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
    return confirmed


# ---------------------------------------------------------------------------
# Read paths.
# ---------------------------------------------------------------------------

async def current() -> dict:
    """Read the active watchlist name from the watchlists-button label."""
    async with chart_session() as (_ctx, page):
        await _ensure_sidebar_open(page)
        btn = await selectors.first_visible(
            page, "watchlist", "watchlists_button", timeout_ms=3000,
        )
        text = (await btn.inner_text()).strip()
        # Button may render the count or icon glyphs alongside the name —
        # take the first line as the canonical name.
        name = text.splitlines()[0].strip() if text else None
        audit.log("watchlist.current", name=name)
        return {"ok": True, "name": name}


async def _scrape_visible_symbols(page: Page) -> list[dict]:
    """Read the rows currently rendered inside [data-name="tree"]."""
    return await page.evaluate(r"""() => {
        const tree = document.querySelector('[data-name="tree"]');
        if (!tree) return [];
        const seen = new Map();
        tree.querySelectorAll('[data-symbol-short]').forEach(el => {
            const short = el.getAttribute('data-symbol-short');
            if (!short || seen.has(short)) return;
            const full = el.getAttribute('data-symbol-full') || '';
            const active = el.getAttribute('data-active') === 'true';
            const status = el.getAttribute('data-status') || '';
            seen.set(short, {
                symbol: short, full,
                exchange: full.includes(':') ? full.split(':')[0] : '',
                active, status,
            });
        });
        return Array.from(seen.values());
    }""")


async def _scroll_and_collect(page: Page) -> list[dict]:
    """Scroll the watchlist container top→bottom collecting all symbols.

    The right-sidebar Watchlist is virtualized — only ~10-15 rows are
    in the DOM at any moment. A single static read misses everything
    outside the viewport. We:
      1. Scroll to top, sample.
      2. Scroll down by ~half-viewport, wait for React to render new
         rows, sample, dedup.
      3. Stop when we've reached scrollTop + clientHeight >= scrollHeight
         AND a final post-bottom sample produces no new rows.

    Why scrollTop-based termination instead of "two stagnant rounds":
    React's row virtualizer mounts/unmounts asynchronously after a
    scroll, so a brief idle moment between scrolls can falsely look
    stagnant even when more rows exist. Anchoring on the container's
    own scroll geometry is reliable."""
    # Reset to top.
    await page.evaluate(r"""() => {
        const wrap = document.querySelector('[data-name="symbol-list-wrap"]');
        if (wrap) wrap.scrollTop = 0;
    }""")
    await page.wait_for_timeout(300)

    seen: dict[str, dict] = {}
    last_scroll_top = -1

    for _ in range(60):
        rows = await _scrape_visible_symbols(page)
        for r in rows:
            seen.setdefault(r["symbol"], r)

        geom = await page.evaluate(r"""() => {
            const wrap = document.querySelector('[data-name="symbol-list-wrap"]');
            if (!wrap) return null;
            return {
                scrollTop: wrap.scrollTop,
                clientHeight: wrap.clientHeight,
                scrollHeight: wrap.scrollHeight,
            };
        }""")
        if not geom:
            break
        at_bottom = geom["scrollTop"] + geom["clientHeight"] >= geom["scrollHeight"] - 1
        # Termination: at bottom AND no progress this iteration.
        if at_bottom and geom["scrollTop"] == last_scroll_top:
            break
        last_scroll_top = geom["scrollTop"]
        # Scroll by half a viewport so each row gets sampled in at
        # least two windows (avoids racing virtualizer mount/unmount).
        await page.evaluate(r"""(step) => {
            const wrap = document.querySelector('[data-name="symbol-list-wrap"]');
            if (wrap) wrap.scrollBy(0, step);
        }""", max(120, geom["clientHeight"] // 2))
        # React's virtualizer needs a beat to mount the new range.
        await page.wait_for_timeout(220)
    return list(seen.values())


async def contents() -> dict:
    """List all symbols in the active watchlist.

    The watchlist sidebar is virtualized — we scroll the container and
    dedup by `data-symbol-short` so the result is the COMPLETE list,
    not just the visible viewport. Returns {symbol, exchange, active,
    status} per row; `active=true` marks the symbol currently charted."""
    async with chart_session() as (_ctx, page):
        await _ensure_sidebar_open(page)
        rows = await _scroll_and_collect(page)
        audit.log("watchlist.contents", count=len(rows))
        return {"ok": True, "count": len(rows), "symbols": rows}


async def list_lists() -> dict:
    """List all named watchlists (the My watchlists tab of the picker)."""
    async with chart_session() as (_ctx, page):
        await _open_picker(page)
        # Make sure we're on the My watchlists tab.
        try:
            tab = await selectors.first_visible(
                page, "watchlists_dialog", "my_watchlists_tab", timeout_ms=2000,
            )
            await tab.click()
            await page.wait_for_timeout(400)
        except Exception:
            pass  # Tab may not exist if there's only one mode.
        rows = await _picker_rows(page)
        await _dismiss_menu(page)
        audit.log("watchlist.list", count=len(rows))
        return {"ok": True, "count": len(rows), "lists": rows}


# ---------------------------------------------------------------------------
# Mutating paths.
# ---------------------------------------------------------------------------

async def add_symbol(symbol: str) -> dict:
    """Add `symbol` to the active watchlist. Opens the Add symbol
    dialog, types the ticker, confirms with Enter."""
    if not symbol or not symbol.strip():
        raise ValueError("symbol must be non-empty")
    symbol = symbol.strip().upper()

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("watchlist.add", symbol=symbol) as ac:
                await _ensure_sidebar_open(page)
                existing = await _read_symbols_inline(page)
                if symbol in existing:
                    ac["already_present"] = True
                    return {
                        "ok": True, "symbol": symbol,
                        "already_present": True, "verified": True,
                    }

                btn = await selectors.first_visible(
                    page, "watchlist", "add_symbol_button", timeout_ms=5000,
                )
                await btn.click()
                search = await selectors.first_visible(
                    page, "add_symbol_dialog", "search_input", timeout_ms=5000,
                )
                await search.fill(symbol)
                await page.wait_for_timeout(400)  # Let the symbol-search results render.
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(700)
                # Dialog may stay open expecting more symbols — close.
                if await selectors.any_visible(page, "add_symbol_dialog", "container"):
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)

                # Verify by re-scraping the full list (TV often scrolls to
                # the new symbol but not always — full scan is safer).
                verified = False
                for _ in range(6):
                    post = await _read_symbols_inline(page)
                    if symbol in post:
                        verified = True
                        ac["post_count"] = len(post)
                        break
                    await page.wait_for_timeout(400)
                ac["verified"] = verified
                return {"ok": True, "symbol": symbol, "verified": verified}


async def remove_symbol(symbol: str) -> dict:
    """Remove `symbol` from the active watchlist via the per-row
    hover-reveal X button.

    The X button (`removeButton-<HASH>`) is gated on real CSS `:hover`
    — synthetic mouseenter doesn't trigger it. We:
      1. Open `bypass_overlap_intercept` so a right-docked Pine Editor's
         wrapper doesn't intercept the cursor at the row position.
      2. Scroll the row into view via JS.
      3. Move the real cursor (`page.mouse.move`) over the row's
         center to fire the CSS `:hover` reveal.
      4. Click the now-visible removeButton with the cursor still
         positioned over the row.
    """
    if not symbol or not symbol.strip():
        raise ValueError("symbol must be non-empty")
    symbol = symbol.strip().upper()

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("watchlist.remove", symbol=symbol) as ac:
                await _ensure_sidebar_open(page)
                existing = await _read_symbols_inline(page)
                if symbol not in existing:
                    ac["already_absent"] = True
                    return {
                        "ok": True, "symbol": symbol,
                        "already_absent": True, "verified": True,
                    }

                async with bypass_overlap_intercept(page):
                    # Scroll the row into view so its center is on-screen.
                    rect = await page.evaluate(
                        r"""(sym) => {
                            const row = document.querySelector(
                                `[data-symbol-short="${CSS.escape(sym)}"]`
                            );
                            if (!row) return null;
                            row.scrollIntoView({block: 'center'});
                            const r = row.getBoundingClientRect();
                            return {
                                x: r.x + r.width / 2,
                                y: r.y + r.height / 2,
                            };
                        }""",
                        symbol,
                    )
                    if rect is None:
                        return {
                            "ok": False, "symbol": symbol,
                            "reason": "row_vanished_before_hover",
                        }
                    # Real cursor move triggers TV's CSS :hover reveal.
                    await page.mouse.move(rect["x"], rect["y"])
                    await page.wait_for_timeout(350)
                    # The X button reveals INSIDE the row; address it via
                    # the row + class-prefix selector. Scope to the
                    # specific row to avoid hitting another visible row's
                    # X if multiple are revealed.
                    clicked = await page.evaluate(
                        r"""(sym) => {
                            const row = document.querySelector(
                                `[data-symbol-short="${CSS.escape(sym)}"]`
                            );
                            if (!row) return {clicked: false, reason: 'row_gone'};
                            // The remove button is a sibling/cousin inside
                            // the row's wrap-IEe5qpW4 ancestor — walk up.
                            const wrap = row.closest('[class*="wrap-IEe5qpW4"]') || row.parentElement;
                            const btn = wrap && wrap.querySelector('[class*="removeButton-"]');
                            if (!btn) {
                                return {clicked: false, reason: 'no_remove_button'};
                            }
                            btn.click();
                            return {clicked: true};
                        }""",
                        symbol,
                    )
                    ac["click_result"] = clicked
                    if not clicked.get("clicked"):
                        return {
                            "ok": False, "symbol": symbol,
                            "reason": clicked.get("reason"),
                        }

                # Verify the row disappeared.
                verified = False
                for _ in range(8):
                    await page.wait_for_timeout(250)
                    post = await _read_symbols_inline(page)
                    if symbol not in post:
                        verified = True
                        ac["post_count"] = len(post)
                        break
                ac["verified"] = verified
                return {
                    "ok": True, "symbol": symbol, "verified": verified,
                }


async def _read_symbols_inline(page: Page) -> list[str]:
    """Read the FULL data-symbol-short list (scroll-and-collect).
    Used inside locked sessions to avoid re-entering chart_session()."""
    rows = await _scroll_and_collect(page)
    return [r["symbol"] for r in rows]


async def _read_current_inline(page: Page) -> str | None:
    """Read the active watchlist name without re-entering chart_session()."""
    btn = await selectors.first_visible(
        page, "watchlist", "watchlists_button", timeout_ms=3000,
    )
    text = (await btn.inner_text()).strip()
    return text.splitlines()[0].strip() if text else None


async def clear(*, dry_run: bool = False) -> dict:
    """Clear all symbols from the active watchlist (with confirmation)."""
    async with chart_session() as (_ctx, page):
        await _ensure_sidebar_open(page)
        if dry_run:
            pre_syms = await _read_symbols_inline(page)
            return {
                "ok": True, "dry_run": True,
                "would_clear_count": len(pre_syms),
                "current_symbols": pre_syms,
            }

        async with with_lock("tv_browser"):
            with audit.timed("watchlist.clear") as ac:
                pre_syms = await _read_symbols_inline(page)
                ac["pre_count"] = len(pre_syms)
                await _open_operations_menu(page)
                await _click_menu_item(page, "Clear list")
                confirmed = await _confirm_destructive(page)
                ac["confirmed"] = confirmed
                await page.wait_for_timeout(800)
                post_syms = await _read_symbols_inline(page)
                ac["post_count"] = len(post_syms)
                return {
                    "ok": True, "dry_run": False,
                    "pre_count": len(pre_syms), "post_count": len(post_syms),
                    "verified": len(post_syms) == 0,
                    "confirmed": confirmed,
                }


async def _rename_via_focused_input(page: Page, name: str) -> None:
    """Type `name` into the currently-focused text input and press Enter.
    Used by rename / create / copy — TV opens an inline edit input
    and focuses it after the menu action."""
    await page.wait_for_timeout(400)
    focused = await page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    if focused == "INPUT":
        await page.keyboard.press("ControlOrMeta+a")
        await page.keyboard.type(name)
    else:
        # Fallback: find a visible text input that just appeared.
        inp = page.locator(
            'input[type="text"]:visible, input:not([type]):visible'
        ).first
        await inp.wait_for(state="visible", timeout=3000)
        await inp.fill(name)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(800)


async def rename(new_name: str) -> dict:
    """Rename the active watchlist."""
    if not new_name or not new_name.strip():
        raise ValueError("new_name must be non-empty")
    new_name = new_name.strip()

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("watchlist.rename", new_name=new_name) as ac:
                await _open_operations_menu(page)
                await _click_menu_item(page, "Rename")
                await _rename_via_focused_input(page, new_name)
                verified_name = await _read_current_inline(page)
                ac["verified_name"] = verified_name
                return {
                    "ok": True, "new_name": new_name,
                    "verified_name": verified_name,
                    "verified": verified_name == new_name,
                }


async def create_list(name: str) -> dict:
    """Create a new watchlist named `name`. The new list becomes active."""
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    name = name.strip()

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("watchlist.create", name=name) as ac:
                await _open_operations_menu(page)
                await _click_menu_item(page, f"Create new list{ELL}")
                await _rename_via_focused_input(page, name)
                verified_name = await _read_current_inline(page)
                ac["verified_name"] = verified_name
                return {
                    "ok": True, "name": name,
                    "verified_name": verified_name,
                    "verified": verified_name == name,
                }


async def copy_list(new_name: str) -> dict:
    """Duplicate the active watchlist as a new list named `new_name`."""
    if not new_name or not new_name.strip():
        raise ValueError("new_name must be non-empty")
    new_name = new_name.strip()

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("watchlist.copy", new_name=new_name) as ac:
                await _open_operations_menu(page)
                await _click_menu_item(page, f"Make a copy{ELL}")
                await _rename_via_focused_input(page, new_name)
                verified_name = await _read_current_inline(page)
                ac["verified_name"] = verified_name
                return {
                    "ok": True, "new_name": new_name,
                    "verified_name": verified_name,
                    "verified": verified_name == new_name,
                }


async def load(name: str) -> dict:
    """Switch to the named watchlist. Opens the picker and clicks the row."""
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    name = name.strip()

    async with chart_session() as (_ctx, page):
        async with with_lock("tv_browser"):
            with audit.timed("watchlist.load", name=name) as ac:
                await _open_picker(page)
                # Filter via search to bring the row into view (picker may
                # virtualize when there are many lists).
                try:
                    search = await selectors.first_visible(
                        page, "watchlists_dialog", "search_input", timeout_ms=2000,
                    )
                    await search.fill(name)
                    await page.wait_for_timeout(400)
                except Exception:
                    pass
                result = await _click_picker_row(page, name)
                ac["click_result"] = result
                if not result.get("clicked"):
                    await _dismiss_menu(page)
                    return {
                        "ok": False, "name": name,
                        "reason": result.get("reason"),
                        "available": result.get("available"),
                    }
                await page.wait_for_timeout(800)
                verified_name = await _read_current_inline(page)
                return {
                    "ok": True, "name": name,
                    "verified_name": verified_name,
                    "verified": verified_name == name,
                }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.watchlist")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("current", help="Show the active watchlist name")
    sub.add_parser("contents", help="List symbols in the active watchlist")
    sub.add_parser("list", help="List all named watchlists")

    a = sub.add_parser("add", help="Add a symbol to the active watchlist")
    a.add_argument("symbol")

    rm = sub.add_parser("remove", help="Remove a symbol from the active watchlist")
    rm.add_argument("symbol")

    cl = sub.add_parser("clear", help="Remove all symbols from the active list")
    cl.add_argument("--dry-run", action="store_true")

    cr = sub.add_parser("create", help="Create a new watchlist (becomes active)")
    cr.add_argument("name")

    rn = sub.add_parser("rename", help="Rename the active watchlist")
    rn.add_argument("new_name")

    cp = sub.add_parser("copy", help="Duplicate the active watchlist")
    cp.add_argument("new_name")

    ld = sub.add_parser("load", help="Switch to a named watchlist")
    ld.add_argument("name")

    args = p.parse_args()
    if args.cmd == "current":
        run(lambda: current())
    elif args.cmd == "contents":
        run(lambda: contents())
    elif args.cmd == "list":
        run(lambda: list_lists())
    elif args.cmd == "add":
        run(lambda: add_symbol(args.symbol))
    elif args.cmd == "remove":
        run(lambda: remove_symbol(args.symbol))
    elif args.cmd == "clear":
        run(lambda: clear(dry_run=args.dry_run))
    elif args.cmd == "create":
        run(lambda: create_list(args.name))
    elif args.cmd == "rename":
        run(lambda: rename(args.new_name))
    elif args.cmd == "copy":
        run(lambda: copy_list(args.new_name))
    elif args.cmd == "load":
        run(lambda: load(args.name))


if __name__ == "__main__":
    _main()
