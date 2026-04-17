"""Shared browser-context helpers.

The attach/detach cycle (`ensure_automation_chromium()` + `tv_context()`
entry/exit) costs about 2 seconds per CLI invocation. A single-shot CLI
pays that once. Multiple reads in a row pay it N times.

This module provides:

  * `browser_context()` — the common "ensure Chromium, yield the shared
    Playwright BrowserContext" pattern. Every surface module uses this.

  * `chart_session()` — one step further: opens/reuses a TradingView
    chart tab, asserts login, and yields (ctx, page) ready to drive.
    Most read and mutate operations want this.

  * `find_or_open_chart()` — shared implementation that surface modules
    duplicated. Now single-sourced.

Aggregate CLIs (see `status.py`) hold one `chart_session()` open and
perform many reads within it, amortizing the ~2s attach cost across all
reads — which is the "batch composition without a daemon" answer.
"""

from __future__ import annotations

import contextlib
from typing import AsyncIterator

from playwright.async_api import BrowserContext, Page

from preflight import ensure_automation_chromium
from session import tv_context

from .guards import assert_logged_in

CHART_URL = "https://www.tradingview.com/chart/"


@contextlib.asynccontextmanager
async def browser_context() -> AsyncIterator[BrowserContext]:
    """Ensure Chromium-Automation is up and yield a logged-in
    BrowserContext. Closes cleanly on exit (disconnects CDP; does NOT
    kill the user's Chromium window)."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        yield ctx


async def find_or_open_chart(ctx: BrowserContext) -> Page:
    """Reuse an existing TradingView chart tab in `ctx` if one is open;
    otherwise open a fresh one. Shared by all surface modules."""
    for p in ctx.pages:
        try:
            if "tradingview.com/chart" in p.url:
                await p.bring_to_front()
                return p
        except Exception:
            # Page might be navigating/closing — just try the next.
            continue
    page = await ctx.new_page()
    await page.goto(CHART_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    await page.wait_for_timeout(1500)
    return page


@contextlib.asynccontextmanager
async def chart_session() -> AsyncIterator[tuple[BrowserContext, Page]]:
    """browser_context + find_or_open_chart + assert_logged_in. Yields
    (ctx, page) — what most operations actually want."""
    async with browser_context() as ctx:
        page = await find_or_open_chart(ctx)
        await assert_logged_in(page)
        yield ctx, page
