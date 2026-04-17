"""Retry helper for transient Playwright/CDP errors.

We retry ONLY on connection-level failures (ECONNRESET, WebSocket
disconnect, "connect_over_cdp" timeouts). We never retry on business
errors (NotLoggedInError, NotPaperTradingError, LimitViolationError,
VerificationFailedError) — those are intentional aborts and should
surface immediately.

Why conservative: the Playwright-vs-Chromium CDP transport can hiccup
(we've observed ECONNRESET during `connect_over_cdp`). A single retry
with a short backoff converts those from CLI failures into invisible
retries, which is exactly what LLM-driven workflows need.

Why not aggressive: retrying on business errors would mask real bugs
(clicked wrong button, selector drift, broker mismatch).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

from .errors import TVAutomationError

log = logging.getLogger("tv-automation.retry")

T = TypeVar("T")

# Playwright packs a variety of transport errors into its generic Error
# class with messages like:
#   "BrowserType.connect_over_cdp: read ECONNRESET"
#   "BrowserType.connect_over_cdp: Target page, context or browser has been closed"
#   "Locator.click: Target closed"
# We match on substrings we've actually seen fail-then-succeed.
_TRANSIENT_MARKERS = (
    "econnreset",
    "target closed",
    "target page, context or browser has been closed",
    "browser has been closed",
    "websocket error",
    "ws preparing",
    "connection closed",
    "socket hang up",
    "read etimedout",
)


def _is_transient(exc: BaseException) -> bool:
    """True if `exc` looks like a transient connection-level issue."""
    # Never retry typed business errors.
    if isinstance(exc, TVAutomationError):
        return False
    # Never retry keyboard interrupt etc.
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return False
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


async def run_with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    initial_delay: float = 0.5,
) -> T:
    """Run `coro_factory()` up to `attempts` times, retrying on transient
    errors with exponential backoff (0.5s → 1s → 2s by default).

    Re-raises the last exception if all attempts fail, or immediately on
    a non-transient error.
    """
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except Exception as e:  # noqa: BLE001
            if not _is_transient(e) or attempt == attempts - 1:
                raise
            delay = initial_delay * (2 ** attempt)
            log.warning(
                "Transient error on attempt %d/%d: %s. Retrying in %.1fs...",
                attempt + 1, attempts, e, delay,
            )
            last_exc = e
            await asyncio.sleep(delay)
    # Unreachable — the loop re-raises on the last attempt — but keep
    # type-checkers happy.
    assert last_exc is not None
    raise last_exc
