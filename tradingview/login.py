"""
One-time interactive TradingView login.

Run this once. It opens a visible browser window pointed at TradingView's
sign-in page. You log in normally (Google/email/2FA — whatever you use). The
session cookies persist in SESSION_DIR so every subsequent script — both
`screenshot.py` and `bridge.py` — runs as you, without re-authenticating.

Usage:
    .venv/bin/python login.py

Re-run only if:
  - TradingView signs you out (rare; cookies last weeks)
  - You want to switch accounts
  - You wipe the session/ directory
"""

from __future__ import annotations

import asyncio
import sys

from session import SESSION_DIR, is_logged_in, tv_context


POLL_INTERVAL_S = 2
POLL_TIMEOUT_S = 900  # 15 minutes for the user to complete sign-in + 2FA


async def main() -> int:
    print(f"Persistent session dir: {SESSION_DIR}", flush=True)
    print("Opening a visible browser. Sign in to TradingView in the window.", flush=True)
    print(f"Auto-detecting login (polling every {POLL_INTERVAL_S}s, timeout {POLL_TIMEOUT_S}s)...", flush=True)
    print(flush=True)

    # Force headless=False — login is the one moment we MUST be visible.
    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        # wait_until="domcontentloaded" — TradingView's accounts page holds
        # long-lived WebSockets, so the default "load" never fires and goto
        # times out. DOM-ready is enough for a sign-in form to be usable.
        await page.goto(
            "https://www.tradingview.com/accounts/signin/",
            wait_until="domcontentloaded",
        )

        elapsed = 0
        while elapsed < POLL_TIMEOUT_S:
            # We poll on /chart/ (not the signin page) because that's the page
            # that proves cookies are wired up, and where `is_logged_in`
            # checks for the absence of the "Sign in" button reliably.
            if page.url != "https://www.tradingview.com/chart/":
                # Once we no longer see the signin form (because TV redirected
                # us post-login), jump to the chart page to confirm.
                if await page.locator('input[name="username"], input[name="email"]').count() == 0:
                    await page.goto(
                        "https://www.tradingview.com/chart/",
                        wait_until="domcontentloaded",
                    )
                    await page.wait_for_timeout(2000)
            if await is_logged_in(page):
                break
            print(f"  ...waiting for login ({elapsed}s)", flush=True)
            await asyncio.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
        else:
            print("ERROR: Timed out waiting for login.", flush=True)
            return 1

        # Backup the auth state to a portable JSON file BEFORE closing
        # the context. If the persistent profile ever gets wiped (we've
        # seen this happen after some automation runs), we can restore
        # from this JSON via storage_state without re-logging in.
        backup_path = SESSION_DIR.parent / "storage_state.json"
        await ctx.storage_state(path=str(backup_path))
        print(f"Also saved storage_state backup: {backup_path}", flush=True)

    print(flush=True)
    print("Logged in. Cookies saved to:", flush=True)
    print(f"  {SESSION_DIR}", flush=True)
    print("You can now run screenshot.py and bridge.py without signing in again.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
