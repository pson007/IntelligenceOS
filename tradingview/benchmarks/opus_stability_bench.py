"""Multi-run stability bench for Opus 4.7 to validate the ⭐ co-default.

Single-point bench can't tell signal-stability from luck. This runs Opus
N times on single-TF and N' times on deep against a freshly captured
chart set, then reports:

  - latency: median + range
  - signal stability: do calls flip Long↔Skip across runs?
  - price drift: how much do entry/stop/tp move across runs?
  - per_tf agreement on deep

Consumes ~5 quota messages from claude.ai subscription.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tv_automation import analyze_mtf, chart  # noqa: E402

SYMBOL = "MNQ1!"
SINGLE_TF = "5m"
SINGLE_RUNS = 3
DEEP_RUNS = 2
MODEL = "Opus 4.7"


def _rr(signal, entry, stop, tp) -> float | None:
    try:
        e, s, t = float(entry), float(stop), float(tp)
        if signal == "Long" and e > s:
            return (t - e) / (e - s)
        if signal == "Short" and s > e:
            return (e - t) / (s - e)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None


async def _single_run(cap: dict) -> dict:
    t0 = time.time()
    raw, _, _ = await analyze_mtf._call_claude_web(cap, SYMBOL, SINGLE_TF, MODEL)
    elapsed = time.time() - t0
    try:
        p = analyze_mtf._parse_json(raw)
        return {
            "elapsed_s": round(elapsed, 1),
            "ok": True,
            "signal": p.get("signal"),
            "confidence": p.get("confidence"),
            "entry": p.get("entry"),
            "stop": p.get("stop"),
            "tp": p.get("tp"),
            "rr": _rr(p.get("signal"), p.get("entry"), p.get("stop"), p.get("tp")),
        }
    except Exception as e:
        return {"elapsed_s": round(elapsed, 1), "ok": False, "error": str(e)[:100]}


async def _deep_run(captures: list[dict], tfs: list[str]) -> dict:
    t0 = time.time()
    raw, _, _ = await analyze_mtf._call_claude_web_deep(captures, SYMBOL, tfs, MODEL)
    elapsed = time.time() - t0
    try:
        p = analyze_mtf._parse_json(raw)
        return {
            "elapsed_s": round(elapsed, 1),
            "ok": True,
            "optimal_tf": p.get("optimal_tf"),
            "signal": p.get("signal"),
            "confidence": p.get("confidence"),
            "entry": p.get("entry"),
            "stop": p.get("stop"),
            "tp": p.get("tp"),
            "rr": _rr(p.get("signal"), p.get("entry"), p.get("stop"), p.get("tp")),
        }
    except Exception as e:
        return {"elapsed_s": round(elapsed, 1), "ok": False, "error": str(e)[:100]}


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "median": round(statistics.median(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "spread": round(max(vals) - min(vals), 2),
    }


def _drift(values: list[float | None]) -> dict | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(nums) < 2:
        return None
    return {"min": min(nums), "max": max(nums), "range": round(max(nums) - min(nums), 2)}


async def main() -> None:
    print(f"Capturing {SYMBOL} {SINGLE_TF} for single-TF runs...", flush=True)
    shot = await chart.screenshot(SYMBOL, SINGLE_TF, None, area="chart")
    cap = {"tf": SINGLE_TF, "path": shot["path"]}
    print(f"  → {Path(shot['path']).name}\n", flush=True)

    print(f"=== Single-TF: {MODEL} × {SINGLE_RUNS} on same screenshot ===", flush=True)
    single_results = []
    for i in range(1, SINGLE_RUNS + 1):
        print(f"[{i}/{SINGLE_RUNS}] running...", flush=True)
        r = await _single_run(cap)
        single_results.append(r)
        if r["ok"]:
            rr = f"{r['rr']:.2f}" if r["rr"] is not None else "—"
            print(f"    {r['elapsed_s']:>5}s  {r['signal']:<5}  conf={r['confidence']}  "
                  f"entry={r['entry']}  stop={r['stop']}  tp={r['tp']}  R:R={rr}", flush=True)
        else:
            print(f"    {r['elapsed_s']:>5}s  ERROR: {r['error']}", flush=True)

    print(f"\nCapturing {len(analyze_mtf.DEFAULT_DEEP_TIMEFRAMES)} TFs for deep runs...", flush=True)
    tfs = analyze_mtf.DEFAULT_DEEP_TIMEFRAMES
    captures = []
    cap_t0 = time.time()
    for tf in tfs:
        s = await chart.screenshot(SYMBOL, tf, None, area="chart")
        captures.append({"tf": tf, "path": s["path"]})
    print(f"  capture wall: {time.time() - cap_t0:.1f}s\n", flush=True)

    print(f"=== Deep: {MODEL} × {DEEP_RUNS} on same capture set ===", flush=True)
    deep_results = []
    for i in range(1, DEEP_RUNS + 1):
        print(f"[{i}/{DEEP_RUNS}] running...", flush=True)
        r = await _deep_run(captures, tfs)
        deep_results.append(r)
        if r["ok"]:
            rr = f"{r['rr']:.2f}" if r["rr"] is not None else "—"
            print(f"    {r['elapsed_s']:>5}s  opt={r['optimal_tf']}  {r['signal']:<5}  "
                  f"conf={r['confidence']}  entry={r['entry']}  stop={r['stop']}  "
                  f"tp={r['tp']}  R:R={rr}", flush=True)
        else:
            print(f"    {r['elapsed_s']:>5}s  ERROR: {r['error']}", flush=True)

    # Aggregate.
    print("\n" + "=" * 80)
    print("AGGREGATE")
    print("=" * 80)

    s_ok = [r for r in single_results if r["ok"]]
    print(f"\nSingle-TF latency (n={len(s_ok)}): {_stats([r['elapsed_s'] for r in s_ok])}")
    s_signals = [r["signal"] for r in s_ok]
    print(f"  Signals: {s_signals} {'STABLE' if len(set(s_signals)) == 1 else 'FLIPPING ⚠'}")
    print(f"  Confidence: {[r['confidence'] for r in s_ok]}")
    print(f"  Entry drift: {_drift([r['entry'] for r in s_ok])}")
    print(f"  Stop drift:  {_drift([r['stop'] for r in s_ok])}")
    print(f"  TP drift:    {_drift([r['tp'] for r in s_ok])}")
    print(f"  R:R range:   {_drift([r['rr'] for r in s_ok])}")

    d_ok = [r for r in deep_results if r["ok"]]
    print(f"\nDeep latency (n={len(d_ok)}): {_stats([r['elapsed_s'] for r in d_ok])}")
    d_signals = [r["signal"] for r in d_ok]
    print(f"  Signals: {d_signals} {'STABLE' if len(set(d_signals)) == 1 else 'FLIPPING ⚠'}")
    d_opts = [r["optimal_tf"] for r in d_ok]
    print(f"  Optimal TF: {d_opts} {'STABLE' if len(set(d_opts)) == 1 else 'DRIFTING ⚠'}")
    print(f"  Entry drift: {_drift([r['entry'] for r in d_ok])}")
    print(f"  Stop drift:  {_drift([r['stop'] for r in d_ok])}")
    print(f"  TP drift:    {_drift([r['tp'] for r in d_ok])}")

    out = Path(__file__).parent / "opus_stability_results.json"
    out.write_text(json.dumps({
        "symbol": SYMBOL,
        "single_tf": SINGLE_TF,
        "single_runs": single_results,
        "deep_runs": deep_results,
    }, indent=2))
    print(f"\nFull dump → {out}")


if __name__ == "__main__":
    asyncio.run(main())
