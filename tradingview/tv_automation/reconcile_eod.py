"""End-of-day reconciliation: grade the day's unreconciled decisions
against real price bars.

For each decision made today that hasn't been tagged with an outcome:
  1. Fetch OHLCV bars from `decision.iso_ts` through end of reconcile
     window (usually `now`).
  2. Walk forward bar-by-bar. First-touch of stop → `hit_stop`; first-
     touch of TP → `hit_tp`; neither within window → `expired` with
     mark-to-market R on the final close.
  3. Update `decisions.db` via `decision_log.set_outcome`.

The heavy lifting sits in `tv_automation.bars.fetch_bars` (yfinance for
MNQ1! → MNQ=F continuous front-month). Same grading rules as the
replay bench (`replay_bench.grade_sample`), with a pessimistic tie-
break when a single bar tags both levels — it models "you don't know
intra-bar order; assume the worse side hit first."

Usage (CLI):
    .venv/bin/python -m tv_automation.reconcile_eod
    .venv/bin/python -m tv_automation.reconcile_eod --date 2026-04-19
    .venv/bin/python -m tv_automation.reconcile_eod --symbols MNQ1! NVDA
    .venv/bin/python -m tv_automation.reconcile_eod --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from datetime import datetime, date, time as dtime, timedelta
from typing import Any

from . import bars as bars_mod, decision_log
from .lib import audit


@dataclass
class Grade:
    request_id: str
    symbol: str
    signal: str
    entry: float | None
    stop: float | None
    tp: float | None
    outcome: str              # hit_tp | hit_stop | expired | skip | ungraded
    realized_r: float | None
    bars_walked: int
    error: str | None = None


def _r_multiple(entry: float, stop: float, tp: float) -> float | None:
    risk = abs(entry - stop)
    if risk == 0:
        return None
    return abs(tp - entry) / risk


def grade_against_bars(dec: dict, bars: list) -> Grade:
    """Pure function — given a decision row and a list of Bar objects
    starting AT OR AFTER the decision's analyze time, return the
    realized outcome by first-touch.

    Mirrors `replay_bench.grade_sample` rules:
      * hit_stop tie-breaks over hit_tp when a single bar tags both
      * expired → mark-to-market on last bar's close, expressed in R
      * missing levels OR no bars → `ungraded`
    """
    signal = dec.get("signal")
    if signal == "Skip":
        return Grade(
            request_id=dec["request_id"], symbol=dec.get("symbol") or "",
            signal="Skip", entry=None, stop=None, tp=None,
            outcome="skip", realized_r=0.0, bars_walked=0,
        )

    entry = dec.get("entry")
    stop = dec.get("stop")
    tp = dec.get("tp")
    if not all(isinstance(v, (int, float)) for v in (entry, stop, tp)):
        return Grade(
            request_id=dec["request_id"], symbol=dec.get("symbol") or "",
            signal=str(signal or ""), entry=entry, stop=stop, tp=tp,
            outcome="ungraded", realized_r=None, bars_walked=0,
            error="missing levels",
        )

    if not bars:
        return Grade(
            request_id=dec["request_id"], symbol=dec.get("symbol") or "",
            signal=str(signal), entry=entry, stop=stop, tp=tp,
            outcome="ungraded", realized_r=None, bars_walked=0,
            error="no bars in window",
        )

    r_mult = _r_multiple(entry, stop, tp) or 0.0
    last_close: float | None = None
    for i, bar in enumerate(bars, 1):
        last_close = bar.close
        if signal == "Long":
            hit_stop = bar.low <= stop
            hit_tp = bar.high >= tp
        else:  # Short
            hit_stop = bar.high >= stop
            hit_tp = bar.low <= tp

        if hit_stop:
            return Grade(
                request_id=dec["request_id"], symbol=dec["symbol"],
                signal=signal, entry=entry, stop=stop, tp=tp,
                outcome="hit_stop", realized_r=-1.0, bars_walked=i,
            )
        if hit_tp:
            return Grade(
                request_id=dec["request_id"], symbol=dec["symbol"],
                signal=signal, entry=entry, stop=stop, tp=tp,
                outcome="hit_tp", realized_r=round(r_mult, 4), bars_walked=i,
            )

    # No touch within the window. Mark-to-market on the last bar.
    pnl = (last_close - entry) if signal == "Long" else (entry - last_close)
    risk = abs(entry - stop)
    mtm_r = round(pnl / risk, 4) if risk else 0.0
    return Grade(
        request_id=dec["request_id"], symbol=dec["symbol"],
        signal=signal, entry=entry, stop=stop, tp=tp,
        outcome="expired", realized_r=mtm_r, bars_walked=len(bars),
    )


def _parse_iso(iso_ts: str) -> datetime:
    """Parse a `%Y-%m-%dT%H:%M:%S%z`-formatted timestamp. Fall back to
    naive if the tz chunk is missing (shouldn't happen in normal flow)."""
    try:
        return datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return datetime.strptime(iso_ts[:19], "%Y-%m-%dT%H:%M:%S")


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    """Midnight-to-midnight bounds (naive) for fetching the day's bars."""
    return (
        datetime.combine(d, dtime(0, 0, 0)),
        datetime.combine(d, dtime(23, 59, 59)),
    )


def reconcile_day(
    target: date | None = None,
    *,
    symbols: set[str] | None = None,
    tf: str = "5m",
    dry_run: bool = False,
) -> dict:
    """Grade all unreconciled decisions whose `iso_ts` falls on `target`
    (default today). Fetches one bar window per distinct symbol.

    `symbols` optionally filters to a subset.

    Returns a summary dict:
      {
        date, counts: {hit_tp, hit_stop, expired, skip, ungraded, total},
        win_rate, total_r, grades: [Grade...], dry_run
      }
    """
    target = target or datetime.now().date()

    # Unreconciled decisions from the target day. We pull a broad batch
    # and filter to the day client-side rather than teach decision_log
    # a new query — there aren't enough decisions for this to matter.
    all_unrec = decision_log.unreconciled(limit=10_000)
    todays: list[dict] = []
    for d in all_unrec:
        iso = d.get("iso_ts") or ""
        if not iso.startswith(target.isoformat()):
            continue
        if symbols and d.get("symbol") not in symbols:
            continue
        todays.append(d)

    audit.log(
        "reconcile_eod.start", target=target.isoformat(),
        n_candidates=len(todays), symbols=sorted(
            {d.get("symbol") for d in todays if d.get("symbol")}),
        dry_run=dry_run,
    )

    # Fetch bars once per symbol — covers the full day + a small
    # lookahead so trades placed near close still have bars forward.
    start, end = _day_bounds(target)
    end_with_buffer = end + timedelta(hours=2)
    bars_by_symbol: dict[str, list] = {}
    for sym in sorted({d.get("symbol") or "" for d in todays if d.get("symbol")}):
        try:
            bars = bars_mod.fetch_bars(sym, tf, start, end_with_buffer)
        except Exception as e:
            audit.log("reconcile_eod.bars_fetch_fail",
                      symbol=sym, error=f"{type(e).__name__}: {e}")
            bars = []
        bars_by_symbol[sym] = bars

    grades: list[Grade] = []
    counts = {"hit_tp": 0, "hit_stop": 0, "expired": 0,
              "skip": 0, "ungraded": 0, "total": len(todays)}
    total_r = 0.0

    for dec in todays:
        sym = dec.get("symbol") or ""
        # Slice bars strictly after the decision's analyze time — we
        # don't know what the T=0 bar did before the prediction.
        t0 = _parse_iso(dec.get("iso_ts") or "")
        # Normalize to naive UTC for comparison with Bar.ts (also naive UTC).
        if t0.tzinfo is not None:
            from datetime import timezone
            t0_naive = t0.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            t0_naive = t0
        window = [b for b in bars_by_symbol.get(sym, []) if b.ts > t0_naive]

        g = grade_against_bars(dec, window)
        grades.append(g)
        counts[g.outcome] = counts.get(g.outcome, 0) + 1
        if g.realized_r is not None and g.outcome not in ("ungraded", "skip"):
            total_r += g.realized_r

        if not dry_run and g.outcome != "ungraded":
            ok = decision_log.set_outcome(
                g.request_id, g.outcome, g.realized_r,
            )
            if not ok:
                audit.log("reconcile_eod.set_outcome_fail",
                          request_id=g.request_id)

    # Win rate = directional wins / closed directional trades.
    directional_closed = counts["hit_tp"] + counts["hit_stop"]
    win_rate = (counts["hit_tp"] / directional_closed
                if directional_closed else None)

    summary = {
        "date": target.isoformat(),
        "counts": counts,
        "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "total_r": round(total_r, 3),
        "grades": [
            {
                "request_id": g.request_id, "symbol": g.symbol,
                "signal": g.signal, "entry": g.entry, "stop": g.stop,
                "tp": g.tp, "outcome": g.outcome,
                "realized_r": g.realized_r, "bars_walked": g.bars_walked,
                "error": g.error,
            }
            for g in grades
        ],
        "dry_run": dry_run,
    }
    audit.log("reconcile_eod.done", target=target.isoformat(),
              counts=counts, win_rate=summary["win_rate"],
              total_r=summary["total_r"], dry_run=dry_run)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _format_summary(s: dict) -> str:
    lines = [
        f"Reconciliation summary — {s['date']}"
        + (" (DRY RUN)" if s.get("dry_run") else ""),
        "─" * 54,
        f"  Total decisions:   {s['counts']['total']}",
        f"  ├─ hit_tp:         {s['counts']['hit_tp']}",
        f"  ├─ hit_stop:       {s['counts']['hit_stop']}",
        f"  ├─ expired:        {s['counts']['expired']}",
        f"  ├─ skip:           {s['counts']['skip']}",
        f"  └─ ungraded:       {s['counts']['ungraded']}",
        "",
        f"  Win rate:          "
        + (f"{s['win_rate'] * 100:.1f}%" if s['win_rate'] is not None else "—"),
        f"  Total realized R:  {s['total_r']:+.2f}",
        "",
    ]
    if s["grades"]:
        lines.append("Per-decision:")
        for g in s["grades"]:
            r_str = (f"{g['realized_r']:+.2f}R"
                     if g["realized_r"] is not None else "—")
            err = f"  ({g['error']})" if g.get("error") else ""
            lines.append(
                f"  {g['request_id']:8s}  {g['symbol']:6s}  "
                f"{g['signal']:5s}  → {g['outcome']:9s}  {r_str}"
                f"  [{g['bars_walked']} bars]{err}"
            )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--date", type=_parse_date, default=None,
                    help="YYYY-MM-DD (default: today)")
    ap.add_argument("--symbols", nargs="+", default=None,
                    help="filter to these symbols (e.g. MNQ1! NVDA)")
    ap.add_argument("--tf", default="5m",
                    help="bar interval for grading (default 5m)")
    ap.add_argument("--dry-run", action="store_true",
                    help="grade but don't write outcomes to decisions.db")
    args = ap.parse_args()

    # Set a request_id for the whole reconciliation run so all
    # reconcile_eod.* audit events share a correlation id.
    audit.current_request_id.set(audit.new_request_id())

    summary = reconcile_day(
        target=args.date,
        symbols=set(args.symbols) if args.symbols else None,
        tf=args.tf, dry_run=args.dry_run,
    )
    print(_format_summary(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
