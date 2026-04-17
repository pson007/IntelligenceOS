"""
Screenshot a TradingView chart via Playwright.

Replaces the AppleScript-driven `tradingview-chart.sh`. This is more reliable
because it talks to the real DOM/canvas, not macOS Accessibility paths, so it
won't break when TradingView ships a UI redesign or when macOS updates.

Usage:
    .venv/bin/python screenshot.py AAPL                   # 1D, default output dir
    .venv/bin/python screenshot.py AAPL 1D
    .venv/bin/python screenshot.py BTCUSD 4h
    .venv/bin/python screenshot.py AAPL 1D -o /tmp/x.png  # custom path
    .venv/bin/python screenshot.py AAPL --headed          # show the browser

Output (default): ~/Desktop/TradingView/<SYMBOL>_<TIMEFRAME>_<TIMESTAMP>.png
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from session import open_chart, tv_context

# Friendly timeframe → TradingView URL `interval` param.
# TradingView uses minute counts as strings, plus single letters for D/W/M.
TIMEFRAME_MAP = {
    "1m": "1", "2m": "2", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240",
    "1D": "D", "1W": "W", "1M": "M",
}

DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "TradingView"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Screenshot a TradingView chart.")
    p.add_argument("symbol", help="Ticker symbol, e.g. AAPL, BTCUSD, NASDAQ:TSLA")
    p.add_argument(
        "timeframe", nargs="?", default="1D",
        choices=list(TIMEFRAME_MAP.keys()),
        help="Chart timeframe (default: 1D)",
    )
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Output PNG path (default: ~/Desktop/TradingView/<SYMBOL>_<TF>_<TS>.png)")
    p.add_argument("--headed", action="store_true",
                   help="Show the browser window (default: headless)")
    return p.parse_args()


def resolve_output_path(symbol: str, timeframe: str, override: Path | None) -> Path:
    if override is not None:
        override.parent.mkdir(parents=True, exist_ok=True)
        return override
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_symbol = symbol.replace(":", "_").replace("/", "_")
    return DEFAULT_OUTPUT_DIR / f"{safe_symbol}_{timeframe}_{ts}.png"


async def main() -> int:
    args = parse_args()
    interval = TIMEFRAME_MAP[args.timeframe]
    output_path = resolve_output_path(args.symbol, args.timeframe, args.output)

    async with tv_context(headless=not args.headed) as ctx:
        page = await open_chart(ctx, symbol=args.symbol, interval=interval)

        # Try to capture just the main chart area for a cleaner image; fall
        # back to a full viewport screenshot if TradingView's class names
        # have shifted. `.chart-container` is the long-standing wrapper
        # around the chart pane(s); `.layout__area--center` is the broader
        # center column (chart + legend + drawings toolbar overlay).
        chart = page.locator(".chart-container, .layout__area--center").first
        try:
            await chart.wait_for(state="visible", timeout=5_000)
            await chart.screenshot(path=str(output_path))
        except Exception:
            await page.screenshot(path=str(output_path), full_page=False)

    print(f"Saved: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
