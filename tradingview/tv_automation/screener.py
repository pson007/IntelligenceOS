"""Screener surface — read filtered tickers from TradingView's screener.

The screener (https://www.tradingview.com/screener/ + crypto/forex/
futures variants) is TV's "stock discovery" surface — apply a filter
set and see which tickers match. This module makes the *read* path
scriptable: navigate to the right screener type, switch column groups,
and scrape the results table (handling virtualization).

The *write* path — programmatically setting individual filter values —
is deferred. Each filter pill (Price, Market Cap, P/E, RSI, ...) is a
different UI control (range slider, dropdown, multi-select, date
picker), so each needs its own setter. The pragmatic workflow today:
configure filters once in the UI manually, save as a named screen,
then call `tv screener results` programmatically.

CLI:
    tv screener open                                # navigate to /screener/ (stocks)
    tv screener current                             # active screen / preset name
    tv screener filters                             # list active filter pills
    tv screener column-tabs                         # list available column tabs
    tv screener results                             # scrape current rows (Overview tab)
    tv screener results --columns Performance       # switch column tab first
    tv screener results --max-rows 500              # cap scroll-collect

Scope: STOCKS ONLY for now. TV's crypto/forex/futures screeners live at
separate URLs (/crypto-screener/, /forex-screener/, /markets/futures/...)
and use a legacy `tv-screener` DOM rather than the modern
`screenerContainer-` React wrapper this module targets. Adding them
would require a parallel implementation; deferred.

Deferred:
    * crypto/forex/futures — different DOM, see scope note above.
    * filter <pill> <value> — set a specific filter programmatically.
      Each pill is a different UI control (range slider, dropdown,
      multi-select, date picker), so each needs its own setter. The
      pragmatic workflow today: configure filters once in the UI
      manually, save as a named screen, then call `results`
      programmatically.
    * preset save / preset load — save/recall named screens (would need
      probing the topbar dropdown menu).
"""

from __future__ import annotations

import argparse
from typing import Any, Literal

from playwright.async_api import BrowserContext, Page

from .lib import audit, selectors
from .lib.cli import run
from .lib.context import browser_context
from .lib.errors import ChartNotReadyError, SelectorDriftError
from .lib.guards import assert_logged_in

# Screener type → URL.
#
# Only `stocks` uses TV's modern unified screener (the React rewrite with
# `screenerContainer-<HASH>` wrapper, filter pills, and column tabs). The
# crypto/forex/futures URLs serve a legacy `tv-screener` DOM that has a
# completely different structure — supporting them needs a separate
# implementation. Deferred until needed.
_SCREENER_URLS: dict[str, str] = {
    "stocks": "https://www.tradingview.com/screener/",
}

ScreenerType = Literal["stocks"]


# ---------------------------------------------------------------------------
# Tab management — find or open a screener tab.
# ---------------------------------------------------------------------------

async def _find_or_open_screener(
    ctx: BrowserContext, screener_type: ScreenerType = "stocks",
) -> Page:
    """Reuse an existing screener tab in `ctx` if one is open at the
    matching URL, otherwise navigate. Different screener types live at
    different URLs; switching type requires a navigation."""
    target_url = _SCREENER_URLS[screener_type]
    # Match the path prefix exactly (after the host) to avoid the
    # "screener" substring matching "crypto-screener" / "forex-screener".
    # Strip a trailing slash from the path so "/screener" matches
    # "/screener/?foo=bar" too.
    from urllib.parse import urlparse
    target_path = urlparse(target_url).path.rstrip("/")

    def _path_matches(url: str) -> bool:
        try:
            up = urlparse(url).path.rstrip("/")
            return up == target_path
        except Exception:
            return False

    # Reuse an existing tab on the exact path.
    for p in ctx.pages:
        try:
            if _path_matches(p.url):
                await p.bring_to_front()
                return p
        except Exception:
            continue

    page = await ctx.new_page()
    await page.goto(target_url, wait_until="domcontentloaded")
    await _wait_screener_ready(page)
    return page


async def _wait_screener_ready(page: Page) -> None:
    """Wait for the screener container to render. Distinct from the
    chart's canvas readiness — screener is a pure DOM table."""
    try:
        await page.wait_for_selector(
            selectors.candidates("screener", "container")[0],
            state="visible", timeout=20_000,
        )
    except Exception as e:
        raise ChartNotReadyError(
            f"Screener container didn't appear within timeout: {e}"
        )
    # Brief beat for the table to populate after the container mounts.
    await page.wait_for_timeout(1500)


