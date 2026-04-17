"""
Shared TradingView session — supports two modes.

MODE 1 (default): Launch our own persistent Chromium.
    Playwright's `launch_persistent_context` spawns a Chromium pointed at
    a directory that survives between runs (like a normal Chrome profile).
    The cookies and localStorage in TV_SESSION_DIR carry the TradingView
    login. Use `login.py` once to populate it.

MODE 2 (attach): Connect to your real, already-running Chrome over CDP.
    Set TV_CDP_URL=http://localhost:9222 in .env. Then run Chrome with
    `--remote-debugging-port=9222` (see start_chrome_cdp.sh). All scripts
    will drive THAT Chrome — your everyday browser, with your real
    TradingView session, no separate profile to maintain.

The mode is decided per-call by env: TV_CDP_URL set → attach, otherwise launch.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from playwright.async_api import BrowserContext, Page, async_playwright

load_dotenv()

# Resolve session dir relative to this file so scripts work from any CWD.
_DEFAULT_SESSION_DIR = Path(__file__).parent / "session"
SESSION_DIR = Path(os.getenv("TV_SESSION_DIR", _DEFAULT_SESSION_DIR)).expanduser().resolve()
HEADLESS = os.getenv("TV_HEADLESS", "true").lower() != "false"

# When set (e.g. "http://localhost:9222"), tv_context attaches to a running
# Chrome over the Chrome DevTools Protocol instead of launching its own.
CDP_URL = os.getenv("TV_CDP_URL", "").strip()

# Reasonable defaults — TradingView is heavy, so a desktop viewport gives the
# layout the Trading Panel scripts depend on. Only used in launch mode;
# attach mode inherits whatever size the user's Chrome window already is.
VIEWPORT = {"width": 1600, "height": 1000}

# Recent stable Chrome UA — TradingView occasionally tightens checks against
# Playwright's default UA which advertises "HeadlessChrome".
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


@asynccontextmanager
async def tv_context(headless: bool | None = None) -> AsyncIterator[BrowserContext]:
    """
    Yield a logged-in TradingView BrowserContext.

    If TV_CDP_URL is set, attaches to the running Chrome at that URL and
    yields its existing default context — *we do not close it on exit*,
    because that would kill the user's browser.

    Otherwise launches a fresh persistent Chromium against TV_SESSION_DIR
    (the original behavior) and closes it cleanly on exit.

    Usage:
        async with tv_context() as ctx:
            page = await ctx.new_page()
            await page.goto("https://www.tradingview.com/chart/")
    """
    async with async_playwright() as pw:
        if CDP_URL:
            # ---- ATTACH MODE -----------------------------------------------
            # connect_over_cdp returns a Browser object. Its `.contexts[0]`
            # is the user's existing default profile context — that's where
            # all their tabs live and where TradingView's cookies are.
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            if not browser.contexts:
                raise RuntimeError(
                    f"Connected to {CDP_URL} but no contexts found — "
                    "is Chrome actually running with --remote-debugging-port?"
                )
            ctx = browser.contexts[0]
            try:
                yield ctx
            finally:
                # IMPORTANT: do not call ctx.close() — that closes Chrome.
                # Just disconnect our CDP transport; the browser keeps running.
                await browser.close()
            return

        # ---- LAUNCH MODE (original behavior) -------------------------------
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        effective_headless = HEADLESS if headless is None else headless
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=effective_headless,
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
            # TradingView fingerprints HeadlessChrome more aggressively than
            # plain Chromium; this flag hides one of the obvious tells.
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield ctx
        finally:
            await ctx.close()


async def open_chart(ctx: BrowserContext, symbol: str | None = None,
                     interval: str | None = None) -> Page:
    """
    Open (or reuse) a TradingView chart page in the given context.

    In attach mode, if there's already a TradingView chart tab open we
    reuse it — much friendlier to the user, and avoids piling up tabs
    over time. We *do* navigate it to the requested symbol/interval if
    those were specified.

    Interval format matches TradingView's URL params:
        "1", "5", "15", "60" (1h), "240" (4h), "D", "W", "M"
    """
    url = "https://www.tradingview.com/chart/"
    params = []
    if symbol:
        params.append(f"symbol={symbol}")
    if interval:
        params.append(f"interval={interval}")
    if params:
        url = f"{url}?{'&'.join(params)}"

    # In attach mode, prefer an existing TV chart tab.
    page: Page | None = None
    if CDP_URL:
        for p in ctx.pages:
            try:
                if "tradingview.com/chart" in p.url:
                    page = p
                    await page.bring_to_front()
                    break
            except Exception:
                # A page might be navigating/closing; just skip it.
                continue

    if page is None:
        page = await ctx.new_page()

    # Always (re)navigate when caller asked for a specific symbol/interval,
    # OR when the existing tab isn't on a chart URL yet.
    needs_nav = bool(params) or "tradingview.com/chart" not in page.url
    if needs_nav:
        await page.goto(url, wait_until="domcontentloaded")

    # The chart's main canvas is the reliable signal that the chart is ready.
    # Waiting on networkidle is unreliable — TradingView holds open WebSockets.
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    # Small buffer so indicators/drawings finish their first paint pass.
    await page.wait_for_timeout(1500)
    return page


async def is_logged_in(page: Page) -> bool:
    """
    True if the browser context holds a TradingView `sessionid` cookie.

    We check via the CDP cookies API rather than ``document.cookie``
    because TradingView marks ``sessionid`` as HttpOnly — the JS
    property never exposes it, even when you're signed in. The
    ``page.context.cookies()`` call goes through CDP and *does* see
    HttpOnly cookies. This is the authoritative check.
    """
    cookies = await page.context.cookies("https://www.tradingview.com/")
    return any(c["name"] == "sessionid" for c in cookies)
