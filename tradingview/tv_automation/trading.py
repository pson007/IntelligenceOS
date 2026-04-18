"""Trading surface — paper orders via the inline quick-trade bar.

The inline quick-trade bar at the top of the chart has three controls:
    [SELL @ $price]  [qty: N]  [BUY @ $price]
Clicking BUY or SELL fires a MARKET order INSTANTLY for `qty` shares.
Editing qty alone does not trade; only the side click places the order.
So: set qty, verify it committed, then click side. Two atomic steps.

Safety layers (all must pass before any click):
  1. LimitViolationError if symbol not in limits.yaml allowlist
  2. LimitViolationError if qty > limits.max_qty
  3. NotLoggedInError if session cookie missing
  4. NotPaperTradingError if broker picker up OR broker chip isn't Paper
  5. with_lock("tv_browser") — only one browser mutation across processes
     at a time (shared with pine_editor, chart, etc.)

CLI:
    python -m tv_automation.trading place-order NVDA buy 1
    python -m tv_automation.trading place-order AAPL sell 5 --dry-run
    python -m tv_automation.trading positions
    python -m tv_automation.trading close-position NVDA
"""

from __future__ import annotations

import argparse
from typing import Literal

from playwright.async_api import BrowserContext, Page

from preflight import ensure_automation_chromium
from session import tv_context

from . import config
from .lib import audit, selectors
from .lib.cli import run
from .lib.errors import ChartNotReadyError, VerificationFailedError
from .lib.guards import assert_logged_in, assert_paper_trading, with_lock
from .lib.overlays import activate_am_tab, ensure_account_manager_open
from .lib.urls import chart_url_for

CHART_URL = "https://www.tradingview.com/chart/"


# ---------------------------------------------------------------------------
# Chart tab management — trading operates on whatever TV chart tab is open,
# reusing it rather than piling up tabs. set-symbol behavior.
# ---------------------------------------------------------------------------

async def _find_or_open_chart(ctx: BrowserContext) -> Page:
    for p in ctx.pages:
        try:
            if "tradingview.com/chart" in p.url:
                await p.bring_to_front()
                return p
        except Exception:
            continue
    page = await ctx.new_page()
    await page.goto(CHART_URL, wait_until="domcontentloaded")
    return page


