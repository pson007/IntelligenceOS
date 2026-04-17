"""Chart surface — symbol/timeframe control, screenshots, chart metadata.

Pure reads (screenshot, metadata) don't take the lock or assert paper
trading — they can't move money. `set-symbol` navigates the existing
chart tab so any open Pine Editor / Trading Panel follows along.

CLI:
    python -m tv_automation.chart set-symbol NVDA --tf 60
    python -m tv_automation.chart set-symbol AAPL --tf 1D
    python -m tv_automation.chart screenshot AAPL 1D
    python -m tv_automation.chart screenshot AAPL 1D -o /tmp/x.png
    python -m tv_automation.chart metadata         # current chart info
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from preflight import ensure_automation_chromium  # top-level module in tradingview/
from session import tv_context

from .lib import audit
from .lib.cli import run
from .lib.guards import assert_logged_in
from .lib.urls import chart_url_for

# Friendly timeframe → TradingView's URL `interval` param.
# TV uses minute counts as strings, plus single letters for D/W/M.
# Lookup is case-insensitive for minute/hour frames ("1h" / "1H" both ok)
# while preserving the canonical casing for D/W/M (TV's URL param is
# uppercase there).
_TIMEFRAME_MAP = {
    "1m": "1", "2m": "2", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240",
    "1d": "D", "1w": "W", "1mo": "M",
    # Also accept the canonical uppercase forms directly.
    "1D": "D", "1W": "W", "1M": "M",
}


def resolve_timeframe(tf: str | None) -> str | None:
    """Map a friendly timeframe to TradingView's interval param.
    Case-insensitive for m/h; accepts 1D/1W/1M in either case. Returns
    None for None input; pass-through if already a TV interval string
    like "60" or "D"."""
    if tf is None:
        return None
    # Try exact first (preserves "1D" vs "1d" if user passed explicitly).
    if tf in _TIMEFRAME_MAP:
        return _TIMEFRAME_MAP[tf]
    # Case-insensitive fallback.
    low = tf.lower()
    if low in _TIMEFRAME_MAP:
        return _TIMEFRAME_MAP[low]
    # Might already be a TV-native interval (e.g. "60", "D"). Pass through.
    return tf


# Back-compat export — some code still references TIMEFRAME_MAP.
TIMEFRAME_MAP = _TIMEFRAME_MAP

CHART_URL = "https://www.tradingview.com/chart/"

_DEFAULT_SCREENSHOT_DIR = Path.home() / "Desktop" / "TradingView"


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

async def _find_or_open_chart(ctx: BrowserContext) -> Page:
    """Reuse an existing TradingView chart tab if one is open; otherwise
    open a new one. Prefers the user's in-progress chart over creating
    parallel tabs that accumulate over time."""
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


async def _navigate(page: Page, symbol: str | None, interval: str | None) -> None:
    """Navigate the chart to symbol/interval, PRESERVING any saved-layout
    path segment in the current URL (e.g. `/chart/wqVfOr3Z/`). Without
    this, every symbol change wipes the user's saved indicators/drawings."""
    if not symbol and not interval:
        return
    target = chart_url_for(page.url, symbol, interval)
    await page.goto(target, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    # Slight buffer — quick-trade bar, indicators, legend all hydrate
    # after the canvas paints.
    await page.wait_for_timeout(1500)


async def _extract_metadata(page: Page) -> dict:
    """Read the active chart's symbol + interval from title and DOM.
    Title is authoritative for symbol; interval is pulled from the
    active interval button when the title doesn't include it (common
    with saved layouts)."""
    title = await page.title()
    url = page.url
    symbol = interval = None

    m = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s+([A-Z0-9]+)\s+chart", title)
    if m:
        symbol, interval = m.group(1), m.group(2)
    else:
        m2 = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s", title)
        if m2:
            symbol = m2.group(1)

    if not symbol:
        um = re.search(r"[?&]symbol=([^&]+)", url)
        if um:
            symbol = um.group(1)
    if not interval:
        um = re.search(r"[?&]interval=([^&]+)", url)
        if um:
            interval = um.group(1)

    if not interval:
        try:
            interval = await page.evaluate("""() => {
              const active = document.querySelector(
                '#header-toolbar-intervals button[aria-pressed="true"]'
              ) || document.querySelector(
                '#header-toolbar-intervals button[class*="isActive"]'
              );
              if (active && active.innerText) return active.innerText.trim();
              const btn = document.querySelector(
                'button[aria-label^="Change interval"], button[id="header-toolbar-intervals"]'
              );
              return btn && btn.innerText ? btn.innerText.trim() : null;
            }""")
        except Exception:
            interval = None

    return {
        "symbol": symbol or "UNKNOWN",
        "interval": interval or "UNKNOWN",
        "url": url,
        "title": title,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def set_symbol(symbol: str, interval: str | None = None) -> dict:
    """Navigate the active chart tab to the given symbol (and optionally
    timeframe). Returns the resulting metadata."""
    tv_interval = resolve_timeframe(interval)
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await _navigate(page, symbol, tv_interval)
        meta = await _extract_metadata(page)
        audit.log("chart.set_symbol", symbol=symbol, interval=interval, resolved=meta)
        return meta


async def screenshot(
    symbol: str | None,
    interval: str | None,
    output: Path | None,
) -> dict:
    """Capture a PNG of the main chart area. If symbol/interval given,
    navigate first. Returns path + metadata."""
    tv_interval = resolve_timeframe(interval)
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await _navigate(page, symbol, tv_interval)
        meta = await _extract_metadata(page)

        if output is None:
            _DEFAULT_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", meta["symbol"])
            safe_int = re.sub(r"[^A-Za-z0-9]+", "_", meta["interval"])
            output = _DEFAULT_SCREENSHOT_DIR / f"{safe_sym}_{safe_int}_{ts}.png"
        else:
            output.parent.mkdir(parents=True, exist_ok=True)

        # Prefer the chart-only region; fall back to full viewport.
        region = page.locator(".chart-container, .layout__area--center").first
        try:
            await region.wait_for(state="visible", timeout=5000)
            await region.screenshot(path=str(output))
        except Exception:
            await page.screenshot(path=str(output), full_page=False)

        audit.log("chart.screenshot", path=str(output), **meta)
        return {"path": str(output), **meta}


async def metadata() -> dict:
    """Return current chart's symbol, interval, and URL. Read-only."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        return await _extract_metadata(page)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.chart")
    sub = p.add_subparsers(dest="cmd", required=True)

    ss = sub.add_parser("set-symbol", help="Navigate chart to a symbol")
    ss.add_argument("symbol")
    ss.add_argument("--tf", "--interval", dest="interval",
                    help="Timeframe, e.g. 5m, 1h, 1D")

    sh = sub.add_parser("screenshot", help="Capture a chart PNG")
    sh.add_argument("symbol", nargs="?",
                    help="Optional symbol to navigate to before capture")
    sh.add_argument("timeframe", nargs="?",
                    help="Optional timeframe, e.g. 1D, 1h, 5m (case-insensitive)")
    sh.add_argument("-o", "--output", type=Path, default=None,
                    help="Output PNG path (default: ~/Desktop/TradingView/...)")

    sub.add_parser("metadata", help="Print current chart metadata")

    args = p.parse_args()

    if args.cmd == "set-symbol":
        run(lambda: set_symbol(args.symbol, args.interval))
    elif args.cmd == "screenshot":
        run(lambda: screenshot(args.symbol, args.timeframe, args.output))
    elif args.cmd == "metadata":
        run(lambda: metadata())


if __name__ == "__main__":
    _main()
