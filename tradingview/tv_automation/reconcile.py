"""Outcome reconciler — interactive CLI to tag trade outcomes.

Phase 1 Step 2 of the calibration roadmap. Walks through unreconciled
decisions oldest-first and prompts the user for how each one played
out. Writes outcome + realized_r back to the decisions table so the
calibration summary can join against it.

Why human-in-the-loop for V1:
  * Auto-reconciling from TV's trade history is non-trivial (DOM
    scraping, session re-use, edge cases like partial fills and
    manual closes). That's a separate project.
  * Auto-reconciling from forward price action (did price touch TP
    before stop?) requires bar-level OHLC data that TV doesn't expose
    as a clean API from the CDP-attached browser.
  * A tagger UI is the right fallback for those edge cases anyway —
    auto-reconciliation should layer on top, not replace it.
  * Trading decisions you care about are the ones you remember. If
    you can't remember the outcome of a trade you placed yesterday,
    it probably wasn't significant — and bulk-tagging it as `expired`
    or `no_fill` is honest.

Outcome taxonomy:
  * `hit_tp`       — trade placed, price reached TP. realized_r = R:R.
  * `hit_stop`     — trade placed, price reached stop. realized_r = -1.
  * `manual_close` — trade placed, closed before stop/TP. user-entered R.
  * `expired`      — trade placed, no stop/TP in window. realized_r = 0.
  * `no_fill`      — signal was actionable, no trade placed. r = 0.
  * `skip_right`   — signal was Skip, and skipping was correct. r = 0.
  * `skip_wrong`   — signal was Skip but a trade would've worked.
                     user-entered opportunity cost R (positive = missed).

Usage:
    cd tradingview && .venv/bin/python -m tv_automation.reconcile
    cd tradingview && .venv/bin/python -m tv_automation.reconcile --limit 5
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Callable

from . import decision_log


# ---------------------------------------------------------------------------
# Outcome computation — keeps realized_r math in one place so the CLI
# prompts and any future auto-reconciler compute the same numbers.
# ---------------------------------------------------------------------------


def _rr_from_levels(signal: str | None, entry, stop, tp) -> float | None:
    """R:R for a directional trade. Mirrors the JS fmt in app.js."""
    try:
        e, s, t = float(entry), float(stop), float(tp)
        if signal == "Long" and e > s:
            return (t - e) / (e - s)
        if signal == "Short" and s > e:
            return (e - t) / (s - e)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None


def _auto_realized_r(outcome: str, signal: str | None,
                     entry, stop, tp) -> float | None:
    """Realized R-multiple given a deterministic outcome, or None if
    the outcome requires a user-entered number (manual_close,
    skip_wrong)."""
    if outcome == "hit_tp":
        return _rr_from_levels(signal, entry, stop, tp)
    if outcome == "hit_stop":
        return -1.0
    if outcome in ("expired", "no_fill", "skip_right"):
        return 0.0
    # manual_close, skip_wrong require user input — return None so the
    # CLI knows to prompt.
    return None


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def _fmt_decision(d: dict) -> str:
    sig = d.get("signal") or "—"
    conf = d.get("confidence")
    tf = d.get("optimal_tf") or d.get("tf") or "?"
    mode_tag = "[deep]" if d.get("mode") == "deep" else ""
    levels = ""
    if d.get("entry") is not None:
        rr = _rr_from_levels(sig, d.get("entry"), d.get("stop"), d.get("tp"))
        rr_s = f"R:R {rr:.2f}:1" if rr is not None else ""
        levels = (f"  E {d['entry']:.2f} / S {d['stop']:.2f} / "
                  f"T {d['tp']:.2f}  {rr_s}")
    rationale = (d.get("rationale") or "").strip().replace("\n", " ")
    if len(rationale) > 200:
        rationale = rationale[:200] + "…"
    return (
        f"[{d['iso_ts'][:19]}]  {d['symbol']:<8} {tf:<4} {mode_tag} "
        f"{sig:<5} @ {conf}%   {d['provider']}/{d['model']}\n"
        f"{levels}\n"
        f"  rationale: {rationale}"
    )


# ---------------------------------------------------------------------------
# Interactive prompt
# ---------------------------------------------------------------------------


def _prompt_outcome(d: dict, input_fn: Callable[[str], str] = input
                    ) -> tuple[str | None, float | None]:
    """Display the decision, ask how it resolved. Returns
    (outcome, realized_r) or (None, None) to skip / quit.

    `input_fn` is injectable for testing."""
    signal = d.get("signal")
    rr = _rr_from_levels(signal, d.get("entry"), d.get("stop"), d.get("tp"))

    # Menu varies by whether this was a directional signal or a Skip.
    # Offering hit_tp/hit_stop for a Skip decision is nonsense, and
    # offering skip_right/skip_wrong for a Long is equally nonsense.
    print()
    print(_fmt_decision(d))
    print()
    if signal in ("Long", "Short"):
        rr_hint = f"+{rr:.2f}R" if rr else "+R"
        print(f"  [t] Hit TP        ({rr_hint})")
        print(f"  [s] Hit stop      (-1.00R)")
        print(f"  [m] Manual close  (you enter R)")
        print(f"  [e] Expired       (no stop/TP touched)")
        print(f"  [n] No fill       (signal not acted on)")
    else:  # Skip
        print(f"  [r] Skip right    (market didn't offer a trade; 0R)")
        print(f"  [w] Skip wrong    (a trade would've worked; you enter R)")
    print(f"  [?] Skip this decision (decide later)")
    print(f"  [q] Quit")
    choice = input_fn("> ").strip().lower()

    if choice == "q":
        return None, None  # caller treats as quit
    if choice in ("", "?"):
        return "_skip_", None  # sentinel: skip this decision

    if signal in ("Long", "Short"):
        if choice == "t":
            return "hit_tp", _auto_realized_r("hit_tp", signal,
                                              d.get("entry"), d.get("stop"),
                                              d.get("tp"))
        if choice == "s":
            return "hit_stop", -1.0
        if choice == "m":
            r = _parse_r_input(input_fn)
            if r is None:
                return "_skip_", None
            return "manual_close", r
        if choice == "e":
            return "expired", 0.0
        if choice == "n":
            return "no_fill", 0.0
    else:
        if choice == "r":
            return "skip_right", 0.0
        if choice == "w":
            r = _parse_r_input(input_fn,
                               prompt="Missed opportunity in R (positive): ")
            if r is None:
                return "_skip_", None
            return "skip_wrong", r

    print(f"  (unrecognized: {choice!r} — skipping)")
    return "_skip_", None


def _parse_r_input(input_fn: Callable[[str], str],
                   prompt: str = "Realized R (e.g. 1.5 or -0.3): "
                   ) -> float | None:
    raw = input_fn(prompt).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print(f"  (not a number: {raw!r})")
        return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def reconcile_interactive(limit: int = 20) -> int:
    """Walk through unreconciled decisions, prompt for outcome, save.
    Returns exit code — 0 on clean exit, 130 on Ctrl-C like the shell."""
    todo = decision_log.unreconciled(limit=limit)
    if not todo:
        print("No unreconciled decisions.")
        return 0

    total = len(todo)
    print(f"Reconciling {total} decision(s), oldest first.")
    print(f"({decision_log.count()} total in log, "
          f"{total} unreconciled.)")

    reconciled = 0
    try:
        for i, d in enumerate(todo, 1):
            print(f"\n━━━ [{i}/{total}] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            outcome, r = _prompt_outcome(d)
            if outcome is None:
                print("\nQuitting.")
                break
            if outcome == "_skip_":
                print("  (skipped)")
                continue
            ok = decision_log.set_outcome(
                d["request_id"], outcome, r, closed_at=time.time(),
            )
            if ok:
                reconciled += 1
                r_str = f" (R = {r:+.2f})" if r is not None else ""
                print(f"  ✓ tagged: {outcome}{r_str}")
            else:
                print(f"  ✗ update failed — request_id not found")
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        print(f"Reconciled {reconciled} this session.")
        return 130

    print(f"\nDone. Reconciled {reconciled}/{total} this session.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=20,
                    help="max decisions to walk (default 20)")
    args = ap.parse_args()
    return reconcile_interactive(limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
