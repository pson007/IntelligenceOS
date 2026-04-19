"""Benchmark local vision-language models against the analyze_mtf prompt.

Picks 9 real chart PNGs from the TradingView screenshot cache, feeds them
to each candidate local VL model with the exact production system prompt,
and records:

  - wall latency (cold + warm runs)
  - JSON validity of the response
  - quality score (presence of required fields)
  - output token count

Text-only models (qwen3.5, gpt-oss) are skipped — they literally cannot
see candles. Image-generation models (flux, z-image) are skipped for
the same reason in reverse (they produce images, not read them).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Ensure we can import the sibling package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tv_automation.analyze_mtf import (
    _SYSTEM_PROMPT,
    _call_openai_compat_multi,
    _parse_json,
)

# Reuse existing screenshots instead of capturing fresh — benchmark goal is
# model performance, not chart fidelity. 9 distinct PNGs so Ollama can't
# dedupe-cache and inflate results.
_SCREENSHOT_DIR = Path.home() / "Desktop" / "TradingView"
_CANDIDATE_TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W", "1M"]

# Models whose names include these tokens are treated as VL. Heuristic —
# we could call /api/show per-model to confirm, but every VL model in the
# wild happens to self-identify via name.
#
# Gemma 4 (all sizes: e2b, e4b, 26b, 31b) is multimodal from pretraining
# despite no "vl" in the name — added explicitly.
# Gemma 3 has vision at 4b/12b/27b (270m/1b are text-only); tag-specific
# allowlist below handles that.
_VL_HINTS = ("vl", "vision", "llava", "bakllava", "moondream", "pixtral",
             "gemma4", "kimi", "medgemma")
# Tag-specific VL: model:tag pairs where only some sizes are multimodal.
_VL_TAGGED = {
    "gemma3": ("4b", "12b", "27b"),
}
# Explicit deny-list: local models whose names superficially match a hint
# but that we know are not multi-image LLMs.
_DENY = ("flux", "z-image", "tts", "embed", "reranker")


def list_ollama_models() -> list[dict]:
    try:
        out = subprocess.check_output(
            ["ollama", "list"], text=True, stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    models = []
    for line in out.strip().splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[0]
        size = " ".join(parts[2:4]) if len(parts) >= 4 else parts[2]
        models.append({"name": name, "size": size})
    return models


def classify(model_name: str) -> str:
    low = model_name.lower()
    if any(d in low for d in _DENY):
        return "skip_other"
    if any(h in low for h in _VL_HINTS):
        return "vl"
    # Tag-aware check for families like gemma3 where only some sizes are VL.
    base = low.split(":", 1)[0]
    tag = low.split(":", 1)[1] if ":" in low else ""
    if base in _VL_TAGGED and any(t in tag for t in _VL_TAGGED[base]):
        return "vl"
    return "text_only"


def build_fake_captures() -> list[dict]:
    """9 distinct real chart PNGs. Mix of MNQ1!/ETHUSD across timeframes —
    the exact identity doesn't matter for model-speed comparison, only
    that the images are real, distinct, and at production sizes.
    """
    picks: list[tuple[str, str]] = []
    files = sorted(_SCREENSHOT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    # Pick distinct files, preferring variety across sizes
    seen_inodes = set()
    for f in files:
        if f.stat().st_ino in seen_inodes:
            continue
        seen_inodes.add(f.stat().st_ino)
        picks.append((str(f), f.name))
        if len(picks) >= 9:
            break
    if len(picks) < 9:
        raise RuntimeError(
            f"need at least 9 PNGs in {_SCREENSHOT_DIR} for benchmark; "
            f"found {len(picks)}. Run analyze once to populate the cache."
        )
    return [
        {"tf": tf, "path": path, "filename": name}
        for tf, (path, name) in zip(_CANDIDATE_TFS, picks)
    ]


def score_output(raw: str) -> dict:
    """Validate and score the LLM's response against the production schema.
    Score is # of required fields present (max 8). Penalty if JSON invalid."""
    try:
        parsed = _parse_json(raw)
    except Exception as e:
        return {"json_ok": False, "json_error": str(e)[:200], "score": 0, "parsed": None}

    score = 0
    details = {}

    sig = parsed.get("signal")
    if sig in ("Long", "Short", "Skip"):
        score += 1
        details["signal"] = sig

    conf = parsed.get("confidence")
    if isinstance(conf, (int, float)) and 0 <= conf <= 100:
        score += 1
        details["confidence"] = conf

    for key in ("entry", "stop", "tp"):
        v = parsed.get(key)
        if v is None or isinstance(v, (int, float)):
            score += 1  # null allowed per schema
            details[key] = v

    rat = parsed.get("rationale")
    if isinstance(rat, str) and len(rat) > 20:
        score += 1
        details["rationale_len"] = len(rat)

    per_tf = parsed.get("per_tf")
    if isinstance(per_tf, list) and len(per_tf) == 9:
        score += 1
        details["per_tf_count"] = 9

    # Real pine code is multi-line AND contains multiple distinct code
    # constructs. Single-marker or no-newline means the model is echoing
    # the prompt's description of pine as prose — qwen2.5vl:7b does this.
    # A legitimate pine script has newlines and hits 3+ marker categories.
    pine = parsed.get("pine_code", "") or ""
    has_newline = "\n" in pine
    marker_groups = [
        ("indicator_decl", ("indicator(overlay", "indicator(\"", "indicator('", "//@version", "// @version")),
        ("plot_call", ("plot(close", "plot(open", "plot(high", "plot(low",
                       "plot(close,", "plot(open,", "plotshape(", "hline(")),
        ("drawing", ("label.new(bar_index", "line.new(bar_index",
                     "box.new(bar_index", "label.style_", "line.style_")),
        ("pine_var", ("bar_index", "barstate.", "close[", "high[", "low[",
                     "syminfo.", "timeframe.", "request.security(")),
        ("input_call", ("input.int(", "input.float(", "input.bool(",
                       "input.string(", "input.color(")),
    ]
    matched = sum(1 for _, keys in marker_groups if any(k in pine for k in keys))

    if isinstance(pine, str) and len(pine) > 100 and has_newline and matched >= 3:
        score += 1
        details["pine_len"] = len(pine)
        details["pine_real"] = True
        details["pine_marker_groups"] = matched
    elif isinstance(pine, str) and len(pine) > 100:
        details["pine_len"] = len(pine)
        details["pine_real"] = False
        details["pine_marker_groups"] = matched
        details["pine_warning"] = (
            f"echo-of-prompt suspected (newline={has_newline}, "
            f"marker_groups={matched}/5 — need ≥3)"
        )

    return {
        "json_ok": True, "score": score, "max_score": 8,
        "details": details, "parsed": parsed,
    }


