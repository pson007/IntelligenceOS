"""Live deep (multi-TF) bench across all installed providers + models.

Captures all DEFAULT_DEEP_TIMEFRAMES once, then feeds the same set
through each (provider, model) combo via the _call_*_deep paths so
latency + signal quality are directly comparable. Claude-browser runs
consume real messages from the user's subscription (~5 total) — run
once per decision session, not in a loop.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tv_automation import analyze_mtf, chart  # noqa: E402

SYMBOL = "MNQ1!"
TFS = analyze_mtf.DEFAULT_DEEP_TIMEFRAMES

COMBOS: list[tuple[str, str]] = [
    ("ollama",     "gemma4:31b"),
    ("ollama",     "gemma4:26b"),
    ("claude_web", "Haiku 4.5"),
    ("claude_web", "Sonnet 4.6"),
    ("claude_web", "Opus 4.7"),
]


def _rr(signal: str | None, entry, stop, tp) -> str:
    try:
        e, s, t = float(entry), float(stop), float(tp)
        if signal == "Long" and e > s:
            return f"{(t - e) / (e - s):.2f}:1"
        if signal == "Short" and s > e:
            return f"{(e - t) / (s - e):.2f}:1"
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return "—"


async def _run_one(provider: str, model: str, captures: list[dict]) -> dict:
    t0 = time.time()
    raw = ""
    try:
        if provider == "claude_web":
            raw, _, _ = await analyze_mtf._call_claude_web_deep(captures, SYMBOL, TFS, model)
        else:  # ollama
            raw, _, _ = await analyze_mtf._call_openai_compat_deep(
                captures, SYMBOL, TFS, model, None,
            )
        elapsed = time.time() - t0
        try:
            parsed = analyze_mtf._parse_json(raw)
            status = "ok"
        except Exception as e:
            parsed = {}
            status = f"parse_fail: {str(e)[:60]}"
        per_tf = parsed.get("per_tf") if isinstance(parsed, dict) else None
        return {
            "provider": provider, "model": model,
            "elapsed_s": round(elapsed, 1),
            "status": status,
            "chars": len(raw),
            "optimal_tf": parsed.get("optimal_tf"),
            "signal": parsed.get("signal"),
            "confidence": parsed.get("confidence"),
            "entry": parsed.get("entry"),
            "stop": parsed.get("stop"),
            "tp": parsed.get("tp"),
            "per_tf_count": len(per_tf) if isinstance(per_tf, list) else None,
            "rationale": (parsed.get("rationale") or "")[:200],
            "raw_head": raw[:300] if not parsed else "",
        }
    except Exception as e:
        return {
            "provider": provider, "model": model,
            "elapsed_s": round(time.time() - t0, 1),
            "status": f"error: {type(e).__name__}: {str(e)[:100]}",
            "chars": len(raw),
        }


async def main() -> None:
    print(f"Capturing {SYMBOL} across {len(TFS)} TFs: {TFS}", flush=True)
    cap_t0 = time.time()
    captures: list[dict] = []
    for i, tf in enumerate(TFS, 1):
        shot = await chart.screenshot(SYMBOL, tf, None, area="chart")
        captures.append({"tf": tf, "path": shot["path"]})
        print(f"  [{i}/{len(TFS)}] {tf:>4}  → {Path(shot['path']).name}", flush=True)
    print(f"  capture wall: {time.time() - cap_t0:.1f}s\n", flush=True)

    results: list[dict] = []
    for i, (provider, model) in enumerate(COMBOS, 1):
        print(f"[{i}/{len(COMBOS)}] {provider} + {model} ...", flush=True)
        r = await _run_one(provider, model, captures)
        results.append(r)
        sig = r.get("signal") or "—"
        opt = r.get("optimal_tf") or "—"
        conf = r.get("confidence")
        rr = _rr(r.get("signal"), r.get("entry"), r.get("stop"), r.get("tp"))
        ptf = r.get("per_tf_count")
        print(f"    {r['elapsed_s']:>6}s  opt={opt:<4} {sig:<5}  conf={conf}  R:R={rr}  "
              f"per_tf={ptf}  {r['status']}", flush=True)

    # Summary table.
    print("\n" + "=" * 102)
    print(f"{'Provider':<12} {'Model':<14} {'Time':>7}  {'OptTF':<6} {'Signal':<6} "
          f"{'Conf':>5} {'R:R':>7} {'pTF':>4}  {'Status':<30}")
    print("-" * 102)
    for r in results:
        sig = r.get("signal") or "—"
        opt = r.get("optimal_tf") or "—"
        conf = str(r.get("confidence") or "—")
        rr = _rr(r.get("signal"), r.get("entry"), r.get("stop"), r.get("tp"))
        ptf = str(r.get("per_tf_count") or "—")
        print(f"{r['provider']:<12} {r['model']:<14} "
              f"{r['elapsed_s']:>6}s  {opt:<6} {sig:<6} {conf:>5} {rr:>7} {ptf:>4}  "
              f"{r['status'][:30]:<30}")
    print("=" * 102)

    out = Path(__file__).parent / "live_bench_deep_results.json"
    out.write_text(json.dumps({
        "symbol": SYMBOL, "timeframes": TFS,
        "capture_paths": [c["path"] for c in captures],
        "results": results,
    }, indent=2))
    print(f"\nFull results + rationales → {out}")


if __name__ == "__main__":
    asyncio.run(main())
