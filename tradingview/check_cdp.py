"""
Verify the CDP attach works.

Usage:
    .venv/bin/python check_cdp.py

Prints the connected Chrome version, lists all open tabs, and reports
whether any TradingView tab is signed in (sessionid cookie present).
Exit codes:
  0  attached + signed in
  1  TV_CDP_URL not set
  2  could not connect to CDP
  3  attached but no TradingView tab (or not signed in)
"""

from __future__ import annotations

import asyncio
import sys

import httpx
from playwright.async_api import async_playwright

from session import CDP_URL, is_logged_in


async def main() -> int:
    if not CDP_URL:
        print("TV_CDP_URL is not set in .env. Set it to e.g. http://localhost:9222.")
        return 1

    # Pre-flight: hit /json/version directly so we get a clearer error than
    # Playwright's traceback when Chrome isn't running with the debug port.
    try:
        async with httpx.AsyncClient(timeout=3.0) as http:
            r = await http.get(f"{CDP_URL}/json/version")
            r.raise_for_status()
            ver = r.json()
            print(f"Chrome at {CDP_URL}:")
            print(f"  Browser:   {ver.get('Browser')}")
            print(f"  Protocol:  {ver.get('Protocol-Version')}")
    except Exception as e:
        print(f"ERROR: cannot reach {CDP_URL}/json/version — {e}")
        print("Did you run ./start_chrome_cdp.sh?")
        return 2

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        try:
            ctx = browser.contexts[0]
            print(f"\nOpen tabs ({len(ctx.pages)}):")
            tv_pages = []
            for p in ctx.pages:
                marker = "  *" if "tradingview.com" in p.url else "   "
                print(f"{marker} {p.url[:100]}")
                if "tradingview.com" in p.url:
                    tv_pages.append(p)

            if not tv_pages:
                print("\nNo TradingView tab found. Open one in Chrome and re-run.")
                return 3

            # Check auth on the first TV tab.
            tv = tv_pages[0]
            signed_in = await is_logged_in(tv)
            print(f"\nFirst TradingView tab signed in: {signed_in}")
            if not signed_in:
                print("Sign in to TradingView in that tab, then re-run.")
                return 3

            print("\nAttach OK — scripts will drive this Chrome.")
            return 0
        finally:
            # Disconnect CDP transport without closing the user's Chrome.
            await browser.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