async def _navigate_to_symbol(page: Page, symbol: str) -> None:
    """Switch the active chart tab to the target symbol, preserving the
    saved-layout segment of the current URL so drawings / indicators /
    saved configuration survive the navigation."""
    target = chart_url_for(page.url, symbol=symbol)
    await page.goto(target, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("canvas", state="visible", timeout=20_000)
    except Exception as e:
        raise ChartNotReadyError(f"Chart canvas didn't appear for {symbol}: {e}")


# ---------------------------------------------------------------------------
# place_order — extracts the click sequence from the old bridge.
# ---------------------------------------------------------------------------

async def place_order(
    symbol: str,
    side: Literal["buy", "sell"],
    qty: int,
    *,
    dry_run: bool = False,
) -> dict:
    """Place a paper-trading MARKET order via the inline quick-trade bar.

    Returns a result dict with ok/symbol/side/qty/dry_run. Does NOT read
    back from the positions table to verify fill — that's a planned
    follow-up (see `positions()`). For now we verify the qty committed
    to the input and trust TradingView to fire the market click.
    """
    # Step 0 — safety limits before any browser work.
    config.check_symbol(symbol)
    config.check_qty(qty, symbol)
    if not dry_run:
        # Velocity throttle only applies to real trades — dry-runs are
        # free. Prevents runaway retry loops from hammering TradingView.
        config.check_velocity("order")
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")

    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)

        # Paper-trading guard BEFORE any navigation. The broker chip
        # ("Open Account Manager" button) is present on any TV chart
        # page regardless of symbol, so we can check it without first
        # navigating to the target symbol. If a real broker is attached
        # we abort before touching the user's chart state.
        await assert_paper_trading(page)

        await _navigate_to_symbol(page, symbol)

        # The quick-trade bar hydrates after canvas; wait on qtyEl.
        try:
            qty_el = await selectors.first_visible(
                page, "trading_panel", "quick_trade_qty", timeout_ms=15_000,
            )
        except Exception:
            raise ChartNotReadyError(
                f"Quick-trade bar (qtyEl) didn't appear for {symbol}. "
                "Is Paper Trading activated on this profile?"
            )

        # Re-verify paper trading post-navigation — defense in depth.
        # A broker switch mid-flight is extraordinarily unlikely but the
        # check is free, and it catches the case where the page was on
        # a non-chart URL and we just now loaded an active broker chip.
        await assert_paper_trading(page)

        async with with_lock("tv_browser"):
            with audit.timed("trading.place_order",
                             symbol=symbol, side=side, qty=qty,
                             dry_run=dry_run) as audit_ctx:

                # Pre-click snapshot: read the positions table so we can
                # compute a qty delta after the click. `activate_am_tab`
                # opens Account Manager if needed, dismisses any toast,
                # and clicks Positions — idempotent if already active.
                await activate_am_tab(page, "positions_tab")

                before = await _read_position_for_symbol(page, symbol)
                before_qty = await _parse_qty(before["qty"] if before else None)
                audit_ctx["before_qty"] = before_qty

                # Activate the Orders tab so its table is in DOM for the
                # post-click verification poll — Account Manager only
                # renders one tab's table at a time.
                await activate_am_tab(page, "orders_tab")

                # Set qty: click qtyEl → calculator input appears →
                # select-all, type new value, Tab to commit.
                await qty_el.click()
                await selectors.first_visible(
                    page, "trading_panel", "quick_trade_qty_input", timeout_ms=5000,
                )
                await page.keyboard.press("ControlOrMeta+A")
                await page.keyboard.type(str(qty))
                await page.keyboard.press("Tab")
                await page.wait_for_timeout(300)

                # Verify qty committed. The qtyEl span should show our value.
                committed = (await page.locator(
                    f'{selectors.candidates("trading_panel", "quick_trade_qty")[0]} span'
                ).first.inner_text()).strip()
                if committed != str(qty):
                    raise VerificationFailedError(
                        "quick-trade qty commit",
                        expected=str(qty), actual=committed,
                    )
                audit_ctx["verified_qty"] = committed

                if dry_run:
                    audit_ctx["dry_run"] = True
                    return {
                        "ok": True, "dry_run": True,
                        "symbol": symbol, "side": side, "qty": qty,
                        "verified_qty": committed,
                        "before_qty": before_qty,
                    }

                # Fire the market order — single atomic action that trades.
                side_role = "quick_trade_buy" if side == "buy" else "quick_trade_sell"
                side_btn = await selectors.first_visible(
                    page, "trading_panel", side_role, timeout_ms=3000,
                )
                await side_btn.click()

                # Order verification — three possible end-states:
                #   FILLED   — positions table shows expected qty delta
                #   PENDING  — new order row appears in Orders table but
                #              no position yet (after-hours, or market
                #              closed, or broker delays fill)
                #   UNKNOWN  — neither; click may not have registered
                #
                # We poll both tables each tick. Whichever shows the new
                # state first wins.
                expected_delta = qty if side == "buy" else -qty

                # Record the order IDs currently in the Orders table so
                # we can detect "a new pending order for our symbol that
                # wasn't there before." Orders tab is active per above,
                # so the table is populated.
                orders_before = await page.evaluate(
                    "() => { const t = document.querySelector("
                    "'[data-name=\"Paper.orders-table\"]'); "
                    "if (!t) return []; "
                    "return Array.from(t.querySelectorAll('tbody tr'))"
                    ".filter(r => !r.className.includes('emptyStateRow'))"
                    ".map(r => { const c = r.querySelectorAll('td'); "
                    "return c[12] ? (c[12].innerText||'').trim() : ''; }); }"
                )
                orders_before_set = set(orders_before or [])
                audit_ctx["orders_before_count"] = len(orders_before_set)

                observed_delta = 0.0
                after = None
                pending_order = None
                final_status: str = "unknown"
                for _ in range(20):  # 20 × 300ms = ~6s max
                    await page.wait_for_timeout(300)

                    # Check positions (fill path).
                    after = await _read_position_for_symbol(page, symbol)
                    after_qty = await _parse_qty(after["qty"] if after else None)
                    observed_delta = after_qty - before_qty
                    if after is None and before is not None:
                        observed_delta = -before_qty
                    if observed_delta == expected_delta:
                        final_status = "filled"
                        break

                    # Check orders table for a new pending order whose
                    # order_id wasn't there before.
                    pending_order = await _read_pending_order_for_symbol(
                        page, symbol,
                    )
                    if pending_order and pending_order.get("order_id") not in orders_before_set:
                        final_status = "pending_fill"
                        break

                audit_ctx["after_qty"] = (
                    await _parse_qty(after["qty"] if after else None)
                )
                audit_ctx["observed_delta"] = observed_delta
                audit_ctx["expected_delta"] = expected_delta
                audit_ctx["final_status"] = final_status
                verified = final_status in ("filled", "pending_fill")

                if not verified:
                    # Click happened but neither position nor pending
                    # order appeared. Do NOT retry blindly.
                    return {
                        "ok": True, "verified": False, "dry_run": False,
                        "final_status": "unknown",
                        "symbol": symbol, "side": side, "qty": qty,
                        "verified_qty": committed,
                        "before_qty": before_qty,
                        "observed_delta": observed_delta,
                        "expected_delta": expected_delta,
                        "warning": (
                            "Neither positions nor orders table reflected "
                            "the new order within timeout. The click MAY "
                            "have fired — check TV's Orders tab manually "
                            "before retrying. Do NOT retry blindly."
                        ),
                    }

                # Stamp the velocity-limit file on any verified state —
                # filled or pending_fill, both are real orders that need
                # cooldown before the next attempt.
                config.record_action("order")

                return {
                    "ok": True, "verified": True, "dry_run": False,
                    "final_status": final_status,
                    "symbol": symbol, "side": side, "qty": qty,
                    "verified_qty": committed,
                    "before_qty": before_qty,
                    "observed_delta": observed_delta,
                    "expected_delta": expected_delta,
                    "pending_order": pending_order,  # populated when final_status=pending_fill
                }