# ---------------------------------------------------------------------------
# Read paths.
# ---------------------------------------------------------------------------

async def open_screener(screener_type: ScreenerType = "stocks") -> dict:
    """Navigate to the named screener variant. Returns the active URL +
    current screen title."""
    if screener_type not in _SCREENER_URLS:
        raise ValueError(
            f"unknown screener type {screener_type!r}; "
            f"valid: {sorted(_SCREENER_URLS)}"
        )
    async with browser_context() as ctx:
        page = await _find_or_open_screener(ctx, screener_type)
        await assert_logged_in(page)
        title = await _read_screen_title(page)
        audit.log("screener.open", screener_type=screener_type, title=title)
        return {
            "ok": True, "screener_type": screener_type,
            "url": page.url, "screen_title": title,
        }


async def _read_screen_title(page: Page) -> str | None:
    """Read the topbar title — this is the active screen / preset name
    (e.g. "All stocks" by default, or a user-saved name)."""
    loc = page.locator(
        selectors.candidates("screener", "topbar_title")[0],
    ).first
    if await loc.count() == 0:
        return None
    text = (await loc.inner_text()).strip()
    return text or None


async def current() -> dict:
    """Read the active screener's screen / preset name."""
    async with browser_context() as ctx:
        page = await _find_or_open_screener(ctx)
        await assert_logged_in(page)
        title = await _read_screen_title(page)
        audit.log("screener.current", title=title)
        return {"ok": True, "screen_title": title, "url": page.url}


async def filters() -> dict:
    """List the filter pills currently shown in the screener topbar.

    Each pill has visible text = filter name (Price, Market cap, P/E,
    Sector, ...). When a filter is active, the visible text usually
    includes the active value range or selection (e.g. "Price >50",
    "Sector: Technology"). We return the raw pill text so callers can
    see what's filtered."""
    async with browser_context() as ctx:
        page = await _find_or_open_screener(ctx)
        await assert_logged_in(page)
        pills = await page.evaluate(r"""() => {
            const root = document.querySelector('div[class*="screenerContainer-"]');
            if (!root) return [];
            return Array.from(root.querySelectorAll(
                'button[data-name^="screener-filter-pill-"]'
            )).map(b => ({
                pill_id: b.getAttribute('data-name'),
                text: (b.innerText || '').trim().replace(/\s+/g, ' '),
            }));
        }""")
        audit.log("screener.filters", count=len(pills))
        return {"ok": True, "count": len(pills), "filters": pills}


async def column_tabs() -> dict:
    """List available column-group tabs (Overview / Performance /
    Extended Hours / Valuation / Dividends / Profitability / Income
    Statement / Balance Sheet / Cash Flow / Per Share / Technicals).

    Tabs are split into `visible` (currently clickable in the strip)
    and `hidden` (responsively-overflowed off the right edge — TV
    positions them at translateX(-999877px) and exposes them via a
    "More" overflow button). `_switch_column_tab` handles both paths
    automatically — visible tabs click directly, hidden tabs are
    accessed through the More dropdown. Widening the browser viewport
    moves more tabs into the visible strip."""
    async with browser_context() as ctx:
        page = await _find_or_open_screener(ctx)
        await assert_logged_in(page)
        tabs = await page.evaluate(r"""() => {
            const root = document.querySelector('div[class*="screenerContainer-"]');
            if (!root) return {visible: [], hidden: []};
            const visible = [], hidden = [];
            const seen = new Set();
            root.querySelectorAll('[role="tab"]').forEach(t => {
                const text = (t.innerText || '').trim();
                if (!text || seen.has(text)) return;
                seen.add(text);
                const r = t.getBoundingClientRect();
                const entry = {
                    text,
                    selected: t.getAttribute('aria-selected') === 'true',
                };
                // TV hides off-strip tabs at translateX(-999999px);
                // a negative x coordinate is the tell-tale.
                if (r.x < 0) hidden.push(entry); else visible.push(entry);
            });
            return {visible, hidden};
        }""")
        return {
            "ok": True,
            "visible": tabs["visible"],
            "hidden": tabs["hidden"],
            "note": "Hidden tabs need a wider browser viewport to be clickable.",
        }


