"""Replay-driven backtest harness.

Runs many Analyze samples against historical bars via TradingView's Bar
Replay, grades each prediction by walking the subsequent bars for
first-touch of stop vs TP, and writes the outcome via
`decision_log.set_outcome`. Designed to be resumable and safe to abort.

Design: REPLAY_BENCH_PLAN.md (next to this file). Don't read this file
in isolation — the plan explains the *why* for every choice here.

CLI:

    python -m tv_automation.replay_bench \\
      --symbol MNQ1! --tf 5m \\
      --start 2026-01-19 --end 2026-04-19 \\
      --step 4h --horizon 40 \\
      --provider claude_web --model sonnet

Flags:
    --rth-only (default) / --all-hours  — whether T₀s are confined to
                                          CME RTH 09:30-16:15 ET
    --force              override RTH-now guard (useful overnight; this
                         harness refuses to run during market hours so
                         the user's live chart isn't contended)
    --dry-run            plan the T₀ sequence but skip analyze + grading
                         (useful for smoke-testing replay.py)
    --resume RUN_ID      reuse an existing run_id's checkpoint and skip
                         T₀s whose request_id is already graded in
                         `decisions.db`
    --run-id RUN_ID      override the auto-generated run_id

Outputs:
    decisions.db                       one row per sample (via analyze_chart)
                                       + outcome tagged here.
    benchmarks/replay_bench_<run>.jsonl  per-sample checkpoint.
    audit/YYYY-MM-DD.jsonl             replay_bench.* events for UI tail.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any

from preflight import ensure_automation_chromium
from session import tv_context

from . import analyze_mtf, bars as bars_mod, chart, decision_log, replay
from .chart import _find_or_open_chart
from .lib import audit

# Parent dir: tradingview/
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = _PACKAGE_ROOT / "benchmarks"

# CME RTH for NQ futures (and MNQ1!): 09:30-16:15 ET. We key off America/
# New_York wall-clock because DST flips are important and using UTC here
# would mis-window samples twice a year.
_NY_TZ = None
try:
    from zoneinfo import ZoneInfo
    _NY_TZ = ZoneInfo("America/New_York")
except Exception:
    # Python 3.12 has zoneinfo, but if the tzdata package isn't available
    # the harness falls back to local time. Not ideal but not fatal.
    pass

RTH_OPEN = dtime(9, 30)
RTH_CLOSE = dtime(16, 15)

# Friendly timeframe → seconds per bar. Keep aligned with
# `chart._TIMEFRAME_MAP`. Used for client-side cursor tracking when TV's
# "Select date" button text can't be parsed (UNKNOWN #6).
_TF_SECONDS = {
    "30s": 30, "45s": 45,
    "1m": 60, "2m": 120, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400,
    "1D": 86400, "1W": 86400 * 7,
}


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class SampleSpec:
    """One sample's inputs. Stored in the checkpoint so resume can skip
    already-completed ones."""
    t0_iso: str
    symbol: str
    tf: str


@dataclass
class SampleResult:
    """One sample's output. Appended to the checkpoint jsonl regardless
    of success — a failed sample still counts as "attempted" for resume
    so we don't retry forever."""
    t0_iso: str
    request_id: str | None
    signal: str | None
    confidence: int | None
    outcome: str | None       # "hit_tp" | "hit_stop" | "expired" | "skip" | "ungraded" | "fail"
    realized_r: float | None
    error: str | None
    elapsed_s: float
    graded_bars: int          # how many bars we successfully read before deciding


# ---------------------------------------------------------------------------
# Time / window math
# ---------------------------------------------------------------------------


def _ny_now() -> datetime:
    if _NY_TZ is None:
        return datetime.now()
    return datetime.now(_NY_TZ)


def _inside_rth(ts: datetime) -> bool:
    """True if `ts` (in ET) is within CME RTH on a weekday."""
    if ts.weekday() >= 5:
        return False
    t = ts.time()
    return RTH_OPEN <= t <= RTH_CLOSE