# ---------------------------------------------------------------------------
# positions / close_position — require the positions table probe to be
# populated into selectors.yaml (trading_panel.positions_*). The current
# selectors are best-effort guesses; if they drift, SelectorDriftError
# fires and you run probes/probe_positions.py to refresh.
# ---------------------------------------------------------------------------

async def _read_pending_order_for_symbol(page: Page, symbol: str) -> dict | None:
    """Read the Orders table for a PENDING order on `symbol`. Returns
    {qty, side, status, order_id} or None. Distinguishes between
    "placed but not yet filled" (e.g. after-hours) and "truly nothing
    happened" — critical for place_order verification."""
    bare = symbol.split(":")[-1].upper()
    return await page.evaluate("""(sym) => {
        const tbl = document.querySelector('[data-name="Paper.orders-table"]');
        if (!tbl) return null;
        const rows = Array.from(tbl.querySelectorAll('tbody tr')).filter(
            r => !r.className.includes('emptyStateRow')
        );
        // Header order from live probe: Symbol, Side, Type, Qty, Limit,
        // Stop, Fill, Take Profit, Stop Loss, Instruction, Status,
        // Placing Time, Order ID, ...
        for (const r of rows) {
            const cells = Array.from(r.querySelectorAll('td'));
            if (!cells.length) continue;
            const token = (cells[0].innerText || '').trim()
                .split(/[:\\s]+/).pop().toUpperCase();
            if (token !== sym) continue;
            return {
                symbol: (cells[0].innerText || '').trim(),
                side: cells[1] ? (cells[1].innerText || '').trim() : '',
                type: cells[2] ? (cells[2].innerText || '').trim() : '',
                qty: cells[3] ? (cells[3].innerText || '').trim() : '',
                status: cells[10] ? (cells[10].innerText || '').trim() : '',
                placing_time: cells[11] ? (cells[11].innerText || '').trim() : '',
                order_id: cells[12] ? (cells[12].innerText || '').trim() : '',
            };
        }
        return null;
    }""", bare)


async def _read_position_for_symbol(page: Page, symbol: str) -> dict | None:
    """Return {qty, side, raw_cells} for the bare ticker, or None if no
    position exists. Silent / read-only — does not expand the Account
    Manager if it's collapsed; returns None if the table isn't in DOM.

    Row match accepts either the full exchange-qualified form
    ("COINBASE:ETHUSD") OR the bare ticker ("ETHUSD"); TV's positions
    table renders the full form but callers pass the bare ticker after
    config.check_symbol strips the prefix. Previously the JS compared
    only the full-form token against bare sym → every prefixed position
    silently returned None, which made place_order verification report
    fills as "unknown" even when they completed correctly."""
    bare = symbol.split(":")[-1].upper()
    return await page.evaluate("""(sym) => {
        const tbl = document.querySelector('[data-name="Paper.positions-table"]');
        if (!tbl) return null;
        const rows = Array.from(tbl.querySelectorAll('tbody tr')).filter(
            r => !r.className.includes('emptyStateRow')
        );
        for (const r of rows) {
            const cells = Array.from(r.querySelectorAll('td'));
            if (!cells.length) continue;
            const token = (cells[0].innerText || '').trim().split(/\\s+/)[0].toUpperCase();
            const tokenBare = token.includes(':') ? token.split(':').pop() : token;
            if (token !== sym && tokenBare !== sym) continue;
            return {
                symbol: (cells[0].innerText || '').trim(),
                side: cells[1] ? (cells[1].innerText || '').trim() : '',
                qty: cells[2] ? (cells[2].innerText || '').trim() : '',
                raw_cells: cells.map(c => (c.innerText || '').trim()),
            };
        }
        return null;
    }""", bare)


