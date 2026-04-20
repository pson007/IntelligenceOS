"""Pick the first *visible* match for a raw CSS selector.

TradingView frequently renders multiple DOM copies of the same control
for responsive-layout variants (narrow vs wide toolbar). Playwright's
`locator(sel).first` is DOM-order-based, so it silently picks the
hidden duplicate when that duplicate comes first in DOM order — the
resulting click lands on nothing and the flow looks "flaky."

The sibling helper `selectors.first_visible(page, surface, name)` does
the right thing, but it requires every selector to be registered in
`selectors.yaml`. Surface modules that own a narrow area (Bar Replay,
probes) don't need that level of indirection — they want "give me the
visible element matching this raw CSS" as a one-liner.

Usage:

    from .lib.visible_locator import pick_visible, wait_visible

    btn = await pick_visible(page, 'div[title="Select date"]')
    if btn is None:
        raise SelectorDriftError(...)
    await btn.click()

    # Or, with polling when the element may appear after a transition:
    btn = await wait_visible(page, 'div[title="Select date"]',
                             timeout_ms=3000)
"""

from __future__ import annotations

import asyncio

from playwright.async_api import Locator, Page


async def pick_visible(page: Page, selector: str) -> Locator | None:
    """Return the first currently-visible Locator matching `selector`, or
    None. Non-blocking — single DOM pass, no polling.

    Use when you expect the element to be on screen already; combine
    with `wait_visible` when you need polling."""
    loc = page.locator(selector)
    try:
        n = await loc.count()
    except Exception:
        return None
    for i in range(n):
        item = loc.nth(i)
        try:
            if await item.is_visible():
                return item
        except Exception:
            # Element detached mid-check — skip.
            continue
    return None


async def wait_visible(
    page: Page, selector: str, *, timeout_ms: int = 5000,
    poll_ms: int = 200,
) -> Locator | None:
    """Poll `pick_visible` until a visible match appears or timeout
    elapses. Returns None on timeout rather than raising — callers
    typically want to decide whether a missing control is drift
    (raise) or just not-yet-mounted (retry)."""
    iterations = max(1, timeout_ms // poll_ms)
    for _ in range(iterations):
        loc = await pick_visible(page, selector)
        if loc is not None:
            return loc
        await asyncio.sleep(poll_ms / 1000)
    return None


async def any_visible(page: Page, selector: str) -> bool:
    """Non-blocking presence check — True if any match is visible right
    now. Use for `is_active()`-style state queries."""
    return (await pick_visible(page, selector)) is not None
