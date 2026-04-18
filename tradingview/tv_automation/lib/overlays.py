"""Shared UI-overlay handling for TradingView automation.

Three concerns consolidated here:

  1. **Toast dismissal**. When an order fills or cancels, TV renders a
     bottom-left toast that intercepts pointer events for ~5s. Any
     automation running during that window sees "subtree intercepts
     pointer events" click failures. `dismiss_toasts` presses Escape
     and clicks the chart body to drop any floating overlay.

  2. **Account Manager expand/collapse**. Every Tier-1/Tier-2 surface
     that reads orders or positions needs the AM expanded. Historically
     each module rolled its own `_ensure_account_manager_open` — and
     each got the SAME bug: `any_visible(positions_table)` returns
     False when AM is open but on the Orders tab (table hidden but
     in DOM), so the module clicks the toggle — which COLLAPSES the
     AM — then waits for the table to become visible, times out.

     The correct check is "is any tab button in the AM tab strip
     visible?" — tab buttons are always visible once AM is expanded,
     regardless of which tab is active.

  3. **Monaco / overlap-manager-root pointer-event interception**.
     When the Pine Editor is right-docked, its wrapper inside
     `#overlap-manager-root` (class prefix `wrapper-`) extends beyond
     Monaco's visible area and intercepts pointer events targeting
     the right-side widget toolbar (alerts icon, watchlist sidebar
     icon, etc.). Playwright correctly detects the intercept and
     refuses to click — but the user IS able to see the underlying
     button. `bypass_overlap_intercept` injects a transient
     `pointer-events: none` style on overlap-manager-root's children
     so clicks pass through to whatever's beneath. Restored on exit.
"""

from __future__ import annotations

import contextlib
from typing import AsyncIterator

from playwright.async_api import Page

from . import selectors

# Injected style id — used as the marker for cleanup. Single shared id
# is fine because the helper is a context manager that always cleans up.
_BYPASS_STYLE_ID = "__tv_auto_overlap_bypass"


async def dismiss_toasts(page: Page, *, attempts: int = 3) -> None:
    """Best-effort drop of any floating overlay that might intercept
    pointer events. Safe to call before any click that might be near
    a recent order-fill event.

    Strategy: press Escape a few times (closes most TV menus/toasts),
    then click the chart canvas center (defocus any modal). We don't
    raise on failure — this is defense-in-depth, not a correctness
    guarantee."""
    try:
        for _ in range(attempts):
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(100)
    except Exception:
        pass
    try:
        # Click near center of the chart canvas — specific enough to
        # miss UI controls but not so central as to hit crosshair tools.
        canvas = page.locator("canvas").first
        if await canvas.count() > 0:
            box = await canvas.bounding_box()
            if box:
                await page.mouse.click(
                    int(box["x"] + box["width"] * 0.4),
                    int(box["y"] + box["height"] * 0.5),
                )
                await page.wait_for_timeout(150)
    except Exception:
        pass


@contextlib.asynccontextmanager
async def bypass_overlap_intercept(page: Page) -> AsyncIterator[None]:
    """Temporarily disable pointer events on `#overlap-manager-root`'s
    descendants so clicks targeting elements behind them (right-toolbar
    icons, sidebar widgets) actually land.

    Why this is needed: when the Pine Editor is right-docked, its
    panel wrapper (`wrapper-<HASH>` inside `overlap-manager-root`)
    extends invisibly into the right-toolbar area at y < Monaco's
    top edge. Playwright's actionability check correctly reports
    "subtree intercepts pointer events" and refuses to click — but
    the user can SEE and click those buttons fine because the
    wrapper is transparent at those coordinates.

    Setting `pointer-events: none` on every descendant of
    `overlap-manager-root` (with `!important` to outrank inline styles)
    makes the entire overlap layer non-interactive for the duration
    of the context. The Pine editor remains visually on screen but
    pointer events pass through to underlying elements.

    Use sparingly — wrap only the specific click that's being
    intercepted, not larger blocks of code, so the user can
    interact with Pine the rest of the time."""
    await page.evaluate(
        r"""(styleId) => {
            // Remove any stale style first (defensive — context-manager
            // exits should always clean up but better safe than sorry).
            const stale = document.getElementById(styleId);
            if (stale) stale.remove();
            const s = document.createElement('style');
            s.id = styleId;
            s.textContent = `
                #overlap-manager-root, #overlap-manager-root * {
                    pointer-events: none !important;
                }
            `;
            document.head.appendChild(s);
        }""",
        _BYPASS_STYLE_ID,
    )
    try:
        yield
    finally:
        # Always clean up, even if the wrapped block raised.
        try:
            await page.evaluate(
                r"""(styleId) => {
                    const s = document.getElementById(styleId);
                    if (s) s.remove();
                }""",
                _BYPASS_STYLE_ID,
            )
        except Exception:
            # Page may have navigated/closed mid-operation. Style is
            # tied to the document; new doc gets clean state anyway.
            pass


async def ensure_account_manager_open(page: Page, *, timeout_ms: int = 5000) -> None:
    """Expand the bottom Account Manager if it's collapsed. Idempotent.

    Detects open-state by checking for the Orders tab button's
    visibility — which is always present when the AM tab strip is
    expanded, regardless of which tab is currently active. (Previously
    modules checked for a specific table's visibility, which failed
    for the "AM open on a different tab" case.)

    Calls `dismiss_toasts` first so the toggle click doesn't get
    intercepted by a fresh order-fill toast.
    """
    await dismiss_toasts(page)

    # Any tab-strip button serves as the "AM expanded" signal. Orders is
    # a good choice — selector is already in selectors.yaml.
    if await selectors.any_visible(page, "trading_panel", "orders_tab"):
        return

    toggle = await selectors.first_visible(
        page, "trading_panel", "account_manager_toggle", timeout_ms=timeout_ms,
    )
    await toggle.click()
    # Wait for the tab strip to appear — confirms AM is now expanded.
    await selectors.first_visible(
        page, "trading_panel", "orders_tab", timeout_ms=8000,
    )


async def activate_am_tab(
    page: Page, tab_role: str, *, timeout_ms: int = 5000,
) -> None:
    """Ensure AM is open AND the given tab is the active one.

    `tab_role` is a role key under `trading_panel.*` — e.g. "positions_tab",
    "orders_tab", "order_history_tab". Dismisses toasts first; skips the
    click if the tab is already `aria-selected="true"`.
    """
    await ensure_account_manager_open(page, timeout_ms=timeout_ms)
    tab = await selectors.first_visible(
        page, "trading_panel", tab_role, timeout_ms=timeout_ms,
    )
    if await tab.get_attribute("aria-selected") == "true":
        return
    # Re-dismiss before click — previous toggle might have caused a new
    # overlay (e.g. AM expanding animation).
    await dismiss_toasts(page, attempts=1)
    await tab.click()
    await page.wait_for_timeout(300)
