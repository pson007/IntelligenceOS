"""Live single-TF bench across all installed providers + models.

Captures ONE chart screenshot, then feeds the same image through each
(provider, model) combo so latency + quality are directly comparable.
Claude-browser runs consume real messages from the user's subscription
(~5 total) — run once per decision session, not in a loop.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Ensure we can import the sibling package when invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tv_automation import analyze_mtf, chart  # noqa: E402

SYMBOL = "MNQ1!"
TIMEFRAME = "5m"

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


async def _run_one(provider: str, model: str, cap: dict) -> dict:
    t0 = time.time()
    raw = ""
    try:
        if provider == "claude_web":
            raw, _, _ = await analyze_mtf._call_claude_web(cap, SYMBOL, TIMEFRAME, model)
        else:  # ollama
            raw, _, _ = await analyze_mtf._call_openai_compat(
                cap, SYMBOL, TIMEFRAME, model, None,
            )
        elapsed = time.time() - t0
        try:
            parsed = analyze_mtf._parse_json(raw)
            status = "ok"
        except Exception as e:
            parsed = {}
            status = f"parse_fail: {str(e)[:60]}"
        return {
            "provider": provider, "model": model,
            "elapsed_s": round(elapsed, 1),
            "status": status,
            "chars": len(raw),
            "signal": parsed.get("signal"),
            "confidence": parsed.get("confidence"),
            "entry": parsed.get("entry"),
            "stop": parsed.get("stop"),
            "tp": parsed.get("tp"),
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
    print(f"Capturing {SYMBOL} {TIMEFRAME}...", flush=True)
    shot = await chart.screenshot(SYMBOL, TIMEFRAME, None, area="chart")
    cap = {"tf": TIMEFRAME, "path": shot["path"]}
    print(f"  → {cap['path']}\n", flush=True)

    results: list[dict] = []
    for i, (provider, model) in enumerate(COMBOS, 1):
        print(f"[{i}/{len(COMBOS)}] {provider} + {model} ...", flush=True)
        r = await _run_one(provider, model, cap)
        results.append(r)
        sig = r.get("signal") or "—"
        conf = r.get("confidence")
        rr = _rr(r.get("signal"), r.get("entry"), r.get("stop"), r.get("tp"))
        print(f"    {r['elapsed_s']:>5}s  {sig:<5}  conf={conf}  R:R={rr}  {r['status']}",
              flush=True)

    # Compact summary table.
    print("\n" + "=" * 92)
    print(f"{'Provider':<12} {'Model':<14} {'Time':>6}  {'Signal':<6} {'Conf':>5} "
          f"{'R:R':>7}  {'Status':<35}")
    print("-" * 92)
    for r in results:
        sig = r.get("signal") or "—"
        conf = str(r.get("confidence") or "—")
        rr = _rr(r.get("signal"), r.get("entry"), r.get("stop"), r.get("tp"))
        print(f"{r['provider']:<12} {r['model']:<14} "
              f"{r['elapsed_s']:>5}s  {sig:<6} {conf:>5} {rr:>7}  "
              f"{r['status'][:35]:<35}")
    print("=" * 92)

    out = Path(__file__).parent / "live_bench_results.json"
    out.write_text(json.dumps({
        "symbol": SYMBOL, "timeframe": TIMEFRAME,
        "capture_path": cap["path"],
        "results": results,
    }, indent=2))
    print(f"\nFull results + rationales → {out}")


if __name__ == "__main__":
    asyncio.run(main())