async def _switch_column_tab(page: Page, name: str) -> bool:
    """Click the column-tab whose visible text equals `name`. Returns
    True if found and clicked (or already active), False if not found.

    Handles TV's responsive overflow: tabs that don't fit in the visible
    strip are translated to x=-999999 and exposed via a "More" overflow
    button. When the target is hidden, click "More" to open the
    dropdown, then click the target from there."""
    found = await page.evaluate(
        r"""(wanted) => {
            const root = document.querySelector('div[class*="screenerContainer-"]');
            if (!root) return null;
            const tabs = Array.from(root.querySelectorAll('[role="tab"]'));
            const target = tabs.find(t => (t.innerText || '').trim() === wanted);
            if (!target) return null;
            const r = target.getBoundingClientRect();
            return {
                hidden: r.x < 0,
                already_active: target.getAttribute('aria-selected') === 'true',
            };
        }""",
        name,
    )
    if found is None:
        return False
    if found["already_active"]:
        return True

    if found["hidden"]:
        # Open the "More" overflow dropdown, then click the named tab.
        # The More button is a <button>, NOT [role="tab"] (the role-tab
        # elements for the hidden tabs themselves are translated off
        # screen at x=-999999).
        more_btn = page.locator(
            'div[class*="screenerContainer-"] button:has-text("More")'
        ).first
        if await more_btn.count() == 0:
            return False
        try:
            await more_btn.click(timeout=5000)
        except Exception:
            return False
        await page.wait_for_timeout(400)
        # Dropdown items live in a menuBox portal. Match by visible
        # text — items use the same item-jFqVJoPk class prefix from
        # the watchlist menu.
        item = page.locator(
            f'[class*="menuBox-"] [class*="item-jFqVJoPk"]:has-text("{name}"), '
            f'[class*="menuBox-"] [role="menuitem"]:has-text("{name}"), '
            f'[class*="menuBox-"] :text-is("{name}")'
        ).first
        try:
            await item.click(timeout=3000)
        except Exception:
            await page.keyboard.press("Escape")
            return False
        await page.wait_for_timeout(1200)
        return True

    # Visible tab — direct click.
    tab = page.locator(
        f'div[class*="screenerContainer-"] [role="tab"]:text-is("{name}")'
    ).first
    if await tab.count() == 0:
        tab = page.locator(
            'div[class*="screenerContainer-"] [role="tab"]'
        ).filter(has_text=name).first
    try:
        await tab.scroll_into_view_if_needed(timeout=3000)
        await tab.click(timeout=5000)
    except Exception:
        return False
    await page.wait_for_timeout(1200)
    return True