async def bench_one(model: str, captures: list[dict], runs: int = 2) -> dict:
    """Run one model against the canonical prompt `runs` times.

    First run is warm-up (Ollama lazy-loads the model into VRAM — the cold
    hit is real but not representative of steady-state latency). We report
    both so you can see the one-off load cost if relevant.
    """
    results = []
    for i in range(runs):
        t0 = time.time()
        try:
            raw, usage, _cost = await _call_openai_compat_multi(
                captures, "MNQ1!", _CANDIDATE_TFS, model, None,
            )
            elapsed = time.time() - t0
            quality = score_output(raw)
            results.append({
                "run": i + 1, "elapsed_s": round(elapsed, 2),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "score": quality["score"], "max_score": quality.get("max_score", 8),
                "json_ok": quality["json_ok"],
                "json_error": quality.get("json_error"),
                "signal": (quality.get("parsed") or {}).get("signal"),
                "confidence": (quality.get("parsed") or {}).get("confidence"),
                "details": quality.get("details", {}),
            })
        except Exception as e:
            results.append({
                "run": i + 1,
                "elapsed_s": round(time.time() - t0, 2),
                "error": f"{type(e).__name__}: {e}",
            })
    return {"model": model, "runs": results}


def summarize(rows: list[dict]) -> None:
    print()
    print(f"{'MODEL':<28} {'COLD':>7} {'WARM':>7} {'SCORE':>6} {'SIGNAL':>7} {'CONF':>5}  NOTES")
    print("-" * 92)
    for r in rows:
        name = r["model"]
        runs = r["runs"]
        if any("error" in run for run in runs):
            err = next((run.get("error") for run in runs if run.get("error")), "")
            print(f"{name:<28}   FAIL                      {err[:40]}")
            continue
        cold = runs[0]["elapsed_s"]
        warm = runs[-1]["elapsed_s"] if len(runs) > 1 else cold
        score = f"{runs[-1]['score']}/{runs[-1].get('max_score',8)}"
        sig = runs[-1].get("signal") or "—"
        conf = runs[-1].get("confidence")
        conf_s = f"{conf}%" if isinstance(conf, (int, float)) else "—"
        notes = ""
        if not runs[-1].get("json_ok"):
            notes = f"JSON: {(runs[-1].get('json_error') or '')[:40]}"
        print(f"{name:<28} {cold:>6.1f}s {warm:>6.1f}s {score:>6} {sig:>7} {conf_s:>5}  {notes}")


