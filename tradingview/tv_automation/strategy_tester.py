"""Strategy Report surface — open, read Metrics, read List of trades.

TradingView internally calls this "Strategy Report" (not "Strategy
Tester" — that's the bottom-panel widget that doesn't actually exist
as a separate thing in current builds). It opens as a full-screen
overlay triggered by the right-toolbar button with
aria-label="Open Strategy Report".

Two tabs inside:
  * Metrics — 10+ <table> elements summarizing the backtest run.
    Each table has header row "Metric / All / Long / Short".
    We concatenate all of them into a single metric → {all, long, short}
    mapping, since the caller usually wants a flat "give me the numbers".
  * List of trades — virtualized table of every entry/exit with P&L.

CLI:
    python -m tv_automation.strategy_tester open
    python -m tv_automation.strategy_tester metrics
    python -m tv_automation.strategy_tester trades
    python -m tv_automation.strategy_tester close
"""

from __future__ import annotations

import argparse
from typing import Any

from playwright.async_api import Page

from preflight import ensure_automation_chromium
from session import tv_context

from .lib import audit, selectors
from .lib.cli import run
from .lib.guards import assert_logged_in

CHART_URL = "https://www.tradingview.com/chart/"


async def _find_chart_page(ctx) -> Page:
    for p in ctx.pages:
        try:
            if "tradingview.com/chart" in p.url:
                await p.bring_to_front()
                return p
        except Exception:
            continue
    page = await ctx.new_page()
    await page.goto(CHART_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    await page.wait_for_timeout(1500)
    return page


async def _is_report_open(page: Page) -> bool:
    """True if the Metrics tab is currently visible — proxy for 'report
    overlay is open and populated'."""
    return await selectors.any_visible(page, "strategy_tester", "metrics_tab")


async def _open_report(page: Page) -> None:
    """Idempotent: open the Strategy Report overlay if it isn't already."""
    if await _is_report_open(page):
        return
    btn = await selectors.first_visible(
        page, "strategy_tester", "open_button", timeout_ms=5000,
    )
    await btn.click()
    # Wait for the Metrics tab (proves the overlay + data populated).
    await selectors.first_visible(
        page, "strategy_tester", "metrics_tab", timeout_ms=8000,
    )
    await page.wait_for_timeout(500)  # let numbers settle


async def _switch_to(page: Page, tab_role: str) -> None:
    """Switch between Metrics / List of trades tabs."""
    tab = await selectors.first_visible(page, "strategy_tester", tab_role, timeout_ms=3000)
    selected = await tab.get_attribute("aria-selected")
    if selected != "true":
        await tab.click()
        await page.wait_for_timeout(400)


async def _close_report(page: Page) -> None:
    """Dismiss the Strategy Report overlay — Escape works reliably."""
    if await _is_report_open(page):
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def open_report() -> dict:
    """Open the Strategy Report overlay."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_chart_page(ctx)
        await assert_logged_in(page)
        await _open_report(page)
        audit.log("strategy_tester.open")
        return {"ok": True}


async def close() -> dict:
    """Close the Strategy Report overlay (back to chart)."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_chart_page(ctx)
        await assert_logged_in(page)
        await _close_report(page)
        audit.log("strategy_tester.close")
        return {"ok": True}


async def metrics() -> dict[str, Any]:
    """Open the Strategy Report, read every Metrics table, return both a
    flat metric → {all, long, short} dict and the raw per-table rows.

    The "flat" view is the convenient access pattern:
        metrics()["flat"]["Net Profit"]["all"]   → "+$1,234.56"
        metrics()["flat"]["Profit Factor"]["all"] → "1.87"

    The raw tables are retained for callers that want column-specific
    structure (some tables have only the "All" column; others split
    long/short).
    """
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_chart_page(ctx)
        await assert_logged_in(page)
        await _open_report(page)
        await _switch_to(page, "metrics_tab")

        data = await page.evaluate("""() => {
            // Find every metrics-shaped table: has Metric + All header cells.
            const all = Array.from(document.querySelectorAll('table')).filter(t => {
                if (!(t.offsetWidth || t.offsetHeight)) return false;
                const heads = Array.from(t.querySelectorAll('thead th, tr:first-child th'))
                    .map(h => (h.innerText || '').trim());
                return heads.includes('Metric') && heads.includes('All');
            });

            const raw_tables = all.map(t => {
                const heads = Array.from(t.querySelectorAll('thead th, tr:first-child th'))
                    .map(h => (h.innerText || '').trim());
                const rows = Array.from(t.querySelectorAll('tbody tr, tr:not(:first-child)'))
                    .map(tr => Array.from(tr.querySelectorAll('th, td'))
                        .map(c => (c.innerText || '').trim()));
                return { headers: heads, rows };
            });

            // Flat metric map: key = metric name (row[0]), values = column map.
            const flat = {};
            raw_tables.forEach(({ headers, rows }) => {
                const colIdx = {
                    all: headers.indexOf('All'),
                    long: headers.indexOf('Long'),
                    short: headers.indexOf('Short'),
                };
                rows.forEach(r => {
                    const name = (r[0] || '').trim();
                    if (!name) return;
                    flat[name] = {
                        all: colIdx.all >= 0 ? (r[colIdx.all] || '') : '',
                        long: colIdx.long >= 0 ? (r[colIdx.long] || '') : '',
                        short: colIdx.short >= 0 ? (r[colIdx.short] || '') : '',
                    };
                });
            });

            return { flat, raw_tables };
        }""")

        audit.log("strategy_tester.metrics",
                  metric_count=len(data.get("flat", {})),
                  table_count=len(data.get("raw_tables", [])))
        return data


async def trades(max_scrolls: int = 200) -> dict:
    """Open the Strategy Report, switch to List of trades, scroll-collect
    every row.

    The trades table is virtualized — only ~10-20 <tr>s sit in DOM at
    any given scroll position. A single static read truncates strategies
    with long histories (the Webhook Alert Template has 488 trades).
    We scroll the `ka-table-wrapper` container in steps and dedup
    rows by their first-cell text (which contains "<trade_num><side>"
    e.g. "1Short" — unique per trade).

    Termination anchors on `scrollTop + clientHeight >= scrollHeight`
    rather than "two stagnant rounds" (the React virtualizer can briefly
    look stagnant after a scroll while it mounts the new range — same
    pattern documented for watchlist.contents)."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_chart_page(ctx)
        await assert_logged_in(page)
        await _open_report(page)
        await _switch_to(page, "list_of_trades_tab")

        # Read headers once (table header is sticky and always rendered).
        headers = await page.evaluate(r"""() => {
            const tbl = Array.from(document.querySelectorAll('table')).find(t => {
                if (!t.offsetWidth) return false;
                const heads = Array.from(t.querySelectorAll('th'))
                    .map(h => (h.innerText || '').trim().toLowerCase());
                return heads.some(h => h.includes('trade')) || heads.some(h => h.includes('signal'));
            });
            if (!tbl) return [];
            return Array.from(tbl.querySelectorAll('thead th, tr:first-child th'))
                .map(h => (h.innerText || '').trim());
        }""")
        if not headers:
            audit.log("strategy_tester.trades", count=0,
                      note="trades_table_not_found")
            return {"headers": [], "rows": []}

        # Reset scroll to top so we capture from row 1.
        await page.evaluate(r"""() => {
            const tbl = Array.from(document.querySelectorAll('table')).find(t => {
                if (!t.offsetWidth) return false;
                const heads = Array.from(t.querySelectorAll('th'))
                    .map(h => (h.innerText || '').trim().toLowerCase());
                return heads.some(h => h.includes('trade')) || heads.some(h => h.includes('signal'));
            });
            if (!tbl) return;
            const wrap = tbl.closest('.ka-table-wrapper');
            if (wrap) wrap.scrollTop = 0;
        }""")
        await page.wait_for_timeout(300)

        seen: dict[str, list[str]] = {}
        last_scroll_top = -1
        for _ in range(max_scrolls):
            scrape = await page.evaluate(r"""() => {
                const tbl = Array.from(document.querySelectorAll('table')).find(t => {
                    if (!t.offsetWidth) return false;
                    const heads = Array.from(t.querySelectorAll('th'))
                        .map(h => (h.innerText || '').trim().toLowerCase());
                    return heads.some(h => h.includes('trade')) || heads.some(h => h.includes('signal'));
                });
                if (!tbl) return null;
                const wrap = tbl.closest('.ka-table-wrapper');
                const rows = Array.from(tbl.querySelectorAll('tbody tr, tr:not(:first-child)'))
                    .map(tr => Array.from(tr.querySelectorAll('th, td'))
                        .map(c => (c.innerText || '').trim()));
                return {
                    rows,
                    scrollTop: wrap ? wrap.scrollTop : 0,
                    clientHeight: wrap ? wrap.clientHeight : 0,
                    scrollHeight: wrap ? wrap.scrollHeight : 0,
                };
            }""")
            if scrape is None:
                break
            for row in scrape["rows"]:
                if not row or not row[0]:
                    continue  # skip empty/aggregate rows
                key = row[0]  # "1Short", "2Long", etc. — unique per trade
                if key not in seen:
                    seen[key] = row

            at_bottom = (
                scrape["scrollTop"] + scrape["clientHeight"]
                >= scrape["scrollHeight"] - 1
            )
            if at_bottom and scrape["scrollTop"] == last_scroll_top:
                break
            last_scroll_top = scrape["scrollTop"]
            # Step ~half a viewport. Each row is ~30px; clientHeight is
            # typically 300-500px, giving 100-150px overlap so each row
            # is sampled in at least two windows (avoids racing the
            # virtualizer's mount/unmount cycle).
            await page.evaluate(r"""(step) => {
                const tbl = Array.from(document.querySelectorAll('table')).find(t => {
                    if (!t.offsetWidth) return false;
                    const heads = Array.from(t.querySelectorAll('th'))
                        .map(h => (h.innerText || '').trim().toLowerCase());
                    return heads.some(h => h.includes('trade')) || heads.some(h => h.includes('signal'));
                });
                if (!tbl) return;
                const wrap = tbl.closest('.ka-table-wrapper');
                if (wrap) wrap.scrollBy(0, step);
            }""", max(150, scrape["clientHeight"] // 2))
            await page.wait_for_timeout(220)

        rows = list(seen.values())
        audit.log("strategy_tester.trades", count=len(rows))
        return {"headers": headers, "rows": rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.strategy_tester")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("open", help="Open the Strategy Report overlay")
    sub.add_parser("close", help="Close the Strategy Report overlay")
    sub.add_parser("metrics", help="Read Metrics tab as JSON (flat + raw)")
    sub.add_parser("trades", help="Scrape List of trades")

    args = p.parse_args()

    if args.cmd == "open":
        run(lambda: open_report())
    elif args.cmd == "close":
        run(lambda: close())
    elif args.cmd == "metrics":
        run(lambda: metrics())
    elif args.cmd == "trades":
        run(lambda: trades())


if __name__ == "__main__":
    _main()