async def _parse_qty(qty_str: str | None) -> float:
    """Parse a qty string from the positions table to a number.
    TV may show "1" or "1.5" or "1,234" — normalize commas and sign."""
    if not qty_str:
        return 0.0
    # Take first whitespace token (ignores any trailing text/units).
    token = qty_str.strip().split()[0].replace(",", "")
    try:
        return float(token)
    except ValueError:
        return 0.0


async def _ensure_account_manager_open(page: Page) -> None:
    """Thin wrapper around the shared `ensure_account_manager_open` —
    kept as a module-private name for back-compat with callers. See
    [lib/overlays.py](lib/overlays.py) for the implementation."""
    await ensure_account_manager_open(page)


async def positions() -> list[dict]:
    """Read open positions from the Account Manager's Positions tab.

    Returns a list of dicts keyed by column name (Symbol, Side, Qty,
    Avg Fill Price, Take Profit, Stop Loss, Last Price, Unrealized P&L,
    Unrealized P&L %, Trade Value, Market Value, Leverage, Margin,
    Expiration Date). Empty list if no positions.
    """
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await activate_am_tab(page, "positions_tab")

        data = await page.evaluate("""() => {
            const tbl = document.querySelector('[data-name="Paper.positions-table"]');
            if (!tbl) return { positions: [], empty: true };

            // Column index → name map from <th data-name="$-column">.
            const headers = Array.from(tbl.querySelectorAll('thead th')).map(h => {
                const dn = h.getAttribute('data-name') || '';
                // Strip '-column' suffix and normalize.
                const key = dn.replace(/-column$/, '') ||
                            (h.innerText || '').trim().toLowerCase().replace(/\\s+/g, '_');
                return { key, label: (h.innerText || '').trim() };
            });

            // Empty state?
            const emptyRow = tbl.querySelector('.emptyStateRow-pnigL71h');
            if (emptyRow) return { positions: [], empty: true, headers };

            // Data rows.
            const rows = Array.from(tbl.querySelectorAll('tbody tr')).filter(r =>
                !r.className.includes('emptyStateRow')
            );
            const positions = rows.map(r => {
                const cells = Array.from(r.querySelectorAll('td'));
                const out = { _raw_cells: cells.map(c => (c.innerText || '').trim()) };
                headers.forEach((h, i) => {
                    const cell = cells[i];
                    if (!cell) return;
                    out[h.key] = (cell.innerText || '').trim();
                });
                return out;
            });
            return { positions, empty: positions.length === 0, headers };
        }""")

        audit.log("trading.positions", count=len(data.get("positions", [])))
        return data