async def _scrape_results(
    page: Page, *, max_rows: int, max_scrolls: int = 80,
) -> tuple[list[str], list[list[str]]]:
    """Scroll-and-collect the screener results table. Returns
    (headers, rows). Rows are deduped by the symbol column (first cell)
    so the same ticker doesn't appear twice across scroll frames."""
    # Read headers once.
    headers: list[str] = await page.evaluate(r"""() => {
        const tbl = document.querySelector(
            'div[class*="screenerContainer-"] table[class*="table-"]'
        );
        if (!tbl) return [];
        return Array.from(tbl.querySelectorAll('thead th'))
            .map(h => (h.innerText || '').trim());
    }""")
    if not headers:
        return [], []

    # Find the scrollable container — TV's screener uses an outer
    # wrapper around the table. Anchor on the screener container.
    await page.evaluate(r"""() => {
        // Reset scroll to top so we capture from row 1.
        const root = document.querySelector('div[class*="screenerContainer-"]');
        if (!root) return;
        // Find the closest scrollable ancestor of the table.
        const tbl = root.querySelector('table[class*="table-"]');
        if (!tbl) return;
        let p = tbl.parentElement;
        while (p && p !== root) {
            const cs = window.getComputedStyle(p);
            if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll')
                && p.scrollHeight > p.clientHeight) {
                p.scrollTop = 0;
                return;
            }
            p = p.parentElement;
        }
        // Fallback: scroll the window.
        window.scrollTo(0, 0);
    }""")
    await page.wait_for_timeout(300)

    seen: dict[str, list[str]] = {}
    last_scroll_top = -1

    for _ in range(max_scrolls):
        scrape = await page.evaluate(r"""() => {
            const root = document.querySelector('div[class*="screenerContainer-"]');
            if (!root) return null;
            const tbl = root.querySelector('table[class*="table-"]');
            if (!tbl) return null;
            const rows = Array.from(tbl.querySelectorAll('tbody tr')).map(tr =>
                Array.from(tr.querySelectorAll('th, td'))
                    .map(c => (c.innerText || '').trim())
            );
            // Find the scrollable container for geometry.
            let wrap = tbl.parentElement;
            while (wrap && wrap !== root) {
                const cs = window.getComputedStyle(wrap);
                if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll')
                    && wrap.scrollHeight > wrap.clientHeight) break;
                wrap = wrap.parentElement;
            }
            const useWindow = !wrap || wrap === root;
            return {
                rows,
                scrollTop: useWindow ? window.scrollY : wrap.scrollTop,
                clientHeight: useWindow ? window.innerHeight : wrap.clientHeight,
                scrollHeight: useWindow ? document.documentElement.scrollHeight : wrap.scrollHeight,
                useWindow,
            };
        }""")
        if scrape is None:
            break
        for row in scrape["rows"]:
            if not row or not row[0]:
                continue
            key = row[0]  # symbol cell
            if key not in seen:
                seen[key] = row
        if len(seen) >= max_rows:
            break

        at_bottom = (
            scrape["scrollTop"] + scrape["clientHeight"]
            >= scrape["scrollHeight"] - 1
        )
        if at_bottom and scrape["scrollTop"] == last_scroll_top:
            break
        last_scroll_top = scrape["scrollTop"]

        await page.evaluate(r"""(step) => {
            const root = document.querySelector('div[class*="screenerContainer-"]');
            if (!root) return;
            const tbl = root.querySelector('table[class*="table-"]');
            if (!tbl) return;
            let wrap = tbl.parentElement;
            while (wrap && wrap !== root) {
                const cs = window.getComputedStyle(wrap);
                if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll')
                    && wrap.scrollHeight > wrap.clientHeight) {
                    wrap.scrollBy(0, step);
                    return;
                }
                wrap = wrap.parentElement;
            }
            window.scrollBy(0, step);
        }""", max(200, scrape["clientHeight"] // 2))
        await page.wait_for_timeout(250)

    return headers, list(seen.values())[:max_rows]


async def results(
    *,
    columns: str | None = None,
    max_rows: int = 1000,
    screener_type: ScreenerType = "stocks",
) -> dict:
    """Scrape the screener's results. Optionally switch column tab
    first ('Overview', 'Performance', 'Technicals', etc.)."""
    async with browser_context() as ctx:
        page = await _find_or_open_screener(ctx, screener_type)
        await assert_logged_in(page)
        if columns:
            switched = await _switch_column_tab(page, columns)
            if not switched:
                tabs_info = await column_tabs()
                return {
                    "ok": False, "reason": "column_tab_not_clickable",
                    "wanted": columns,
                    "visible": [t["text"] for t in tabs_info["visible"]],
                    "hidden": [t["text"] for t in tabs_info["hidden"]],
                    "hint": (
                        "Hidden tabs need a wider browser viewport — "
                        "resize the screener window and retry."
                        if any(t["text"] == columns for t in tabs_info["hidden"])
                        else f"Tab not found; valid: "
                             f"{[t['text'] for t in tabs_info['visible']]}"
                    ),
                }
        title = await _read_screen_title(page)
        headers, rows = await _scrape_results(page, max_rows=max_rows)
        audit.log("screener.results",
                  screener_type=screener_type, columns=columns,
                  count=len(rows))
        return {
            "ok": True, "screener_type": screener_type,
            "screen_title": title, "columns": columns,
            "headers": headers, "row_count": len(rows),
            "rows": rows,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.screener")
    sub = p.add_subparsers(dest="cmd", required=True)

    op = sub.add_parser("open", help="Navigate to a screener variant")
    op.add_argument("type", nargs="?", default="stocks",
                    choices=sorted(_SCREENER_URLS),
                    help="Screener type (default: stocks)")

    sub.add_parser("current", help="Show the active screen / preset name")
    sub.add_parser("filters", help="List active filter pills")
    sub.add_parser("column-tabs", help="List available column tabs")

    res = sub.add_parser("results", help="Scrape screener results")
    res.add_argument("--columns",
                     help="Switch column tab first (Overview, Performance, Technicals, ...)")
    res.add_argument("--max-rows", type=int, default=1000,
                     help="Cap on rows returned (default: 1000)")
    res.add_argument("--type", default="stocks",
                     choices=sorted(_SCREENER_URLS),
                     help="Screener type (default: stocks)")

    args = p.parse_args()
    if args.cmd == "open":
        run(lambda: open_screener(args.type))
    elif args.cmd == "current":
        run(lambda: current())
    elif args.cmd == "filters":
        run(lambda: filters())
    elif args.cmd == "column-tabs":
        run(lambda: column_tabs())
    elif args.cmd == "results":
        run(lambda: results(columns=args.columns, max_rows=args.max_rows,
                            screener_type=args.type))


if __name__ == "__main__":
    _main()
