"""Orders surface — pending-order management via TradingView's order panel.

The Tier 1 `trading.place_order` fires MARKET orders via the inline quick-
trade bar. This module extends the trading lifecycle with limit, stop, and
bracket orders (plus listing and cancellation), all driven through the
persistent right-side "order panel" rather than the quick-trade bar.

Key insight: the order panel (`[data-name="order-panel"]`) is a stateful
form, not a modal. It holds side/type/qty/price/TP/SL across interactions.
So the flow is:

  1. Ensure panel is visible (raise ChartNotReadyError if the user has
     collapsed the right sidebar).
  2. Click the type tab (Market / Limit / Stop).
  3. Set side (Buy / Sell) — these are clickable divs that toggle.
  4. Set quantity, limit/stop price, and TP/SL toggles + prices.
  5. Read the submit button's self-computed preview text — it reads e.g.
     "Buy\\n2 MNQ1! @ 26,776.00 LIMIT". Verify it matches our intent
     before clicking. If mismatch, raise VerificationFailedError — NEVER
     click a button whose preview doesn't match what the caller asked for.
  6. Click submit. Poll the orders table until our new order_id appears.

CLI:
    python -m tv_automation.orders list
    python -m tv_automation.orders place-limit NVDA buy 1 170.50
    python -m tv_automation.orders place-stop NVDA sell 1 165.00 --dry-run
    python -m tv_automation.orders place-bracket NVDA buy 1 \\
        --entry 170.00 --take-profit 175.00 --stop-loss 168.00
    python -m tv_automation.orders cancel <order_id>
    python -m tv_automation.orders cancel-all
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from typing import Literal

from playwright.async_api import BrowserContext, Page

from . import config
from .lib import audit, selectors
from .lib.cli import run
from .lib.context import chart_session
from .lib.errors import ChartNotReadyError, VerificationFailedError
from .lib.guards import assert_paper_trading, with_lock
from .lib.overlays import activate_am_tab
from .lib.urls import chart_url_for

CHART_URL = "https://www.tradingview.com/chart/"
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop"]


# ---------------------------------------------------------------------------
# Helpers — panel visibility, chart navigation, field setters.
# ---------------------------------------------------------------------------

async def _navigate_to_symbol(page: Page, symbol: str) -> None:
    """Switch chart to `symbol` preserving the saved-layout URL segment."""
    target = chart_url_for(page.url, symbol=symbol)
    if page.url != target:
        await page.goto(target, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("canvas", state="visible", timeout=20_000)
        except Exception as e:
            raise ChartNotReadyError(
                f"Chart canvas didn't appear for {symbol}: {e}"
            )
        # Order panel re-hydrates per symbol; give it a moment.
        await page.wait_for_timeout(500)


async def _ensure_panel_visible(page: Page) -> None:
    """Ensure the order panel is visible, auto-opening if needed.

    The panel's visibility is layout-dependent: some saved layouts hide it
    by default, and switching symbols may collapse it. The header
    <button>Trade</button> toggles it cleanly — one click opens when
    hidden. We only click when hidden (so we don't accidentally close it
    if it's already open).
    """
    if await selectors.any_visible(page, "order_panel", "panel"):
        return

    # Panel is hidden — click header Trade button to open. There are
    # multiple "Trade" buttons on the page (header toolbar, bottom bar);
    # both toggle but they're identical in behavior, so take the first
    # visible one.
    trade_btn = page.locator('button:has-text("Trade"):visible').first
    if await trade_btn.count() == 0:
        raise ChartNotReadyError(
            "Order panel is hidden and no 'Trade' toggle button is visible. "
            "Expand the right sidebar in TradingView manually."
        )
    await trade_btn.click()
    # Wait for the panel to materialize AND its form fields to hydrate.
    # We check multiple landmarks — the panel container alone appears
    # before its inner React tree is interactive, so we also wait for
    # the type-tab buttons (Market / Limit / Stop) which hydrate late
    # and are needed immediately by `_click_type_tab`.
    try:
        await page.wait_for_selector(
            selectors.candidates("order_panel", "panel")[0],
            state="visible", timeout=5000,
        )
        await selectors.first_visible(
            page, "order_panel", "quantity_input", timeout_ms=5000,
        )
        # Any type tab — proxy for "Market/Limit/Stop row has hydrated".
        await selectors.first_visible(
            page, "order_panel", "type_tab_market", timeout_ms=5000,
        )
    except Exception as e:
        raise ChartNotReadyError(
            f"Clicked Trade toggle but panel didn't fully hydrate: {e}"
        )


async def _click_type_tab(page: Page, order_type: OrderType) -> None:
    """Switch the order-type tab. Idempotent — clicks even if already on
    the target; TV re-derives the preview text on every click."""
    role = f"type_tab_{order_type}"
    tab = await selectors.first_visible(page, "order_panel", role, timeout_ms=3000)
    await tab.click()
    await page.wait_for_timeout(200)


async def _click_side(page: Page, side: OrderSide) -> None:
    """Set Buy or Sell on the panel's toggle. The div is role=button."""
    role = f"side_{side}"
    btn = await selectors.first_visible(page, "order_panel", role, timeout_ms=3000)
    await btn.click()
    await page.wait_for_timeout(200)


async def _set_input(page: Page, surface: str, role: str, value: str | float | int) -> None:
    """Fill a numeric/text field identified by a selectors-yaml role.
    Uses Playwright's `.fill()` which clears + types atomically. No
    keyboard tab-to-commit needed — the React form commits on blur."""
    loc = await selectors.first_visible(page, surface, role, timeout_ms=3000)
    await loc.fill(str(value))
    # Blur to commit — click elsewhere in the panel.
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(150)


async def _set_toggle(page: Page, surface: str, role: str, desired: bool) -> None:
    """Ensure a <input type=checkbox role=switch> matches `desired`.
    Clicks the input if it mismatches; no-op otherwise."""
    loc = await selectors.first_visible(page, surface, role, timeout_ms=3000)
    checked = await loc.is_checked()
    if bool(checked) != bool(desired):
        await loc.click()
        await page.wait_for_timeout(150)


# Canonical duration codes → TV's display text. Used to map the user's
# lowercase flag ("day") to the exact button label TV renders ("Day").
_DURATION_DISPLAY = {
    "day": "Day",
    "week": "Week",
    "gtc": "GTC",
    "gtd": "GTD",
}

# Safe quantity-type labels — "qty=N" means N of these units. Non-safe
# modes (Risk, Amount) reinterpret the qty field as a dollar value,
# which silently changes what we submit.
_NATIVE_QTY_TYPES = frozenset({"units", "contracts", "shares", "lots"})


async def _assert_qty_type_native(page: Page) -> str:
    """Verify the panel's quantity-type dropdown is in a native-unit
    mode (Units/Contracts/Shares/Lots), NOT Risk or Amount mode.

    Why a read-only check rather than auto-switching: TV renders the
    qty-type dropdown's options in a floating portal that's hard to
    automate reliably (options don't carry role="menuitem" or other
    stable hooks). Asserting is cheap and sufficient — Risk/Amount
    modes require deliberate user action to enter, so silent leakage
    across automation sessions is extremely unlikely once flagged.

    Returns the detected native unit label (for logging/audit).
    """
    btn = await selectors.first_visible(
        page, "order_panel", "quantity_type_dropdown", timeout_ms=3000,
    )
    current = (await btn.inner_text()).strip()
    if current.lower() not in _NATIVE_QTY_TYPES:
        raise VerificationFailedError(
            "quantity type mode",
            expected=f"one of {sorted(_NATIVE_QTY_TYPES)} (native units)",
            actual=(
                f"{current!r} — panel is in Risk/Amount mode, which "
                f"reinterprets qty as dollars. Open the order panel in "
                f"TradingView and manually switch 'Quantity type' back "
                f"to Units/Contracts/Shares before retrying."
            ),
        )
    return current


async def _set_rth_toggles(
    page: Page, *, outside_rth: bool, outside_rth_for_tp: bool,
) -> dict:
    """Set 'Fill order outside RTH' and 'Fill take profit outside RTH'
    checkboxes in the Extra Settings section.

    Only present for equities — futures like MNQ1! don't expose RTH
    toggles because their globex session is continuous, not extended.
    We try-and-tolerate absence: if the toggle isn't in the DOM, we
    skip silently. Returns a dict showing what was set / skipped.
    """
    result = {"outside_rth": None, "outside_rth_for_tp": None}
    for role, target, key in (
        ("fill_outside_rth_toggle", outside_rth, "outside_rth"),
        ("fill_tp_outside_rth_toggle", outside_rth_for_tp, "outside_rth_for_tp"),
    ):
        try:
            loc = await selectors.first_visible(
                page, "order_panel", role, timeout_ms=1500,
            )
        except Exception:
            result[key] = "absent"  # toggle not in panel (e.g. MNQ1!)
            continue
        checked = await loc.is_checked()
        if bool(checked) != bool(target):
            await loc.click()
            await page.wait_for_timeout(150)
        result[key] = "on" if target else "off"
    return result


async def _set_duration(page: Page, duration: str) -> None:
    """Set the Time-in-Force dropdown to the requested value.

    TV's panel persists this field across orders, so without explicit
    control a prior user session's "GTC" selection silently lives on.
    Futures crossing weekends is the motivating risk — a Week-lived MNQ
    order placed Friday fills at whatever Monday's open gap is.

    We call this on every `_place` submission (default: "day"), ensuring
    every programmatic order has a predictable Time-in-Force.
    """
    want_label = _DURATION_DISPLAY.get(duration.lower())
    if want_label is None:
        raise ValueError(
            f"duration must be one of {sorted(_DURATION_DISPLAY.keys())}, "
            f"got {duration!r}"
        )
    btn = await selectors.first_visible(
        page, "order_panel", "duration_dropdown", timeout_ms=3000,
    )
    current = (await btn.inner_text()).strip()
    if current == want_label:
        return
    await btn.click()
    await page.wait_for_timeout(250)
    # TV renders the dropdown options as a floating list; match by exact
    # visible text. Use a strict equality selector rather than `has-text`
    # (substring) to avoid matching e.g. "Week" when "Weekly" is also
    # an option.
    option = page.locator(
        f'[role="option"]:text-is("{want_label}"), '
        f'[role="menuitem"]:text-is("{want_label}")'
    ).first
    try:
        await option.click(timeout=3000)
    except Exception:
        # Fallback: any clickable element with exact text.
        fallback = page.locator(f':visible:text-is("{want_label}")').first
        await fallback.click(timeout=3000)
    await page.wait_for_timeout(200)
    # Verify it stuck.
    committed = (await btn.inner_text()).strip()
    if committed != want_label:
        raise VerificationFailedError(
            "duration dropdown commit",
            expected=want_label, actual=committed,
        )


async def _read_submit_preview(page: Page) -> str:
    """Read the submit button's computed preview text. Returns e.g.
    'Buy\\n2 MNQ1! @ 26,776.00 LIMIT' or 'Start creating order' if the
    form isn't ready. Normalized — single line, whitespace collapsed."""
    btn = await selectors.first_visible(
        page, "order_panel", "submit_button", timeout_ms=3000,
    )
    text = (await btn.inner_text()).strip()
    return " ".join(text.split())


async def _read_panel_ref_price(page: Page, side: OrderSide) -> float:
    """Read the current reference price (ask for buy, bid for sell) from
    the order panel's side-control buttons. Used to resolve TP/SL
    offsets into absolute prices at the latest possible moment before
    submit, minimizing CLI-invocation-to-submit price drift.

    The side-control divs show text like "Buy\\n26,787.50" (ask, for buy
    orders) or "Sell\\n26,775.00" (bid, for sell orders). We parse the
    first numeric we find, tolerating TV's thousands-comma formatting.
    """
    import re
    role = f"side_{side}"  # side_buy / side_sell
    loc = await selectors.first_visible(
        page, "order_panel", role, timeout_ms=3000,
    )
    text = (await loc.inner_text()).strip()
    m = re.search(r"([\d,]+\.?\d*)", text)
    if not m:
        raise VerificationFailedError(
            "order panel reference price",
            expected="numeric bid/ask",
            actual=text[:60],
        )
    return float(m.group(1).replace(",", ""))


def _resolve_offsets(
    *, side: OrderSide, ref_price: float,
    tp_offset: float | None, sl_offset: float | None,
) -> tuple[float | None, float | None]:
    """Convert (tp_offset, sl_offset) in price units → absolute TP/SL
    relative to `ref_price`, with correct sign per side.

    buy: TP above ref, SL below ref.
    sell: TP below ref, SL above ref.
    Offsets must be positive — a negative offset would invert the
    semantics (sell below market as SL is not a stop-loss, it's an
    entry), so reject explicitly rather than silently producing the
    wrong thing.
    """
    if tp_offset is not None and tp_offset <= 0:
        raise ValueError(f"tp_offset must be positive, got {tp_offset}")
    if sl_offset is not None and sl_offset <= 0:
        raise ValueError(f"sl_offset must be positive, got {sl_offset}")
    take_profit: float | None = None
    stop_loss: float | None = None
    if tp_offset is not None:
        take_profit = (
            ref_price + tp_offset if side == "buy" else ref_price - tp_offset
        )
    if sl_offset is not None:
        stop_loss = (
            ref_price - sl_offset if side == "buy" else ref_price + sl_offset
        )
    return take_profit, stop_loss


def _preview_matches(
    preview: str, *, side: OrderSide, qty: int, symbol: str, order_type: OrderType,
    price: float | None = None, price_tolerance: float = 0.02,
) -> tuple[bool, str]:
    """Compare panel-computed preview against caller intent. Returns
    (ok, reason). Tolerant about formatting — commas in price, case of
    side, trailing symbol suffixes, etc. — but strict on the core facts."""
    p = preview.lower()
    if "start creating order" in p:
        return False, "form not ready (preview = 'Start creating order')"
    if side.lower() not in p:
        return False, f"side {side!r} not in preview"
    if str(qty) not in preview:
        return False, f"qty {qty} not in preview"
    bare = symbol.split(":")[-1].lower()
    if bare not in p:
        return False, f"symbol {bare!r} not in preview"
    if order_type != "market" and order_type.upper() not in preview.upper():
        return False, f"type {order_type!r} not in preview"
    if price is not None:
        # Strip commas from preview numerics; parse any decimal number and
        # check if any is within tolerance of our target.
        import re
        nums = [float(n.replace(",", "")) for n in re.findall(r"[\d,]+\.?\d*", preview)]
        if not any(abs(n - price) <= max(price_tolerance, price * 0.0001) for n in nums):
            return False, f"price {price} not in preview (found {nums})"
    return True, "ok"


# ---------------------------------------------------------------------------
# Orders-table reads — shared infra for list/cancel.
# ---------------------------------------------------------------------------

async def _ensure_orders_tab_active(
    page: Page, subtab_role: str = "orders_working_subtab",
) -> None:
    """Open the Account Manager and select Orders → <subtab>.

    Two-level activation:
      1. Main tab: click "Orders" to activate the orders-table surface.
         Delegated to `lib.overlays.activate_am_tab` which also dismisses
         toast overlays (important when an order just fired — TV's
         "executed" toast intercepts pointer events for a few seconds).
      2. Sub-tab: force-click the desired sub-filter. TV has a DOM-cache
         bug where clicking the already-selected sub-tab is a no-op
         (rows stay stale); clicking a *different* sub-tab first and
         then the target forces a re-render. We use "All" as the
         cache-buster (or "Working" when the target already IS "All").

    `subtab_role` is a selectors.yaml role key under `trading_panel.*`:
      - "orders_working_subtab" (default) — pending orders
      - "orders_filled_subtab" — historical fills (used by market-order
        verification, since market entries land in Filled instantly)
      - "orders_rejected_subtab" — TV rejections (used by the verification
        poll to surface explicit error paths)
    """
    await activate_am_tab(page, "orders_tab", timeout_ms=8000)
    await page.wait_for_selector(
        selectors.candidates("trading_panel", "orders_table")[0],
        state="visible", timeout=5000,
    )

    # Force sub-tab refresh via (other) → (target). Sub-tabs are a newer
    # TV feature; if absent (older build), we silently fall through.
    try:
        buster_role = (
            "orders_all_subtab" if subtab_role != "orders_all_subtab"
            else "orders_working_subtab"
        )
        buster = await selectors.first_visible(
            page, "trading_panel", buster_role, timeout_ms=2000,
        )
        target = await selectors.first_visible(
            page, "trading_panel", subtab_role, timeout_ms=2000,
        )
        await buster.click()
        await page.wait_for_timeout(200)
        await target.click()
        await page.wait_for_timeout(300)
    except Exception:
        pass


def _parse_tv_time(s: str | None) -> float | None:
    """Parse TV's order timestamp format 'YYYY-MM-DD HH:MM:SS' (local
    time) to epoch seconds. Returns None for unparsable input."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return None


def _row_bare_symbol(row: dict) -> str:
    """Extract the bare ticker from a row's Symbol column.
    Orders table shows e.g. 'CME_MINI:MNQ1!' or 'NASDAQ:AAPL'; the bare
    ticker is everything after the last colon. Anchored equality
    comparison prevents 'NQ1!' from matching 'MNQ1!' (substring trap)."""
    sym = (row.get("symbol") or "").upper()
    return sym.split(":")[-1].strip()


def _match_new_order(
    rows: list[dict], *,
    symbol: str, side: str, qty: int, row_type_match: str,
    placed_after_epoch: float,
) -> dict | None:
    """Find the row corresponding to a just-submitted order.

    Strict match on side + qty + placing time + type substring + EXACT
    symbol equality (anchored, not substring). `row_type_match` is a
    lowercase substring tested against the row's type column — e.g.
    "market" for market entries, "limit" for limit entries, "take
    profit" / "stop loss" for bracket children.
    """
    want_side = side.lower()
    bare = symbol.split(":")[-1].upper()
    # 60s slack on placing time — TV times use whole seconds and local
    # TZ; small clock offsets + pre-click capture wiggle room.
    cutoff = placed_after_epoch - 60
    for row in rows:
        if _row_bare_symbol(row) != bare:
            continue
        if (row.get("side") or "").lower() != want_side:
            continue
        if (row.get("qty") or "").strip() != str(qty):
            continue
        if row_type_match.lower() not in (row.get("type") or "").lower():
            continue
        ts = _parse_tv_time(row.get("placingTime"))
        if ts is None or ts < cutoff:
            continue
        return row
    return None


async def _read_orders(page: Page) -> list[dict]:
    """Return the Paper.orders-table as a list of dicts keyed by column.
    Empty list if there are no pending orders."""
    data = await page.evaluate(r"""() => {
        const tbl = document.querySelector('[data-name="Paper.orders-table"]');
        if (!tbl) return [];
        const headers = Array.from(tbl.querySelectorAll('thead th')).map(h => {
            const dn = h.getAttribute('data-name') || '';
            const key = dn.replace(/-column$/, '')
                || (h.innerText || '').trim().toLowerCase().replace(/\s+/g, '_');
            return { key, label: (h.innerText || '').trim() };
        });
        const rows = Array.from(tbl.querySelectorAll('tbody tr')).filter(
            r => !r.className.includes('emptyStateRow')
        );
        return rows.map(r => {
            const cells = Array.from(r.querySelectorAll('td'));
            const out = {};
            headers.forEach((h, i) => {
                const c = cells[i];
                if (c) out[h.key] = (c.innerText || '').trim();
            });
            out._raw_cells = cells.map(c => (c.innerText || '').trim());
            return out;
        });
    }""")
    return data or []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def list_orders() -> dict:
    """List all pending orders in the Paper.orders-table."""
    async with chart_session() as (_ctx, page):
        await _ensure_orders_tab_active(page)
        orders = await _read_orders(page)
        audit.log("orders.list", count=len(orders))
        return {"ok": True, "count": len(orders), "orders": orders}


async def _place(
    symbol: str,
    side: OrderSide,
    qty: int,
    order_type: OrderType,
    *,
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit: float | None = None,
    stop_loss: float | None = None,
    tp_offset: float | None = None,
    sl_offset: float | None = None,
    duration: str = "day",
    outside_rth: bool = False,
    outside_rth_for_tp: bool = False,
    dry_run: bool = False,
) -> dict:
    """Generic pending-order placer. Called by the typed entrypoints below.

    TP/SL can be specified either as absolute prices (`take_profit`,
    `stop_loss`) or as offsets from a reference price (`tp_offset`,
    `sl_offset`). The two forms are mutually exclusive per field. For
    limit/stop entries, offsets are relative to the entry price — safe
    and deterministic. For market entries, offsets are resolved against
    the panel's live bid/ask just before the TP/SL fields are filled,
    minimizing the CLI-invocation-to-submit price-drift window.

    `duration` is the Time-in-Force ("day" | "week" | "gtc" | "gtd").
    We set it on every submission because TV's panel persists the field
    across sessions — default Day is the safest choice (no weekend
    gap exposure for MNQ futures).

    `outside_rth` / `outside_rth_for_tp`: control the "Fill order outside
    RTH" and "Fill take profit outside RTH" checkboxes in Extra Settings.
    Default False — safe for equities (no accidental extended-hours
    fills). Silently ignored for futures (MNQ1! hides these toggles
    because globex is a continuous session, not extended-hours).
    """
    # Step 0: safety layers.
    config.check_symbol(symbol)
    config.check_qty(qty, symbol)
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy'|'sell', got {side!r}")
    if order_type not in ("market", "limit", "stop"):
        raise ValueError(f"order_type must be market|limit|stop, got {order_type!r}")
    if order_type == "limit" and limit_price is None:
        raise ValueError("limit_price is required for limit orders")
    if order_type == "stop" and stop_price is None:
        raise ValueError("stop_price is required for stop orders")
    # Offset / absolute mutual exclusivity.
    if take_profit is not None and tp_offset is not None:
        raise ValueError("pass either take_profit OR tp_offset, not both")
    if stop_loss is not None and sl_offset is not None:
        raise ValueError("pass either stop_loss OR sl_offset, not both")
    # Validate duration up front so a typo doesn't waste a trip to the panel.
    if duration.lower() not in _DURATION_DISPLAY:
        raise ValueError(
            f"duration must be one of {sorted(_DURATION_DISPLAY.keys())}, "
            f"got {duration!r}"
        )
    # Tick-alignment check on any user-supplied absolute price. Resolved
    # offsets get a second check post-resolution (see below).
    config.check_tick_alignment(symbol, limit_price, field="limit_price")
    config.check_tick_alignment(symbol, stop_price, field="stop_price")
    config.check_tick_alignment(symbol, take_profit, field="take_profit")
    config.check_tick_alignment(symbol, stop_loss, field="stop_loss")
    if not dry_run:
        config.check_velocity("order")

    async with chart_session() as (_ctx, page):
        await assert_paper_trading(page)
        await _navigate_to_symbol(page, symbol)
        await _ensure_panel_visible(page)
        await assert_paper_trading(page)  # defense-in-depth post-nav

        async with with_lock("tv_browser"):
            with audit.timed(
                f"orders.place_{order_type}",
                symbol=symbol, side=side, qty=qty,
                limit_price=limit_price, stop_price=stop_price,
                take_profit=take_profit, stop_loss=stop_loss,
                dry_run=dry_run,
            ) as audit_ctx:

                # Which sub-tab will the new order appear in?
                #   market → Filled (entry fills instantly; TP/SL exits go
                #            to Working but are secondary).
                #   limit/stop → Working (entry sits pending).
                # Matching sub-tab choice here to `_match_new_order` via
                # row_type_match below.
                if order_type == "market":
                    poll_subtab = "orders_filled_subtab"
                    row_type_match = "market"
                else:
                    poll_subtab = "orders_working_subtab"
                    row_type_match = order_type

                # Baseline snapshot from the relevant sub-tab so we can
                # filter out pre-existing rows (defense against the case
                # where an identical prior order's ID ghost-matches).
                await _ensure_orders_tab_active(page, subtab_role=poll_subtab)
                before = await _read_orders(page)
                before_ids = {o.get("id") for o in before if o.get("id")}
                audit_ctx["orders_before_count"] = len(before_ids)
                audit_ctx["poll_subtab"] = poll_subtab

                # Configure the panel.
                await _click_type_tab(page, order_type)
                await _click_side(page, side)
                await _set_input(page, "order_panel", "quantity_input", qty)

                if order_type == "limit":
                    await _set_input(
                        page, "order_panel", "limit_price_input", limit_price,
                    )
                elif order_type == "stop":
                    await _set_input(
                        page, "order_panel", "stop_price_input", stop_price,
                    )

                # Resolve TP/SL offsets → absolute prices. Reference price:
                #   - limit order: the entry limit_price (known, exact)
                #   - stop order:  the entry stop_price  (known, exact)
                #   - market:      live ask/bid read from the panel NOW
                #                  (closest-to-submit price we can observe;
                #                  tolerates any drift between CLI
                #                  invocation and this point).
                if tp_offset is not None or sl_offset is not None:
                    if order_type == "limit":
                        ref_price = limit_price
                    elif order_type == "stop":
                        ref_price = stop_price
                    else:
                        ref_price = await _read_panel_ref_price(page, side)
                    resolved_tp, resolved_sl = _resolve_offsets(
                        side=side, ref_price=ref_price,
                        tp_offset=tp_offset, sl_offset=sl_offset,
                    )
                    if resolved_tp is not None:
                        take_profit = resolved_tp
                    if resolved_sl is not None:
                        stop_loss = resolved_sl
                    # Re-validate tick alignment on the RESOLVED values —
                    # a fractional offset (e.g. --tp-offset 0.1 against a
                    # 0.25-tick symbol) can produce an off-grid price even
                    # when the ref itself is aligned.
                    config.check_tick_alignment(
                        symbol, take_profit, field="resolved take_profit",
                    )
                    config.check_tick_alignment(
                        symbol, stop_loss, field="resolved stop_loss",
                    )
                    audit_ctx["offset_ref_price"] = ref_price
                    audit_ctx["resolved_take_profit"] = take_profit
                    audit_ctx["resolved_stop_loss"] = stop_loss

                # TP/SL — explicitly set toggle state + price. If either is
                # None, force toggle off (defense against panel sticky state
                # leaving a TP/SL from a prior order).
                await _set_toggle(
                    page, "order_panel", "take_profit_toggle",
                    take_profit is not None,
                )
                if take_profit is not None:
                    await _set_input(
                        page, "order_panel", "take_profit_price", take_profit,
                    )
                await _set_toggle(
                    page, "order_panel", "stop_loss_toggle",
                    stop_loss is not None,
                )
                if stop_loss is not None:
                    await _set_input(
                        page, "order_panel", "stop_loss_price", stop_loss,
                    )

                # Set Time-in-Force — always for limit/stop (where TIF
                # matters), skip for market (fills instantly, no
                # persistence; TV hides the duration dropdown entirely
                # on the Market tab).
                if order_type != "market":
                    await _set_duration(page, duration)
                    audit_ctx["duration"] = duration

                # RTH toggles (equities only — silently no-op on futures).
                rth_result = await _set_rth_toggles(
                    page,
                    outside_rth=outside_rth,
                    outside_rth_for_tp=outside_rth_for_tp,
                )
                audit_ctx["rth"] = rth_result

                # Assert quantity-type is in a native-unit mode before
                # reading the submit preview — non-native modes silently
                # reinterpret qty. Cheap check, catches the worst silent
                # bug in the system.
                qty_type = await _assert_qty_type_native(page)
                audit_ctx["quantity_type"] = qty_type

                # Read panel-computed preview and verify it matches intent.
                preview = await _read_submit_preview(page)
                audit_ctx["preview"] = preview

                expected_price = limit_price if order_type == "limit" else stop_price
                ok, reason = _preview_matches(
                    preview,
                    side=side, qty=qty, symbol=symbol,
                    order_type=order_type, price=expected_price,
                )
                if not ok:
                    raise VerificationFailedError(
                        "order panel preview",
                        expected=(
                            f"{side} {qty} {symbol} @ {expected_price} "
                            f"{order_type.upper()}"
                        ),
                        actual=f"{preview!r} ({reason})",
                    )

                if dry_run:
                    audit_ctx["dry_run"] = True
                    return {
                        "ok": True, "dry_run": True,
                        "symbol": symbol, "side": side, "qty": qty,
                        "type": order_type,
                        "limit_price": limit_price, "stop_price": stop_price,
                        "take_profit": take_profit, "stop_loss": stop_loss,
                        "preview": preview,
                    }

                # Submit. Capture wall-clock as the "placed_after" floor
                # used by `_match_new_order` to filter out stale rows.
                # Small backward slack (-2s) tolerates TV's whole-second
                # timestamp granularity and our own clock skew.
                placed_after_epoch = time.time() - 2
                submit = await selectors.first_visible(
                    page, "order_panel", "submit_button", timeout_ms=3000,
                )
                await submit.click()

                # Poll for the new row. Match criteria:
                #   - symbol bare ticker contained in row symbol
                #   - side matches (Buy / Sell)
                #   - qty matches
                #   - type column contains `row_type_match` (market/limit/stop)
                #   - placingTime ≥ placed_after_epoch
                #   - id NOT in before_ids (belt-and-suspenders against
                #     same-second timestamp collisions)
                #
                # Re-activate the sub-tab each iteration — TV may
                # auto-switch tabs after placement, and the cache-bust
                # sequence ensures fresh DOM.
                #
                # Early-rejection peek: every 5 iters (at i=5, 10, 15),
                # flip to Rejected and check there too. TV rejects are
                # usually immediate; catching them mid-poll cuts the
                # "waited 19s to learn it was rejected" UX.
                #
                # Budget: 20 iters × (~600ms ensure + 300ms wait + 50ms
                # read) ≈ 19s, plus 3 rejection peeks × ~600ms = ~21s.
                # Market orders usually resolve in <3s, so the typical
                # run is 3-5 iters.
                new_order: dict | None = None
                rejected_order: dict | None = None
                for i in range(20):
                    # Periodic early-rejection peek (skip iter 0 — too
                    # early; TV's backend hasn't processed the submit).
                    if i > 0 and i % 5 == 0:
                        await _ensure_orders_tab_active(
                            page, subtab_role="orders_rejected_subtab",
                        )
                        rej_rows = await _read_orders(page)
                        rejected_order = _match_new_order(
                            rej_rows,
                            symbol=symbol, side=side, qty=qty,
                            row_type_match=row_type_match,
                            placed_after_epoch=placed_after_epoch,
                        )
                        if rejected_order:
                            break

                    await _ensure_orders_tab_active(
                        page, subtab_role=poll_subtab,
                    )
                    await page.wait_for_timeout(300)
                    current = await _read_orders(page)
                    match = _match_new_order(
                        current,
                        symbol=symbol, side=side, qty=qty,
                        row_type_match=row_type_match,
                        placed_after_epoch=placed_after_epoch,
                    )
                    if match and match.get("id") not in before_ids:
                        new_order = match
                        break

                audit_ctx["new_order_id"] = (
                    new_order.get("id") if new_order else None
                )
                audit_ctx["verified"] = bool(new_order)

                # If the mid-loop peek already caught a rejection, skip
                # the catch-all final check.
                if rejected_order is None and not new_order:
                    # Catch-all: late rejection between the last peek and now.
                    await _ensure_orders_tab_active(
                        page, subtab_role="orders_rejected_subtab",
                    )
                    rej_rows = await _read_orders(page)
                    rejected_order = _match_new_order(
                        rej_rows,
                        symbol=symbol, side=side, qty=qty,
                        row_type_match=row_type_match,
                        placed_after_epoch=placed_after_epoch,
                    )

                if rejected_order:
                    audit_ctx["rejected"] = True
                    audit_ctx["rejection_row"] = rejected_order
                    return {
                        "ok": False, "rejected": True, "dry_run": False,
                        "symbol": symbol, "side": side, "qty": qty,
                        "type": order_type,
                        "limit_price": limit_price, "stop_price": stop_price,
                        "take_profit": take_profit, "stop_loss": stop_loss,
                        "preview": preview,
                        "rejection_row": rejected_order,
                        "message": (
                            "TV rejected the order — see rejection_row "
                            "for details. Common causes: price off-tick, "
                            "buying power, halted symbol, outside RTH "
                            "without override."
                        ),
                    }

                if not new_order:

                    warn = (
                        "Submit clicked but no matching row appeared in "
                        f"{poll_subtab!r} within ~19s, and no rejection "
                        "was detected. "
                    )
                    if order_type == "market":
                        warn += (
                            "For a market order, this often means the "
                            "entry filled AND a TP/SL child already "
                            "resolved (both moved to Filled/Cancelled "
                            "faster than our poll caught). Run `tv orders "
                            "list` and `tv trading positions` to confirm "
                            "actual state before retrying."
                        )
                    else:
                        warn += (
                            "The submission may have failed silently, or "
                            "the sub-tab cache bug masked the new row. "
                            "Do NOT retry blindly — check `tv orders list` "
                            "first."
                        )
                    return {
                        "ok": True, "verified": False, "dry_run": False,
                        "symbol": symbol, "side": side, "qty": qty,
                        "type": order_type,
                        "limit_price": limit_price, "stop_price": stop_price,
                        "take_profit": take_profit, "stop_loss": stop_loss,
                        "preview": preview,
                        "warning": warn,
                    }

                config.record_action("order")
                return {
                    "ok": True, "verified": True, "dry_run": False,
                    "symbol": symbol, "side": side, "qty": qty,
                    "type": order_type,
                    "limit_price": limit_price, "stop_price": stop_price,
                    "take_profit": take_profit, "stop_loss": stop_loss,
                    "preview": preview,
                    "order_id": new_order.get("id"),
                    "order": new_order,
                }


async def place_market(
    symbol: str, side: OrderSide, qty: int,
    *,
    take_profit: float | None = None, stop_loss: float | None = None,
    tp_offset: float | None = None, sl_offset: float | None = None,
    duration: str = "day",
    outside_rth: bool = False, outside_rth_for_tp: bool = False,
    dry_run: bool = False,
) -> dict:
    """Place a market order via the order-panel Market tab.

    Unlike `trading.place_order` (which fires through the inline
    quick-trade bar and has NO TP/SL support), this route opens the
    order panel, selects Market, sets qty + optional TP/SL, and clicks
    submit. The entry typically fills instantly.

    TP/SL can be absolute (`take_profit`, `stop_loss`) or offset-based
    (`tp_offset`, `sl_offset`). For market orders, offsets are
    resolved against the panel's live ask (buy) / bid (sell) at submit
    time — reducing the asymmetric-slippage problem that absolute
    prices suffer when market moves between CLI invocation and submit.
    """
    return await _place(
        symbol, side, qty, "market",
        take_profit=take_profit, stop_loss=stop_loss,
        tp_offset=tp_offset, sl_offset=sl_offset,
        duration=duration,
        outside_rth=outside_rth, outside_rth_for_tp=outside_rth_for_tp,
        dry_run=dry_run,
    )


async def place_limit(
    symbol: str, side: OrderSide, qty: int, limit_price: float,
    *,
    take_profit: float | None = None, stop_loss: float | None = None,
    tp_offset: float | None = None, sl_offset: float | None = None,
    duration: str = "day",
    outside_rth: bool = False, outside_rth_for_tp: bool = False,
    dry_run: bool = False,
) -> dict:
    return await _place(
        symbol, side, qty, "limit",
        limit_price=limit_price,
        take_profit=take_profit, stop_loss=stop_loss,
        tp_offset=tp_offset, sl_offset=sl_offset,
        duration=duration,
        outside_rth=outside_rth, outside_rth_for_tp=outside_rth_for_tp,
        dry_run=dry_run,
    )


async def place_stop(
    symbol: str, side: OrderSide, qty: int, stop_price: float,
    *,
    take_profit: float | None = None, stop_loss: float | None = None,
    tp_offset: float | None = None, sl_offset: float | None = None,
    duration: str = "day",
    outside_rth: bool = False, outside_rth_for_tp: bool = False,
    dry_run: bool = False,
) -> dict:
    return await _place(
        symbol, side, qty, "stop",
        stop_price=stop_price,
        take_profit=take_profit, stop_loss=stop_loss,
        tp_offset=tp_offset, sl_offset=sl_offset,
        duration=duration,
        outside_rth=outside_rth, outside_rth_for_tp=outside_rth_for_tp,
        dry_run=dry_run,
    )


async def place_bracket(
    symbol: str, side: OrderSide, qty: int,
    *,
    entry: float,
    take_profit: float | None = None, stop_loss: float | None = None,
    tp_offset: float | None = None, sl_offset: float | None = None,
    order_type: OrderType = "limit",
    duration: str = "day",
    outside_rth: bool = False, outside_rth_for_tp: bool = False,
    dry_run: bool = False,
) -> dict:
    """Place a limit (or stop) entry with attached TP + SL exits.
    TradingView treats these as a single atomic submit — the child
    TP/SL exits automatically activate when the entry fills.

    TP/SL accepts absolute prices or offsets (see `place_market`).
    For bracket entries, offsets are relative to the entry price —
    exact and deterministic (no panel-read needed)."""
    if (take_profit is None and tp_offset is None) or \
       (stop_loss is None and sl_offset is None):
        raise ValueError(
            "place_bracket requires both TP and SL (either absolute "
            "or offset form for each)"
        )
    kwargs = {
        "take_profit": take_profit, "stop_loss": stop_loss,
        "tp_offset": tp_offset, "sl_offset": sl_offset,
        "duration": duration,
        "outside_rth": outside_rth, "outside_rth_for_tp": outside_rth_for_tp,
        "dry_run": dry_run,
    }
    if order_type == "limit":
        return await _place(symbol, side, qty, "limit", limit_price=entry, **kwargs)
    elif order_type == "stop":
        return await _place(symbol, side, qty, "stop", stop_price=entry, **kwargs)
    else:
        raise ValueError(
            f"bracket entry must be limit|stop, not {order_type!r}"
        )


async def cancel_order(order_id: str, *, dry_run: bool = False) -> dict:
    """Cancel a pending order by its TradingView order ID. Finds the row
    whose id-column matches and clicks its close-settings-cell-button."""
    if not order_id or not order_id.strip():
        raise ValueError("order_id must not be empty")

    async with chart_session() as (_ctx, page):
        await assert_paper_trading(page)
        await _ensure_orders_tab_active(page)

        async with with_lock("tv_browser"):
            with audit.timed(
                "orders.cancel", order_id=order_id, dry_run=dry_run,
            ) as audit_ctx:
                plan = await page.evaluate(r"""(oid) => {
                    const tbl = document.querySelector(
                        '[data-name="Paper.orders-table"]'
                    );
                    if (!tbl) return { found: false, reason: 'no_table' };
                    const headers = Array.from(tbl.querySelectorAll('thead th'))
                        .map(h => (h.getAttribute('data-name') || '').replace(/-column$/, ''));
                    const idCol = headers.indexOf('id');
                    const rows = Array.from(tbl.querySelectorAll('tbody tr'))
                        .filter(r => !r.className.includes('emptyStateRow'));
                    for (const r of rows) {
                        const cells = Array.from(r.querySelectorAll('td'));
                        const cellId = idCol >= 0 && cells[idCol]
                            ? (cells[idCol].innerText || '').trim()
                            : '';
                        if (cellId !== oid) continue;
                        const btn = r.querySelector(
                            '[data-name="close-settings-cell-button"]'
                        );
                        return {
                            found: true,
                            row_text: (r.innerText || '').trim().slice(0, 200),
                            has_cancel_btn: !!btn,
                            btn_aria: btn ? btn.getAttribute('aria-label') : null,
                            symbol: cells[0] ? (cells[0].innerText || '').trim() : '',
                        };
                    }
                    return { found: false, reason: 'order_id_not_in_table' };
                }""", order_id)

                audit_ctx["plan"] = plan
                if not plan.get("found"):
                    return {
                        "ok": False, "order_id": order_id,
                        "reason": plan.get("reason", "unknown"),
                        "plan": plan,
                    }
                if not plan.get("has_cancel_btn"):
                    return {
                        "ok": False, "order_id": order_id,
                        "reason": "cancel_button_not_in_row",
                        "plan": plan,
                    }

                if dry_run:
                    return {
                        "ok": True, "dry_run": True,
                        "would_cancel": True, "order_id": order_id,
                        "plan": plan,
                    }

                clicked = await page.evaluate(r"""(oid) => {
                    const tbl = document.querySelector(
                        '[data-name="Paper.orders-table"]'
                    );
                    if (!tbl) return false;
                    const headers = Array.from(tbl.querySelectorAll('thead th'))
                        .map(h => (h.getAttribute('data-name') || '').replace(/-column$/, ''));
                    const idCol = headers.indexOf('id');
                    const rows = Array.from(tbl.querySelectorAll('tbody tr'))
                        .filter(r => !r.className.includes('emptyStateRow'));
                    for (const r of rows) {
                        const cells = Array.from(r.querySelectorAll('td'));
                        const cellId = idCol >= 0 && cells[idCol]
                            ? (cells[idCol].innerText || '').trim()
                            : '';
                        if (cellId !== oid) continue;
                        const btn = r.querySelector(
                            '[data-name="close-settings-cell-button"]'
                        );
                        if (btn) { btn.click(); return true; }
                    }
                    return false;
                }""", order_id)

                if not clicked:
                    return {
                        "ok": False, "order_id": order_id,
                        "reason": "click_dispatch_failed", "plan": plan,
                    }

                # Verify: poll until the row is gone. Match the place()
                # timeout budget — TV's async round-trip here is similar.
                gone = False
                for _ in range(30):
                    await page.wait_for_timeout(400)
                    current = await _read_orders(page)
                    if not any(o.get("id") == order_id for o in current):
                        gone = True
                        break

                audit_ctx["verified"] = gone
                return {
                    "ok": True, "dry_run": False, "cancelled": True,
                    "verified": gone, "order_id": order_id, "plan": plan,
                    "warning": (
                        None if gone
                        else "Row still present after 12s — may be "
                             "transitioning to history. Check list-orders."
                    ),
                }


async def cancel_all(*, dry_run: bool = False) -> dict:
    """Cancel every pending order. Convenience; loops cancel_order per id."""
    async with chart_session() as (_ctx, page):
        await _ensure_orders_tab_active(page)
        orders = await _read_orders(page)
        ids = [o.get("id") for o in orders if o.get("id")]
    if not ids:
        return {"ok": True, "count": 0, "cancelled": []}

    results = []
    for oid in ids:
        r = await cancel_order(oid, dry_run=dry_run)
        results.append(r)
    return {
        "ok": all(r.get("ok") for r in results),
        "count": len(results),
        "cancelled": results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.orders")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List pending orders")

    def _add_tp_sl_flags(parser):
        """TP/SL can be absolute price OR offset from reference (entry
        for limit/stop; live panel ask/bid for market). Mutually
        exclusive per field."""
        parser.add_argument("--take-profit", type=float, default=None,
                            help="TP absolute price")
        parser.add_argument("--stop-loss", type=float, default=None,
                            help="SL absolute price")
        parser.add_argument("--tp-offset", type=float, default=None,
                            help="TP as positive price-unit offset from ref")
        parser.add_argument("--sl-offset", type=float, default=None,
                            help="SL as positive price-unit offset from ref")
        parser.add_argument("--duration", choices=["day", "week", "gtc", "gtd"],
                            default="day",
                            help="Time-in-Force (default: day)")
        parser.add_argument("--outside-rth", action="store_true",
                            help="Allow entry fill outside regular trading hours "
                                 "(equities only; silently no-op for futures)")
        parser.add_argument("--outside-rth-tp", action="store_true",
                            dest="outside_rth_for_tp",
                            help="Allow TP fill outside regular trading hours")

    pm = sub.add_parser("place-market",
                        help="Place a market order (optional TP/SL) via order panel")
    pm.add_argument("symbol")
    pm.add_argument("side", choices=["buy", "sell"])
    pm.add_argument("qty", type=int)
    _add_tp_sl_flags(pm)
    pm.add_argument("--dry-run", action="store_true")

    pl = sub.add_parser("place-limit", help="Place a limit order")
    pl.add_argument("symbol")
    pl.add_argument("side", choices=["buy", "sell"])
    pl.add_argument("qty", type=int)
    pl.add_argument("limit_price", type=float)
    _add_tp_sl_flags(pl)
    pl.add_argument("--dry-run", action="store_true")

    ps = sub.add_parser("place-stop", help="Place a stop-market order")
    ps.add_argument("symbol")
    ps.add_argument("side", choices=["buy", "sell"])
    ps.add_argument("qty", type=int)
    ps.add_argument("stop_price", type=float)
    _add_tp_sl_flags(ps)
    ps.add_argument("--dry-run", action="store_true")

    pb = sub.add_parser("place-bracket",
                        help="Place an entry + TP + SL as a bracket")
    pb.add_argument("symbol")
    pb.add_argument("side", choices=["buy", "sell"])
    pb.add_argument("qty", type=int)
    pb.add_argument("--entry", type=float, required=True)
    _add_tp_sl_flags(pb)
    pb.add_argument("--type", dest="order_type",
                    choices=["limit", "stop"], default="limit")
    pb.add_argument("--dry-run", action="store_true")

    cx = sub.add_parser("cancel", help="Cancel a pending order by id")
    cx.add_argument("order_id")
    cx.add_argument("--dry-run", action="store_true")

    ca = sub.add_parser("cancel-all", help="Cancel every pending order")
    ca.add_argument("--dry-run", action="store_true")

    args = p.parse_args()

    if args.cmd == "list":
        run(lambda: list_orders())
    elif args.cmd == "place-market":
        run(lambda: place_market(
            args.symbol, args.side, args.qty,
            take_profit=args.take_profit, stop_loss=args.stop_loss,
            tp_offset=args.tp_offset, sl_offset=args.sl_offset,
            duration=args.duration,
            outside_rth=args.outside_rth,
            outside_rth_for_tp=args.outside_rth_for_tp,
            dry_run=args.dry_run,
        ))
    elif args.cmd == "place-limit":
        run(lambda: place_limit(
            args.symbol, args.side, args.qty, args.limit_price,
            take_profit=args.take_profit, stop_loss=args.stop_loss,
            tp_offset=args.tp_offset, sl_offset=args.sl_offset,
            duration=args.duration,
            outside_rth=args.outside_rth,
            outside_rth_for_tp=args.outside_rth_for_tp,
            dry_run=args.dry_run,
        ))
    elif args.cmd == "place-stop":
        run(lambda: place_stop(
            args.symbol, args.side, args.qty, args.stop_price,
            take_profit=args.take_profit, stop_loss=args.stop_loss,
            tp_offset=args.tp_offset, sl_offset=args.sl_offset,
            duration=args.duration,
            outside_rth=args.outside_rth,
            outside_rth_for_tp=args.outside_rth_for_tp,
            dry_run=args.dry_run,
        ))
    elif args.cmd == "place-bracket":
        run(lambda: place_bracket(
            args.symbol, args.side, args.qty,
            entry=args.entry,
            take_profit=args.take_profit, stop_loss=args.stop_loss,
            tp_offset=args.tp_offset, sl_offset=args.sl_offset,
            order_type=args.order_type,
            duration=args.duration,
            outside_rth=args.outside_rth,
            outside_rth_for_tp=args.outside_rth_for_tp,
            dry_run=args.dry_run,
        ))
    elif args.cmd == "cancel":
        run(lambda: cancel_order(args.order_id, dry_run=args.dry_run))
    elif args.cmd == "cancel-all":
        run(lambda: cancel_all(dry_run=args.dry_run))


if __name__ == "__main__":
    _main()