async def main():
    print("=" * 92)
    print("Local VL-model benchmark for analyze_mtf")
    print("=" * 92)

    installed = list_ollama_models()
    vl_models = [m for m in installed if classify(m["name"]) == "vl"]
    text_models = [m for m in installed if classify(m["name"]) == "text_only"]
    skipped = [m for m in installed if classify(m["name"]) == "skip_other"]

    print(f"Installed Ollama models: {len(installed)}")
    print(f"  Vision-capable (will benchmark): {[m['name'] for m in vl_models]}")
    print(f"  Text-only (skipped, can't see charts): {[m['name'] for m in text_models]}")
    print(f"  Other (image-gen/TTS/etc, skipped): {[m['name'] for m in skipped]}")
    print()

    if not vl_models:
        print("No vision-capable local models found. Pull one, e.g.:")
        print("  ollama pull gemma4:31b       # ~20GB, winner of 2026-04-18 bench")
        print("  ollama pull gemma4:26b       # ~18GB, MoE — fast-mode option")
        print("  ollama pull gemma4:e4b       # ~10GB, small VL")
        return

    captures = build_fake_captures()
    print(f"Benchmark input: 9 real chart PNGs from {_SCREENSHOT_DIR}")
    for c in captures:
        print(f"  [{c['tf']:>3}] {c['filename']}")
    print()
    print(f"Running {len(vl_models)} model(s) × 2 runs (cold + warm)…")
    print()

    rows = []
    for m in vl_models:
        print(f"→ {m['name']} ({m['size']}) …", flush=True)
        r = await bench_one(m["name"], captures, runs=2)
        rows.append(r)
        # Per-model detail
        for run in r["runs"]:
            if "error" in run:
                print(f"    run{run['run']}: ERROR {run['error']}")
            else:
                print(f"    run{run['run']}: {run['elapsed_s']}s "
                      f"score={run['score']}/{run.get('max_score',8)} "
                      f"signal={run.get('signal')} conf={run.get('confidence')} "
                      f"tokens={run.get('input_tokens')}in/{run.get('output_tokens')}out"
                      f"{'' if run['json_ok'] else ' JSON_INVALID'}")
        print()

    summarize(rows)

    out_path = Path(__file__).parent / "bench_results.json"
    out_path.write_text(json.dumps(rows, indent=2, default=str))
    print()
    print(f"Full results saved → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
