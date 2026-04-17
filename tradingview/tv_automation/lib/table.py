"""Generic table scrapers for TradingView.

TradingView uses two styles of tables we care about:

  1. Plain HTML tables — Strategy Tester's Performance Summary, small
     tabular views. All rows present in DOM; trivial to scrape.

  2. Virtualized tables — Strategy Tester's "List of Trades", Orders
     history, Screener results. Only the visible viewport is rendered
     to DOM. To get all rows, scroll the container and collect rows,
     deduping by a stable row ID.

This module exposes:
  * scrape_plain — every <tr> in a container
  * scrape_virtualized — scroll-and-collect with dedup
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Locator, Page


async def scrape_plain(container: Locator) -> list[dict[str, str]]:
    """Scrape a plain <table> / role=table, return list-of-dicts keyed
    by header text. Headers are the FIRST row's <th> texts; if no <th>,
    the first <tr>'s cells are used as headers."""
    return await container.evaluate("""el => {
        const rows = Array.from(el.querySelectorAll('tr'));
        if (rows.length === 0) return [];
        let headers = Array.from(rows[0].querySelectorAll('th')).map(
            h => (h.innerText || '').trim()
        );
        let dataRows = rows.slice(1);
        if (headers.length === 0) {
            headers = Array.from(rows[0].querySelectorAll('td, [role="cell"]')).map(
                c => (c.innerText || '').trim()
            );
            dataRows = rows.slice(1);
        }
        return dataRows.map(r => {
            const cells = Array.from(r.querySelectorAll('td, [role="cell"]')).map(
                c => (c.innerText || '').trim()
            );
            const out = {};
            headers.forEach((h, i) => { out[h || `col${i}`] = cells[i] ?? ''; });
            return out;
        });
    }""")


async def scrape_virtualized(
    page: Page,
    container: Locator,
    row_selector: str,
    row_key: str = "data-row-id",
    max_scrolls: int = 50,
    scroll_step_px: int = 400,
) -> list[dict[str, Any]]:
    """Scroll a virtualized container and collect all rows.

    We scroll in `scroll_step_px` increments, collecting currently-visible
    rows each step. Rows are keyed by the `row_key` attribute so we only
    capture each once even though it'll appear in multiple frames. Stops
    early when two consecutive scrolls produce no new rows.

    For TradingView specifically, the common patterns are:
      - Strategy Tester List of Trades: row key is a combination of
        trade number and type; scroll the tbody container
      - Screener results: virtualized vertical scroll; row key is the
        symbol
    """
    seen_keys: set[str] = set()
    out: list[dict[str, Any]] = []
    stagnant_rounds = 0

    for _ in range(max_scrolls):
        rows = await container.evaluate(f"""(el, sel) => {{
            return Array.from(el.querySelectorAll(sel)).map(r => {{
                const cells = Array.from(r.querySelectorAll('td, [role="cell"]')).map(
                    c => (c.innerText || '').trim()
                );
                return {{
                    key: r.getAttribute('{row_key}') || r.innerText.slice(0, 80),
                    cells: cells,
                }};
            }});
        }}""", row_selector)

        new_rows = [r for r in rows if r["key"] not in seen_keys]
        for r in new_rows:
            seen_keys.add(r["key"])
            out.append({"key": r["key"], "cells": r["cells"]})

        if not new_rows:
            stagnant_rounds += 1
            if stagnant_rounds >= 2:
                break
        else:
            stagnant_rounds = 0

        # Scroll the container, not the page.
        await container.evaluate(f"el => el.scrollBy(0, {scroll_step_px})")
        await page.wait_for_timeout(150)

    return out
