"""
Preflight for CDP-attached automation.

Any script that uses `session.tv_context()` in attach mode should call
`await ensure_automation_chromium()` at the top of its main(). This:

  1. Checks whether CDP is reachable at TV_CDP_URL.
  2. If not, runs ./start_chrome_cdp.sh and waits for the port to bind.
  3. Checks whether a TradingView `sessionid` cookie is present in the
     attached browser's default context. If not, opens the sign-in page
     and tells the user to sign in, then polls until the cookie shows up.

Why this matters: the old flow required the user to manually run two
shell commands (start_chrome_cdp.sh, check_cdp.py) before any Python
automation would work. That's a trip-hazard. Now scripts self-heal.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from session import CDP_URL

START_SCRIPT = Path(__file__).parent / "start_chrome_cdp.sh"
TV_SIGNIN_URL = "https://www.tradingview.com/accounts/signin/"


async def _cdp_reachable(url: str, timeout: float = 1.5) -> bool:
    """True if GET {url}/json/version returns 200."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            r = await http.get(f"{url}/json/version")
            return r.status_code == 200
    except Exception:
        return False


async def _start_chromium_via_script() -> None:
    """Run start_chrome_cdp.sh in a subprocess and block until it exits."""
    if not START_SCRIPT.exists():
        raise RuntimeError(f"Launcher not found: {START_SCRIPT}")
    # Blocking — the script itself polls until CDP is up or gives up.
    result = subprocess.run(
        ["bash", str(START_SCRIPT)],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"start_chrome_cdp.sh exited with {result.returncode}. "
            "Inspect output above."
        )


async def _has_tv_session(cdp_url: str) -> bool:
    """True if the attached browser holds a TradingView sessionid cookie."""
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            ctx = browser.contexts[0]
            cookies = await ctx.cookies("https://www.tradingview.com/")
            return any(c["name"] == "sessionid" for c in cookies)
        finally:
            await browser.close()


def _existing_tv_targets(cdp_url: str) -> list[dict]:
    """List TV tabs via the CDP HTTP API. More reliable than Playwright's
    ctx.pages for dedup: each `connect_over_cdp` call returns a snapshot
    that can lag behind tabs created by a previous (recently-closed)
    connection, so rapid preflight cycles leak a fresh tab per call.
    The /json HTTP endpoint is authoritative."""
    base = cdp_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/json", timeout=2) as r:
            tabs = json.loads(r.read().decode())
    except Exception:
        return []
    return [t for t in tabs
            if t.get("type") == "page"
            and "tradingview.com" in (t.get("url") or "")]


async def _open_signin_and_wait(cdp_url: str, poll_interval: float = 2.0,
                                 timeout: float = 600.0) -> None:
    """Direct user to sign in (reusing an existing TV tab if any),
    poll for cookie. Never opens a tab when one already exists —
    that's the difference from the previous version, which leaked
    one tab per preflight invocation when the user stayed signed out
    across a multi-stage workflow."""
    existing = _existing_tv_targets(cdp_url)
    if existing:
        # Bring the existing tab to front via CDP — no Playwright
        # connection at all, so no risk of opening a new tab.
        try:
            tid = existing[0]["id"]
            urllib.request.urlopen(
                f"{cdp_url.rstrip('/')}/json/activate/{tid}", timeout=2,
            ).read()
        except Exception:
            pass
        target_url = existing[0].get("url") or TV_SIGNIN_URL
        print(f"\nNot signed in to TradingView.", flush=True)
        print(f"Sign in at the existing TradingView tab "
              f"({target_url[:80]}).", flush=True)
    else:
        # No TV tab exists — open exactly one signin tab via Playwright.
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            try:
                ctx = browser.contexts[0]
                page = await ctx.new_page()
                await page.goto(TV_SIGNIN_URL, wait_until="domcontentloaded")
                await page.bring_to_front()
            finally:
                await browser.close()
        print(f"\nNot signed in to TradingView.", flush=True)
        print(f"Sign in at {TV_SIGNIN_URL} in the automation Chromium window.",
              flush=True)
    print("Waiting for sign-in (polling cookie)...", flush=True)

    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        if await _has_tv_session(cdp_url):
            print(f"Signed in (after {elapsed:.0f}s). Continuing.", flush=True)
            return
        if int(elapsed) % 10 == 0:
            print(f"  ...still waiting ({int(elapsed)}s)", flush=True)

    raise RuntimeError(f"Sign-in not detected within {timeout:.0f}s.")


async def ensure_automation_chromium(require_signin: bool = True) -> None:
    """Top-level preflight. Call at the start of any CDP-using script.

    Args:
        require_signin: If True (default), block until a TradingView
            sessionid cookie appears. Pass False for scripts that don't
            need auth (rare — most TV automation does).
    """
    if not CDP_URL:
        # Not in attach mode — nothing to do. The legacy launch-persistent
        # flow handles its own sign-in via login.py.
        return

    # Stage 1: CDP reachable?
    if not await _cdp_reachable(CDP_URL):
        print(f"CDP at {CDP_URL} not reachable. Starting automation Chromium...",
              flush=True)
        await _start_chromium_via_script()
        # After the launcher, give the browser an extra moment to fully
        # populate contexts on a cold start.
        await asyncio.sleep(1.0)
        if not await _cdp_reachable(CDP_URL):
            raise RuntimeError(
                "Launcher succeeded but CDP still unreachable. "
                "Inspect start_chrome_cdp.sh output above."
            )

    # Stage 2: signed in?
    if require_signin and not await _has_tv_session(CDP_URL):
        await _open_signin_and_wait(CDP_URL)


if __name__ == "__main__":
    # Standalone: `python preflight.py` — useful as a warm-up before a
    # batch of automation commands.
    asyncio.run(ensure_automation_chromium())
    print("Preflight OK.")
