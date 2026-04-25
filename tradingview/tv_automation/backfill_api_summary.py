"""One-shot tool — patch historical `profiles/{SYMBOL}_{DATE}.json`
files with `actual_summary_api` so reconcile reads a deterministic
ground truth instead of falling through to the LLM-vision summary.

Backfilled profiles (Feb–Apr historical priors built before
2026-04-24) don't have `actual_summary_api` because the bar reader
didn't exist yet. Reconciles run against those days will continue to
log `actual_summary_source=vision` until this script patches them.

Method: navigate the chart to each missing date via Bar Replay (so
the bar buffer covers the RTH session), read OHLC numerically via
`bar_reader.read_session_ohlc`, write `actual_summary_api` into the
existing JSON. Never overwrites a profile that already has the field.

Usage:
    cd tradingview && .venv/bin/python -m tv_automation.backfill_api_summary
    cd tradingview && .venv/bin/python -m tv_automation.backfill_api_summary --symbol MNQ1 --since 2026-02-01
    cd tradingview && .venv/bin/python -m tv_automation.backfill_api_summary --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from . import bar_reader, replay, replay_api
from .lib import audit
from .lib.context import chart_session


_PROFILES_ROOT = (Path(__file__).parent.parent / "profiles").resolve()
_FILE_RX = re.compile(r"^([A-Z0-9]+)_(\d{4}-\d{2}-\d{2})\.json$")


def _list_candidates(symbol: str | None, since: str | None,
                     until: str | None) -> list[Path]:
    out = []
    for p in sorted(_PROFILES_ROOT.glob("*.json")):
        m = _FILE_RX.match(p.name)
        if not m:
            continue
        sym, date_str = m.group(1), m.group(2)
        if symbol and sym != symbol:
            continue
        if since and date_str < since:
            continue
        if until and date_str > until:
            continue
        out.append(p)
    return out


async def _backfill_one(page, profile_path: Path) -> dict:
    data = json.loads(profile_path.read_text())
    if data.get("actual_summary_api"):
        return {"path": str(profile_path), "skipped": "already_present"}

    m = _FILE_RX.match(profile_path.name)
    if not m:
        return {"path": str(profile_path), "skipped": "name_unparseable"}
    date_str = m.group(2)
    target_date = datetime.strptime(date_str, "%Y-%m-%d")

    # Navigate Bar Replay to 16:00 ET on the target date so the bar
    # buffer covers the full RTH session, then read OHLC. Self-healing
    # navigate_to handles broken Replay states + lands exactly on target
    # via the JS API.
    close_dt = target_date.replace(hour=16, minute=0)
    open_dt = target_date.replace(hour=9, minute=30)
    await replay.navigate_to(page, close_dt, tolerance_min=5)

    api_ohlc = await bar_reader.read_session_ohlc(
        page, start_et=open_dt, end_et=close_dt,
    )
    if api_ohlc is None or api_ohlc.get("bars_count", 0) == 0:
        return {"path": str(profile_path), "skipped": "no_bars_in_range",
                "ohlc": api_ohlc}

    data["actual_summary_api"] = api_ohlc
    profile_path.write_text(json.dumps(data, indent=2))
    audit.log("backfill_api_summary.patched",
              path=str(profile_path), date=date_str,
              bars=api_ohlc.get("bars_count"))
    return {"path": str(profile_path), "patched": True,
            "bars": api_ohlc.get("bars_count"),
            "open": api_ohlc.get("open"), "close": api_ohlc.get("close")}


async def backfill(*, symbol: str | None = None, since: str | None = None,
                   until: str | None = None, dry_run: bool = False,
                   ) -> list[dict]:
    paths = _list_candidates(symbol, since, until)
    if not paths:
        return []

    if dry_run:
        return [{"path": str(p), "would_process": True} for p in paths]

    results = []
    async with chart_session() as (_ctx, page):
        from . import layout_guard
        await layout_guard.ensure_layout(page)
        for p in paths:
            try:
                results.append(await _backfill_one(page, p))
            except Exception as e:
                results.append({"path": str(p),
                                "error": f"{type(e).__name__}: {e}"})
    return results


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.backfill_api_summary")
    p.add_argument("--symbol", default="MNQ1",
                   help="Symbol to backfill (default: MNQ1).")
    p.add_argument("--since", help="Earliest date YYYY-MM-DD (inclusive).")
    p.add_argument("--until", help="Latest date YYYY-MM-DD (inclusive).")
    p.add_argument("--dry-run", action="store_true",
                   help="List which profiles would be patched, don't write.")
    args = p.parse_args()

    results = asyncio.run(backfill(
        symbol=args.symbol, since=args.since, until=args.until,
        dry_run=args.dry_run,
    ))
    print(json.dumps(results, indent=2)[:5000])


if __name__ == "__main__":
    _main()
