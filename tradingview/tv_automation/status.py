"""Aggregate read-only status snapshot.

Single CLI that performs many independent reads in ONE browser context,
amortizing the ~2s CDP attach cost across them. A standalone LLM
"orientation" call: before making decisions, grab a full picture of the
TradingView state in one shot.

CLI:
    tv status
    tv status --no-metrics         # skip strategy-report open (slower)
    tv status --no-pine            # skip Pine console read

Output shape (selected fields may be null when unavailable):
{
  "chart": {"symbol", "interval", "url", "title"},
  "broker": {"chip_label", "is_paper"},
  "account_manager": {"open": bool},
  "positions": {"empty": bool, "positions": [...], "headers": [...]},
  "pine_editor": {"open": bool, "errors": [...], "warnings": [...]},
  "strategy_report": {"reachable": bool, "opened": bool, "metrics_flat": {...}},
}

All sub-reads are wrapped in try/except — if one surface is unavailable
(e.g. Pine Editor never opened), that field gets {"error": "..."} but
the rest still populate. An LLM gets partial information rather than
total failure on one missing pane.
"""

from __future__ import annotations

import argparse
from typing import Any

from playwright.async_api import BrowserContext, Page

from . import config, pine_editor, strategy_tester, trading
from .chart import _extract_metadata
from .lib import audit, selectors
from .lib.cli import run
from .lib.context import chart_session


async def _safe(label: str, coro):
    """Run `coro`, return its result, or return {'error': ...} on exception.
    Per-pane isolation — one broken surface doesn't tank the whole report."""
    try:
        return await coro
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "pane": label}


async def _chart_info(page: Page) -> dict[str, Any]:
    return await _extract_metadata(page)


async def _broker_info(page: Page) -> dict[str, Any]:
    """Read the Account Manager toggle — its inner text is the broker name."""
    for sel in selectors.candidates("trading_panel", "broker_chip"):
        loc = page.locator(sel).first
        if await loc.count() == 0:
            continue
        try:
            label = (await loc.inner_text()).strip()
        except Exception:
            continue
        if not label:
            continue
        head = label.splitlines()[0].strip()
        return {
            "chip_label": head,
            "full_label": label,
            "is_paper": config.broker_label_allowed(head),
        }
    return {"chip_label": None, "is_paper": False}


async def _account_manager_info(page: Page) -> dict[str, Any]:
    is_open = await selectors.any_visible(
        page, "trading_panel", "positions_table"
    )
    return {"open": is_open}


async def _positions_info(page: Page) -> dict[str, Any]:
    # Reuse trading.positions but without re-attaching. We call the
    # raw DOM logic against the existing page. The public CLI version
    # opens its own ctx; here we only need the DOM scrape.
    if not await selectors.any_visible(page, "trading_panel", "positions_table"):
        return {"empty": True, "positions": [], "note": "account_manager_closed"}
    # Ensure Positions tab is active.
    tab = await selectors.first_visible(
        page, "trading_panel", "positions_tab", timeout_ms=2000,
    )
    if await tab.get_attribute("aria-selected") != "true":
        await tab.click()
        await page.wait_for_timeout(250)
    return await page.evaluate("""() => {
        const tbl = document.querySelector('[data-name="Paper.positions-table"]');
        if (!tbl) return { empty: true, positions: [] };
        const headers = Array.from(tbl.querySelectorAll('thead th')).map(h => {
            const dn = h.getAttribute('data-name') || '';
            return { key: dn.replace(/-column$/, ''), label: (h.innerText || '').trim() };
        });
        const emptyRow = tbl.querySelector('.emptyStateRow-pnigL71h');
        if (emptyRow) return { empty: true, positions: [], headers };
        const rows = Array.from(tbl.querySelectorAll('tbody tr')).filter(
            r => !r.className.includes('emptyStateRow')
        );
        const positions = rows.map(r => {
            const cells = Array.from(r.querySelectorAll('td'));
            const out = {};
            headers.forEach((h, i) => {
                if (cells[i]) out[h.key] = (cells[i].innerText || '').trim();
            });
            return out;
        });
        return { empty: positions.length === 0, positions, headers };
    }""")


