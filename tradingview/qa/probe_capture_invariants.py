"""Live probe — exercise capture_invariants against the attached Chrome.

Drives the SAME navigation path as `daily_profile` (enter Replay, jump
to today's session close, frame the view), then runs
`assert_capture_ready` with daily_profile's expectations and captures
a screenshot. Prints the per-check status and the PNG path so a human
can validate the invariant module is wired correctly.

Read-only side effects: enters Bar Replay on the active TV chart and
parks it at today's 16:00 ET. Does NOT call ChatGPT, does NOT write
any artifact other than the screenshot.

Usage:
    cd tradingview && .venv/bin/python -m qa.probe_capture_invariants
    cd tradingview && .venv/bin/python -m qa.probe_capture_invariants --date 2026-04-22
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from tv_automation.daily_profile import (
    _SCREENSHOT_ROOT, _frame_session_view, _navigate_to_session_close,
)
from tv_automation.lib.capture_invariants import (
    CaptureExpect, CaptureInvariantError, assert_capture_ready,
)
from tv_automation.lib.context import chart_session


async def main(date_str: str, symbol: str, no_navigate: bool) -> int:
    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    close_target = target_date.replace(hour=16, minute=0, second=0, microsecond=0)
    expect = CaptureExpect(
        symbol=f"{symbol}!" if "!" not in symbol else symbol,
        interval="1m",
        replay_mode=True,
        cursor_time=close_target,
        cursor_tolerance_min=30,
        soft_cursor=True,
    )
    print(f"probe: symbol={expect.symbol} interval={expect.interval} "
          f"date={date_str} close_target={close_target.strftime('%H:%M')} ET "
          f"navigate={'no' if no_navigate else 'yes'}",
          file=sys.stderr)

    async with chart_session() as (_ctx, page):
        if no_navigate:
            print("skipping navigation; checking chart as-is…", file=sys.stderr)
        else:
            print("navigating to session close…", file=sys.stderr)
            await _navigate_to_session_close(page, target_date)
            print("framing session view…", file=sys.stderr)
            await _frame_session_view(page, variant=0)

        print("\nrunning assert_capture_ready…", file=sys.stderr)
        try:
            summary = await assert_capture_ready(page, expect)
            ready_ok = True
        except CaptureInvariantError as e:
            summary = {"checks": {e.reason: {"ok": False, **e.details}}}
            ready_ok = False
            print(f"  HARD FAIL: {e}", file=sys.stderr)

        # Capture regardless so we can see what would have been shot.
        _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = _SCREENSHOT_ROOT / f"qa_probe_{symbol}_{date_str}_{ts}.png"
        await page.screenshot(path=str(out))

    print("\n=== INVARIANT SUMMARY ===", file=sys.stderr)
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nready_ok={ready_ok}", file=sys.stderr)
    print(f"screenshot: {out}", file=sys.stderr)
    print(out)  # stdout = single path so callers can pipe
    return 0 if ready_ok else 1


def cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                   help="YYYY-MM-DD (default: today)")
    p.add_argument("--symbol", default="MNQ1",
                   help="symbol stem; ! is appended if absent (default: MNQ1)")
    p.add_argument("--no-navigate", action="store_true",
                   help="skip Replay re-entry + framing; run invariants "
                        "against current chart state (debug only)")
    args = p.parse_args()
    return asyncio.run(main(args.date, args.symbol, args.no_navigate))


if __name__ == "__main__":
    sys.exit(cli())
