"""
End-to-end pipeline: capture chart → wait for Pine file → apply to TradingView.

The middle step (analysis + Pine generation) is expected to happen OUT of
band — typically by Claude Code reading the screenshot and writing the
Pine file at the deterministic path this script prints. That's why this
file exists separately from the capture / apply scripts: it doesn't
assume who or what produces the Pine code, only that it lands at a
specific file path.

Typical interactive use with Claude Code:

    # Terminal (or Claude Code in background mode)
    .venv/bin/python analyze_and_apply.py

        Symbol:   MNQ1!
        Interval: 5
        Screenshot: pine/captures/MNQ1__5_20260416-180501.png
        Waiting for Pine at: pine/generated/MNQ1__5_20260416-180501.pine
        ...

    # In Claude Code — read the screenshot, write a .pine file to
    # exactly that path. This script polls and detects the file,
    # then invokes apply_pine.py on it.

Usage:
    .venv/bin/python analyze_and_apply.py                  # default
    .venv/bin/python analyze_and_apply.py --symbol TSLA --interval 60
    .venv/bin/python analyze_and_apply.py --timeout 600    # longer wait
    .venv/bin/python analyze_and_apply.py --no-apply       # stop after capture
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from capture_chart import extract_metadata, find_or_open_chart, OUT_DIR as CAPTURE_DIR
from preflight import ensure_automation_chromium
from session import is_logged_in, tv_context

GENERATED_DIR = Path(__file__).parent / "pine" / "generated"
APPLY_SCRIPT = Path(__file__).parent / "apply_pine.py"
CHART_URL = "https://www.tradingview.com/chart/"


async def capture(page, symbol: str | None, interval: str | None) -> tuple[Path, Path, dict]:
    """Capture screenshot + metadata. Return (png_path, expected_pine_path, meta).
    The expected_pine_path is the deterministic slot where the Pine
    generator (Claude Code, human, or whatever) should write its output."""
    if symbol or interval:
        params = []
        if symbol:
            params.append(f"symbol={symbol}")
        if interval:
            params.append(f"interval={interval}")
        await page.goto(
            f"{CHART_URL}?{'&'.join(params)}",
            wait_until="domcontentloaded",
        )
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(1500)

    meta = await extract_metadata(page)

    ts = time.strftime("%Y%m%d-%H%M%S")
    safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", meta["symbol"])
    safe_int = re.sub(r"[^A-Za-z0-9]+", "_", meta["interval"])
    base = f"{safe_sym}_{safe_int}_{ts}"

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    png = CAPTURE_DIR / f"{base}.png"
    meta_path = CAPTURE_DIR / f"{base}.json"
    pine = GENERATED_DIR / f"{base}.pine"

    await page.screenshot(path=str(png), full_page=False)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    return png, pine, meta


async def wait_for_file(path: Path, timeout: float, poll: float = 2.0) -> bool:
    """Poll until `path` exists and is non-empty. Returns True on success."""
    elapsed = 0.0
    while elapsed < timeout:
        if path.exists() and path.stat().st_size > 0:
            # Give any concurrent writer a beat to finish (Write tool is
            # atomic but nicer to be paranoid).
            await asyncio.sleep(0.2)
            return True
        await asyncio.sleep(poll)
        elapsed += poll
        if int(elapsed) % 10 == 0:
            print(f"  ...waiting for Pine ({int(elapsed)}s / {int(timeout)}s)",
                  flush=True)
    return False


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Capture → wait-for-Pine → apply to TradingView.")
    ap.add_argument("--symbol", help="Optional: navigate to this symbol first")
    ap.add_argument("--interval", help="Optional: navigate to this interval first")
    ap.add_argument("--timeout", type=float, default=300.0,
                    help="How long to wait for the Pine file (default 300s)")
    ap.add_argument("--no-apply", action="store_true",
                    help="Stop after capture — don't wait or apply")
    args = ap.parse_args()

    await ensure_automation_chromium()

    async with tv_context(headless=False) as ctx:
        page = await find_or_open_chart(ctx)

        if not await is_logged_in(page):
            print("ERROR: not signed in to TradingView.", flush=True)
            return 1

        png, pine, meta = await capture(page, args.symbol, args.interval)

        print(f"Symbol:        {meta['symbol']}", flush=True)
        print(f"Interval:      {meta['interval']}", flush=True)
        print(f"Screenshot:    {png}", flush=True)
        print(f"Expected Pine: {pine}", flush=True)

        if args.no_apply:
            return 0

        print(f"\nWaiting up to {int(args.timeout)}s for {pine.name}...",
              flush=True)
        ok = await wait_for_file(pine, args.timeout)
        if not ok:
            print(f"TIMEOUT: {pine} did not appear within {args.timeout}s.",
                  flush=True)
            return 2

        print(f"Pine detected ({pine.stat().st_size} bytes). Applying...",
              flush=True)

    # Drop the Playwright session before apply_pine runs — it will open
    # its own attach. This avoids two connections racing.

    result = subprocess.run(
        [sys.executable, str(APPLY_SCRIPT), str(pine)],
        cwd=str(Path(__file__).parent),
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