def _parse_step(step: str) -> timedelta:
    """'4h' → 4 hours. '30m' → 30 min. Supports h/m/s/d suffix."""
    s = step.strip().lower()
    if not s or not s[-1] in "smhd":
        raise ValueError(f"unrecognized step {step!r}; use e.g. 4h, 30m, 1d")
    n = int(s[:-1])
    unit = s[-1]
    return {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]


def _parse_date(s: str) -> datetime:
    """Accept YYYY-MM-DD or YYYY-MM-DD HH:MM, interpret as NY-local."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=_NY_TZ) if _NY_TZ else dt
        except ValueError:
            continue
    raise ValueError(f"unparseable date {s!r}; use YYYY-MM-DD or YYYY-MM-DD HH:MM")


def generate_samples(start: datetime, end: datetime, step: timedelta,
                     *, rth_only: bool, symbol: str, tf: str,
                     ) -> list[SampleSpec]:
    """Generate T₀ timestamps walking [start, end] by step.
    RTH-only drops weekends and times outside 09:30–16:15 ET."""
    out: list[SampleSpec] = []
    cur = start
    while cur <= end:
        if not rth_only or _inside_rth(cur):
            out.append(SampleSpec(t0_iso=cur.isoformat(), symbol=symbol, tf=tf))
        cur = cur + step
    return out


# ---------------------------------------------------------------------------
# Grading — now data-source-agnostic. Takes a pre-fetched list of bars
# (from `bars.fetch_bars`) instead of scraping TV's DOM. See
# REPLAY_BENCH_PLAN.md UNKNOWN #1: we picked option (c) after option
# (a)'s legend-scrape approach proved too fragile in Replay context.
# ---------------------------------------------------------------------------


def _r_multiple(entry: float, stop: float, tp: float, signal: str) -> float:
    """TP distance in R-multiples of the stop distance."""
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    reward = abs(tp - entry)
    return (reward / risk) if signal == "Long" or signal == "Short" else 0.0


def grade_sample(bars: list["bars_mod.Bar"], result: dict, horizon: int,
                 ) -> tuple[str, float | None, int]:
    """First-touch grading against pre-fetched bars.

    `bars` must be the `horizon` bars strictly after T₀ (use
    `bars_mod.slice_forward(all_bars, t0, horizon)` to produce this).

    Outcomes:
      'hit_tp'   — TP touched first → realized_r = +R
      'hit_stop' — stop touched first → realized_r = -1.0
      'expired'  — neither touched within horizon → mark-to-market at
                   the final bar's close
      'skip'     — analyze signal was Skip → realized_r = 0.0
      'ungraded' — not enough bars available for grading (Yahoo window
                   edge, weekend gap, etc.)
    """
    signal = result.get("signal")
    if signal == "Skip":
        return "skip", 0.0, 0

    entry = result.get("entry")
    stop = result.get("stop")
    tp = result.get("tp")
    if not all(isinstance(v, (int, float)) for v in (entry, stop, tp)):
        return "ungraded", None, 0
    if not bars:
        return "ungraded", None, 0

    r = _r_multiple(entry, stop, tp, signal)
    used = min(len(bars), horizon)

    for i, bar in enumerate(bars[:horizon], 1):
        if signal == "Long":
            hit_stop = bar.low <= stop
            hit_tp = bar.high >= tp
        else:  # Short
            hit_stop = bar.high >= stop
            hit_tp = bar.low <= tp

        # Pessimistic tie-break: if a single bar tags BOTH levels, assume
        # the stop was hit first. Real markets don't guarantee order
        # within a bar — conservative grading matches how a trader would
        # actually experience a same-bar both-touched outcome.
        if hit_stop:
            return "hit_stop", -1.0, i
        if hit_tp:
            return "hit_tp", r, i

    # No touch within the fetched horizon. Mark-to-market on the last
    # bar's close.
    last = bars[used - 1]
    pnl = (last.close - entry) if signal == "Long" else (entry - last.close)
    risk = abs(entry - stop)
    mtm_r = (pnl / risk) if risk else 0.0
    return "expired", round(mtm_r, 4), used


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------


def checkpoint_path(run_id: str) -> Path:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    return BENCH_DIR / f"replay_bench_{run_id}.jsonl"


def load_completed_t0s(run_id: str) -> set[str]:
    """Load T₀s from the checkpoint that already produced a non-fail
    result. Combined with `decisions.db` check, this is what `--resume`
    uses to skip completed work."""
    path = checkpoint_path(run_id)
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("outcome") and rec["outcome"] not in ("fail", "ungraded"):
                done.add(rec["t0_iso"])
    return done


def append_checkpoint(run_id: str, res: SampleResult) -> None:
    path = checkpoint_path(run_id)
    with path.open("a") as f:
        f.write(json.dumps(asdict(res), default=str) + "\n")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run_bench(
    *, symbol: str, tf: str, start: datetime, end: datetime,
    step: timedelta, horizon: int, provider: str, model: str | None,
    rth_only: bool, dry_run: bool, run_id: str, skip_t0s: set[str],
) -> dict:
    await ensure_automation_chromium()

    specs = generate_samples(
        start, end, step,
        rth_only=rth_only, symbol=symbol, tf=tf,
    )
    total = len(specs)
    audit.log("replay_bench.run_start", run_id=run_id, total=total,
              symbol=symbol, tf=tf, provider=provider, model=model,
              dry_run=dry_run, rth_only=rth_only, horizon=horizon)

    # Pre-fetch all bars covering the run's window + grading horizon.
    # Single yfinance call for the whole run — massively cheaper than
    # per-sample fetches. Buffer the end by horizon * bar_seconds so
    # late-window samples have enough forward bars.
    all_bars: list[bars_mod.Bar] = []
    if not dry_run:
        tf_sec = _TF_SECONDS[tf]
        end_with_buffer = end + timedelta(seconds=tf_sec * horizon + 3600)
        try:
            all_bars = bars_mod.fetch_bars(symbol, tf, start, end_with_buffer)
        except Exception as e:
            audit.log("replay_bench.bars_fetch_fail",
                      error=f"{type(e).__name__}: {e}")
        audit.log("replay_bench.bars_fetched",
                  symbol=symbol, tf=tf, count=len(all_bars),
                  first_ts=str(all_bars[0].ts) if all_bars else None,
                  last_ts=str(all_bars[-1].ts) if all_bars else None)
        if not all_bars:
            audit.log("replay_bench.run_done",
                      run_id=run_id, error="no_bars",
                      ok=0, skip=0, fail=0, resumed=0, ungraded=0)
            return {"run_id": run_id, "total": total, "error": "no_bars",
                    "ok": 0, "skip": 0, "fail": 0,
                    "resumed": 0, "ungraded": 0,
                    "checkpoint": str(checkpoint_path(run_id))}

    # Open the page and save the pre-run chart state so we can restore
    # it even if the loop crashes mid-sample.
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        was_in_replay = await replay.is_active(page)

        counts = {"ok": 0, "skip": 0, "fail": 0, "resumed": 0, "ungraded": 0}
        try:
            for i, spec in enumerate(specs, 1):
                if spec.t0_iso in skip_t0s:
                    counts["resumed"] += 1
                    audit.log("replay_bench.sample_resume", t0=spec.t0_iso,
                              i=i, total=total)
                    continue

                # Fresh request_id per sample so decision_log.log_decision
                # (called inside analyze_chart) uses it, and we can tag
                # set_outcome against the same id later in the same loop iter.
                req_id = audit.new_request_id()
                token = audit.current_request_id.set(req_id)
                t_start = time.time()
                try:
                    res = await _run_one_sample(
                        page, spec, horizon=horizon,
                        provider=provider, model=model,
                        dry_run=dry_run, request_id=req_id,
                        all_bars=all_bars,
                    )
                except Exception as e:
                    elapsed = round(time.time() - t_start, 2)
                    res = SampleResult(
                        t0_iso=spec.t0_iso, request_id=req_id,
                        signal=None, confidence=None,
                        outcome="fail", realized_r=None,
                        error=f"{type(e).__name__}: {e}",
                        elapsed_s=elapsed, graded_bars=0,
                    )
                    audit.log("replay_bench.sample_fail",
                              t0=spec.t0_iso, error=res.error)
                finally:
                    audit.current_request_id.reset(token)

                append_checkpoint(run_id, res)
                if res.outcome == "fail":
                    counts["fail"] += 1
                elif res.outcome == "skip":
                    counts["skip"] += 1
                elif res.outcome == "ungraded":
                    counts["ungraded"] += 1
                else:
                    counts["ok"] += 1

                audit.log(
                    "replay_bench.sample_done",
                    i=i, total=total, t0=spec.t0_iso,
                    outcome=res.outcome, realized_r=res.realized_r,
                    signal=res.signal, confidence=res.confidence,
                    elapsed_s=res.elapsed_s, request_id=req_id,
                )
                # Light terminal progress — helps when running without
                # a UI tail in view.
                print(
                    f"[{i}/{total}] {spec.t0_iso} "
                    f"{(res.signal or '·'):5s} "
                    f"conf={res.confidence if res.confidence is not None else '—':>3} "
                    f"→ {res.outcome} "
                    f"R={res.realized_r if res.realized_r is not None else '—'} "
                    f"({res.elapsed_s}s)",
                    flush=True,
                )
        finally:
            # Best-effort restore. Don't raise out of the finally block.
            try:
                if not was_in_replay and await replay.is_active(page):
                    await replay.exit_replay(page)
            except Exception as e:
                audit.log("replay_bench.restore_fail",
                          error=f"{type(e).__name__}: {e}")

    audit.log("replay_bench.run_done", run_id=run_id, **counts)
    return {"run_id": run_id, "total": total, **counts,
            "checkpoint": str(checkpoint_path(run_id))}


async def _run_one_sample(
    page, spec: SampleSpec, *, horizon: int, provider: str,
    model: str | None, dry_run: bool, request_id: str,
    all_bars: list["bars_mod.Bar"],
) -> SampleResult:
    """Single-sample body: navigate chart, activate replay, pick T₀,
    analyze, grade against external bars, tag outcome."""
    t_start = time.time()

    # Ensure chart is on the right symbol/tf. Cheap when already correct
    # (URL-param-driven).
    await chart._navigate(page, spec.symbol, chart.resolve_timeframe(spec.tf))

    await replay.enter_replay(page)
    try:
        t0_dt = datetime.fromisoformat(spec.t0_iso)
    except ValueError:
        t0_dt = datetime.strptime(spec.t0_iso[:19], "%Y-%m-%dT%H:%M:%S")
    await replay.select_start_date(page, t0_dt)

    if dry_run:
        return SampleResult(
            t0_iso=spec.t0_iso, request_id=request_id,
            signal="DRY", confidence=None, outcome="skip",
            realized_r=None, error=None,
            elapsed_s=round(time.time() - t_start, 2), graded_bars=0,
        )

    result = await analyze_mtf.analyze_chart(
        spec.symbol, timeframe=spec.tf,
        provider=provider, model=model,
    )

    # Grade against external bars — no more stepping through TV.
    forward = bars_mod.slice_forward(all_bars, t0_dt, horizon)
    outcome, realized_r, graded_bars = grade_sample(forward, result, horizon)

    # `log_decision` was called inside `analyze_chart`. Tag the outcome.
    decision_log.set_outcome(request_id, outcome, realized_r)

    audit.log("replay_bench.graded",
              t0=spec.t0_iso,
              bars_available=len(forward),
              outcome=outcome, realized_r=realized_r)

    return SampleResult(
        t0_iso=spec.t0_iso, request_id=request_id,
        signal=result.get("signal"),
        confidence=result.get("confidence"),
        outcome=outcome, realized_r=realized_r,
        error=None,
        elapsed_s=round(time.time() - t_start, 2),
        graded_bars=graded_bars,
    )


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--symbol", default="MNQ1!")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD [HH:MM]")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD [HH:MM]")
    ap.add_argument("--step", default="4h", help="e.g. 4h, 30m, 1d")
    ap.add_argument("--horizon", type=int, default=40,
                    help="bars to walk forward when grading (default 40)")
    ap.add_argument("--provider", default="claude_web",
                    choices=["claude_web", "ollama", "anthropic", "chatgpt_web"])
    ap.add_argument("--model", default="sonnet")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--rth-only", action="store_true", default=True,
                     help="(default) sample only 09:30–16:15 ET, Mon–Fri")
    grp.add_argument("--all-hours", dest="rth_only", action="store_false",
                     help="sample overnight/weekend too (~4× more T₀s)")
    ap.add_argument("--force", action="store_true",
                    help="ignore the RTH-now guard (run during market hours)")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan T₀ sequence but skip analyze + grading")
    ap.add_argument("--resume",
                    help="RUN_ID to resume; skips already-graded T₀s")
    ap.add_argument("--run-id", help="override generated run_id")
    args = ap.parse_args()

    # RTH-now guard. The chart is shared with the user's live session —
    # a bench run during RTH would contend with whatever they're doing.
    if not args.force:
        now_ny = _ny_now()
        if _inside_rth(now_ny):
            print(
                f"ERROR: it is {now_ny.strftime('%H:%M %Z')} (CME RTH). "
                "Refusing to run — the chart is shared with your live "
                "session. Pass --force to override.",
                file=sys.stderr,
            )
            return 2

    # Validate tf — must be one we know the bar duration for.
    if args.tf not in _TF_SECONDS:
        print(f"ERROR: unknown tf {args.tf!r}; known: {sorted(_TF_SECONDS)}",
              file=sys.stderr)
        return 2

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if end < start:
        print("ERROR: --end is before --start", file=sys.stderr)
        return 2
    step = _parse_step(args.step)

    run_id = args.resume or args.run_id or f"replay-{time.strftime('%Y%m%d-%H%M%S')}"
    skip_t0s: set[str] = set()
    if args.resume:
        skip_t0s = load_completed_t0s(args.resume)
        # Also join against decisions.db to skip T₀s whose request_id
        # already has a non-null outcome.
        skip_t0s |= _graded_t0s_from_db(run_id=args.resume)
        print(f"Resuming run {args.resume} — {len(skip_t0s)} T₀s to skip",
              flush=True)

    # Set up a run-scoped request_id too, so the "replay_bench.run_*"
    # events share a correlation id distinct from per-sample ids.
    audit.current_request_id.set(audit.new_request_id())

    result = asyncio.run(run_bench(
        symbol=args.symbol, tf=args.tf, start=start, end=end, step=step,
        horizon=args.horizon, provider=args.provider, model=args.model,
        rth_only=args.rth_only, dry_run=args.dry_run,
        run_id=run_id, skip_t0s=skip_t0s,
    ))

    print(json.dumps(result, indent=2, default=str))
    return 0


def _graded_t0s_from_db(run_id: str) -> set[str]:
    """Read the checkpoint for `run_id` and for each entry whose
    request_id is already tagged with a non-null outcome in
    decisions.db, add that T₀ to the skip set.

    Defense-in-depth: the checkpoint might say "ok" but the row could
    have been cleared. DB is authoritative for "already graded."
    """
    path = checkpoint_path(run_id)
    if not path.exists():
        return set()
    req_ids: dict[str, str] = {}
    with path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rid = rec.get("request_id")
            t0 = rec.get("t0_iso")
            if rid and t0:
                req_ids[rid] = t0
    if not req_ids:
        return set()
    # Query decisions.db in one pass.
    import sqlite3
    try:
        con = sqlite3.connect(decision_log.DB_PATH)
        con.row_factory = sqlite3.Row
        placeholders = ",".join(["?"] * len(req_ids))
        rows = con.execute(
            f"SELECT request_id FROM decisions "
            f"WHERE outcome IS NOT NULL AND request_id IN ({placeholders})",
            list(req_ids.keys()),
        ).fetchall()
        con.close()
    except Exception:
        return set()
    return {req_ids[r["request_id"]] for r in rows if r["request_id"] in req_ids}


if __name__ == "__main__":
    sys.exit(main())
