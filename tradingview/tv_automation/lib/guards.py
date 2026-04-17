"""Safety guards — run BEFORE every mutating action.

The three non-negotiables:
  1. Logged in — cookie present, session not expired.
  2. Paper Trading active — the single most important check. Clicking
     BUY against a real broker turns LLM-driven autonomy into real
     money lost. We verify the active-broker label before any order.
  3. Process lock — only one TV automation process acts on the browser
     at a time. Two simultaneous `page.click()` calls race and produce
     undefined outcomes.

Read guards (screenshot, positions listing, etc.) skip paper-trading
and lock checks — pure reads can run in parallel and don't mutate.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import Page

from .errors import NotLoggedInError, NotPaperTradingError
from . import selectors as _selectors

_LOCK_DIR = Path("/tmp/tv-automation")


async def assert_logged_in(page: Page) -> None:
    """Verify the attached context has a TradingView sessionid cookie.
    The cookie is HttpOnly so we check via CDP (page.context.cookies)
    rather than document.cookie — the JS property never sees it."""
    cookies = await page.context.cookies("https://www.tradingview.com/")
    if not any(c["name"] == "sessionid" for c in cookies):
        raise NotLoggedInError(
            "No TradingView sessionid cookie. Sign in to the Chromium-Automation "
            "profile (CDP on :9222), then retry."
        )


async def assert_paper_trading(page: Page) -> None:
    """Refuse to proceed if the Trading Panel's active broker isn't Paper Trading.

    Two failure modes we're guarding against:
      A. Broker picker dialog is visible → no broker connected at all.
         Clicking BUY opens the picker, not a trade. Harmless but not what
         we want. Raised as NotPaperTradingError(None).
      B. A real broker is connected (e.g. Interactive Brokers, Tradovate).
         Clicking BUY places a REAL order. This is the dangerous case. We
         read the broker chip label at the top of the Trading Panel.

    If neither check finds a broker chip, we assume the Trading Panel
    isn't open yet and let the caller handle it (they typically need to
    open it anyway for the specific action they're about to take).
    """
    # Lazy import to avoid circular: config → (selectors ← guards → config).
    from .. import config

    # Case A: broker picker open?
    if await _selectors.any_visible(page, "trading_panel", "broker_picker_dialog"):
        raise NotPaperTradingError(None)

    # Case B: read active broker label from the Account Manager toggle
    # button. On TV Pro+, the toggle's aria-label is "Open Account Manager"
    # (collapsed) or "Close Account Manager" (expanded); its *inner text*
    # is the broker name, e.g. "Paper Trading". Probes keep this selector
    # list fresh in selectors.yaml → trading_panel.broker_chip.
    for sel in _selectors.candidates("trading_panel", "broker_chip"):
        loc = page.locator(sel).first
        if await loc.count() == 0:
            continue
        try:
            label = (await loc.inner_text()).strip()
        except Exception:
            continue
        # Strip currency/balance suffixes — the button sometimes renders
        # "Paper Trading" on one line and a balance on another.
        label_head = label.splitlines()[0].strip() if label else ""
        if not label_head:
            continue
        if not config.broker_label_allowed(label_head):
            raise NotPaperTradingError(label_head)
        return  # Confirmed allowed broker (paper trading).

    # No broker chip found anywhere. Don't fail hard — the trading panel
    # may simply not be open yet. Downstream code will surface a clearer
    # error if its selector isn't found.
    return


_AsyncCM = contextlib.AbstractAsyncContextManager


@contextlib.asynccontextmanager
async def with_lock(name: str = "default", poll_s: float = 0.1) -> AsyncIterator[None]:
    """File-based advisory lock — serializes automation across processes.

    The bridge (deprecated path) used an asyncio.Lock, which only protects
    one process. CLI invocations are separate processes. Use `flock(2)` on
    /tmp/tv-automation/<name>.lock so concurrent CLIs queue cleanly.

    Convention: use `"tv_browser"` for any operation that mutates the
    browser UI — trading, chart navigation, pine editing, indicator
    settings. Different names don't serialize against each other, so a
    split name would let two processes race on the same tab.

    Usage:
        async with with_lock("tv_browser"):
            ...  # only one process runs this at a time
    """
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _LOCK_DIR / f"{name}.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        # asyncio-friendly spin: non-blocking flock + sleep yields control
        # to the event loop, so other coroutines in this process keep
        # progressing while we wait.
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(poll_s)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