async def close_position(symbol: str, *, dry_run: bool = False) -> dict:
    """Close the open position for `symbol` by clicking its row's close
    button. No-op if the symbol isn't currently in the positions table.

    `dry_run=True` walks through row lookup + close-button discovery and
    reports what WOULD happen, without clicking. Useful for an LLM to
    sanity-check before committing.

    The positions table's last column is "settings-column" — it holds a
    per-row button (usually a close/X icon). We search for buttons in
    that cell by aria-label starting with "Close" or data-name
    containing "close". If the probe finds a more specific selector
    later, move it to selectors.yaml → trading_panel.close_position.
    """
    config.check_symbol(symbol)
    if not dry_run:
        config.check_velocity("order")
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await assert_paper_trading(page)
        await activate_am_tab(page, "positions_tab")

        async with with_lock("tv_browser"):
            with audit.timed("trading.close_position",
                             symbol=symbol, dry_run=dry_run) as audit_ctx:
                bare = symbol.split(":")[-1].upper()

                # Discover the row and close button WITHOUT clicking.
                # This lets us support dry-run naturally — the JS runs
                # the same path and reports {found, reason} so we can
                # either return a dry-run preview or proceed to click.
                #
                # Row match accepts EITHER the full exchange-qualified
                # form ("COINBASE:ETHUSD") OR the bare ticker ("ETHUSD")
                # since TV's positions table renders the full form but
                # callers pass the bare ticker after config.check_symbol
                # strips the prefix.
                plan = await page.evaluate("""(sym) => {
                    const tbl = document.querySelector('[data-name="Paper.positions-table"]');
                    if (!tbl) return { found: false, reason: 'no_table' };
                    const rows = Array.from(tbl.querySelectorAll('tbody tr')).filter(
                        r => !r.className.includes('emptyStateRow')
                    );
                    for (const r of rows) {
                        const first = r.querySelector('td');
                        if (!first) continue;
                        const token = (first.innerText || '').trim()
                            .split(/\\s+/)[0].toUpperCase();
                        const tokenBare = token.includes(':')
                            ? token.split(':').pop() : token;
                        if (token !== sym && tokenBare !== sym) continue;
                        const lastCell = r.querySelector('td:last-child');
                        const btn = (lastCell || r).querySelector(
                            'button[aria-label^="Close"], button[data-name*="close"], button[title*="Close"]'
                        );
                        if (!btn) return { found: true, close_btn: false, reason: 'close_button_not_found' };
                        return {
                            found: true, close_btn: true,
                            btn_aria: btn.getAttribute('aria-label'),
                            btn_data_name: btn.getAttribute('data-name'),
                            row_text: (r.innerText || '').trim().slice(0, 120),
                        };
                    }
                    return { found: false, reason: 'symbol_not_in_table' };
                }""", bare)

                audit_ctx["plan"] = plan

                if not plan.get("found") or not plan.get("close_btn"):
                    return {
                        "ok": False,
                        "reason": plan.get("reason", "unknown"),
                        "symbol": symbol,
                        "dry_run": dry_run,
                        "plan": plan,
                    }

                if dry_run:
                    return {
                        "ok": True, "dry_run": True, "would_close": True,
                        "symbol": symbol, "plan": plan,
                    }

                # Commit: click via the same selector path. Matching
                # logic must mirror the plan-discovery above — accept
                # full or bare form of the first-cell token.
                clicked = await page.evaluate("""(sym) => {
                    const tbl = document.querySelector('[data-name="Paper.positions-table"]');
                    if (!tbl) return false;
                    const rows = Array.from(tbl.querySelectorAll('tbody tr')).filter(
                        r => !r.className.includes('emptyStateRow')
                    );
                    for (const r of rows) {
                        const first = r.querySelector('td');
                        if (!first) continue;
                        const token = (first.innerText || '').trim()
                            .split(/\\s+/)[0].toUpperCase();
                        const tokenBare = token.includes(':')
                            ? token.split(':').pop() : token;
                        if (token !== sym && tokenBare !== sym) continue;
                        const lastCell = r.querySelector('td:last-child');
                        const btn = (lastCell || r).querySelector(
                            'button[aria-label^="Close"], button[data-name*="close"], button[title*="Close"]'
                        );
                        if (btn) { btn.click(); return true; }
                    }
                    return false;
                }""", bare)

                if not clicked:
                    return {"ok": False, "reason": "click_failed",
                            "symbol": symbol, "plan": plan}

                await page.wait_for_timeout(500)
                config.record_action("order")
                return {"ok": True, "dry_run": False, "closed": True,
                        "symbol": symbol, "plan": plan}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.trading")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("place-order", help="Place a market order (paper)")
    po.add_argument("symbol")
    po.add_argument("side", choices=["buy", "sell"])
    po.add_argument("qty", type=int)
    po.add_argument("--dry-run", action="store_true",
                    help="Set qty + verify, but DO NOT click buy/sell")

    sub.add_parser("positions", help="List open positions")

    cp = sub.add_parser("close-position", help="Close a position by symbol")
    cp.add_argument("symbol")
    cp.add_argument("--dry-run", action="store_true",
                    help="Report what WOULD be clicked without actually closing")

    args = p.parse_args()

    if args.cmd == "place-order":
        run(lambda: place_order(args.symbol, args.side, args.qty, dry_run=args.dry_run))
    elif args.cmd == "positions":
        run(lambda: positions())
    elif args.cmd == "close-position":
        run(lambda: close_position(args.symbol, dry_run=args.dry_run))


if __name__ == "__main__":
    _main()