async def _pine_editor_info(page: Page, include_warnings: bool) -> dict[str, Any]:
    """Non-expanding read — only reports Pine state if the editor is
    already open. We don't expand it here because that would be a
    visible mutation for a read-only status call."""
    monaco_sel = selectors.candidates("pine_editor", "monaco")[0]
    is_open = (
        await page.locator(monaco_sel).first.count() > 0
        and await page.locator(monaco_sel).first.is_visible()
    )
    if not is_open:
        return {"open": False}

    errors = await pine_editor._read_compile_errors(page, include_warnings=False)
    warnings = (
        await pine_editor._read_compile_errors(page, include_warnings=True)
        if include_warnings else []
    )
    # _read_compile_errors with include_warnings=True returns errors+warnings
    # combined; subtract the error set to get warnings-only.
    warnings_only = [w for w in warnings if w not in errors] if include_warnings else []

    return {
        "open": True,
        "errors": errors,
        "warnings": warnings_only,
    }


async def _strategy_report_info(
    page: Page, open_if_closed: bool,
) -> dict[str, Any]:
    """If the report is already open, read its metrics. If `open_if_closed`
    is False and the report isn't open, skip — this is the default for
    status, since opening the report is visibly disruptive."""
    is_open = await selectors.any_visible(page, "strategy_tester", "metrics_tab")
    if not is_open:
        if not open_if_closed:
            return {"opened": False, "note": "report_not_open_and_open_if_closed_false"}
        # We're allowed to open it. Use the strategy_tester helpers.
        try:
            await strategy_tester._open_report(page)
        except Exception as e:
            return {"opened": False, "error": f"{type(e).__name__}: {e}"}

    # Switch to metrics tab and scrape.
    try:
        tab = await selectors.first_visible(
            page, "strategy_tester", "metrics_tab", timeout_ms=2000,
        )
        if await tab.get_attribute("aria-selected") != "true":
            await tab.click()
            await page.wait_for_timeout(300)
    except Exception:
        pass

    data = await page.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('table')).filter(t => {
            if (!(t.offsetWidth || t.offsetHeight)) return false;
            const heads = Array.from(t.querySelectorAll('thead th, tr:first-child th'))
                .map(h => (h.innerText || '').trim());
            return heads.includes('Metric') && heads.includes('All');
        });
        const flat = {};
        all.forEach(t => {
            const heads = Array.from(t.querySelectorAll('thead th, tr:first-child th'))
                .map(h => (h.innerText || '').trim());
            const allIdx = heads.indexOf('All');
            Array.from(t.querySelectorAll('tbody tr, tr:not(:first-child)')).forEach(tr => {
                const cells = Array.from(tr.querySelectorAll('th, td'))
                    .map(c => (c.innerText || '').trim());
                if (!cells[0]) return;
                flat[cells[0]] = allIdx >= 0 ? cells[allIdx] : cells[1] || '';
            });
        });
        return { metrics_flat: flat, table_count: all.length };
    }""")
    return {"opened": True, **data}


async def status(
    *,
    include_pine: bool = True,
    include_strategy_report: bool = False,
    include_warnings: bool = False,
) -> dict[str, Any]:
    """Gather a full TV state snapshot in ONE browser context.

    `include_strategy_report` is off by default because opening the
    Strategy Report is visible (it's a full-screen overlay) — passing
    True is opt-in disruption.
    """
    async with chart_session() as (ctx, page):
        with audit.timed("status.snapshot",
                         include_pine=include_pine,
                         include_strategy_report=include_strategy_report) as a:
            out = {"logged_in": True}
            out["chart"] = await _safe("chart", _chart_info(page))
            out["broker"] = await _safe("broker", _broker_info(page))
            out["account_manager"] = await _safe(
                "account_manager", _account_manager_info(page)
            )
            out["positions"] = await _safe("positions", _positions_info(page))
            if include_pine:
                out["pine_editor"] = await _safe(
                    "pine_editor", _pine_editor_info(page, include_warnings)
                )
            if include_strategy_report:
                out["strategy_report"] = await _safe(
                    "strategy_report",
                    _strategy_report_info(page, open_if_closed=True),
                )
            a["pane_count"] = sum(1 for k, v in out.items()
                                  if isinstance(v, dict) and "error" not in v)
            return out


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.status",
        description="Aggregate read-only TradingView state snapshot.")
    p.add_argument("--no-pine", dest="include_pine",
                   action="store_false", default=True,
                   help="Skip the Pine Editor read")
    p.add_argument("--strategy-report", dest="include_strategy_report",
                   action="store_true", default=False,
                   help="Open the Strategy Report overlay and scrape metrics "
                        "(visible — disruptive)")
    p.add_argument("--warnings", dest="include_warnings",
                   action="store_true", default=False,
                   help="Include Pine warning rows in addition to errors")

    args = p.parse_args()
    run(lambda: status(
        include_pine=args.include_pine,
        include_strategy_report=args.include_strategy_report,
        include_warnings=args.include_warnings,
    ))


if __name__ == "__main__":
    _main()
