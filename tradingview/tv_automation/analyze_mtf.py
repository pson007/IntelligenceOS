"""Single-timeframe chart analysis.

Captures one chart screenshot at the user-selected timeframe, asks a
vision LLM to produce a Long/Short/Skip trade recommendation plus an
overlay pine script.

The LLM is asked to return a strict JSON shape:

    {
      "signal":     "Long" | "Short" | "Skip",
      "confidence": 0..100,
      "entry":      number | null,
      "stop":       number | null,
      "tp":         number | null,
      "rationale":  string,
      "pine_code":  "Pine v6 indicator() script that draws
                     entry/stop/tp lines on the chart"
    }

The top-level fields drive the UI's Apply-to-order flow; pine_code is
saved to `pine/generated/` and applied to the chart on explicit user
action.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

from . import chart
from .lib import audit

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# Default when the caller doesn't specify one. Matches the UI's default
# active pill.
DEFAULT_TIMEFRAME = "1D"

# 9-TF set for deep analysis. Order matters — the LLM references TFs
# by position in prompts ("image 1 is 1m, image 9 is 1M"), and the UI
# renders the per-TF breakdown in the same order.
DEFAULT_DEEP_TIMEFRAMES: list[str] = [
    "1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W", "1M",
]

_PINE_DIR = Path(__file__).resolve().parent.parent / "pine" / "generated"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an elite day-trading analyst.

You will receive a single chart screenshot for one symbol at one
timeframe. Read the price action, structure, trend, key levels, and any
visible indicators, then produce a trade recommendation for this
timeframe.

Output STRICTLY a single JSON object, no commentary before or after, no
markdown fences. Schema:

{
  "signal": "Long" | "Short" | "Skip",
  "confidence": integer 0..100,
  "entry": number | null,
  "stop": number | null,
  "tp": number | null,
  "rationale": "2-4 sentences explaining WHY, naming the specific features in the chart that drove the call",
  "pine_code": "Pine v6 indicator() script that draws: entry as a horizontal line, stop and tp as horizontal lines with label.new() annotations. Must compile on TradingView. Use indicator(overlay=true). Use input.float for entry/stop/tp defaults so users can tweak. Use color.green for Long, color.red for Short, color.gray for Skip."
}

If the chart data is ambiguous, low-liquidity, or insufficient, signal
should be "Skip", confidence should be low, and entry/stop/tp should be
null. Never fabricate price levels."""


def _user_text(symbol: str, timeframe: str) -> str:
    return (
        f"Symbol: {symbol}\n"
        f"Timeframe: {timeframe}\n\n"
        "Analyze. Return the JSON object only."
    )


# Deep analysis — 9 images, multi-TF integration, produces a backtestable
# Pine v6 STRATEGY (not just an indicator) so the trader can validate the
# setup on the optimal TF before committing. The "optimal_tf" field is
# the key differentiator vs single-TF: the model picks *where* to trade,
# not just *whether*.
_DEEP_SYSTEM_PROMPT = """You are an elite multi-timeframe day-trading analyst.

You will receive 9 chart screenshots for a single symbol across these
timeframes in order: 1m, 5m, 15m, 30m, 1h, 4h, 1D, 1W, 1M.

How to read the stack:
- Higher TFs (1D/1W/1M) set regime and directional bias.
- Intermediate TFs (1h/4h) show setup structure and key levels.
- Lower TFs (1m/5m/15m/30m) show trigger and entry precision.

Your job:
1. Briefly analyze each TF on its own terms.
2. Pick the ONE timeframe where a trader should actually PLACE this
   trade — the "optimal" TF. It's usually where higher-TF context
   agrees with the intermediate setup AND there's a clear trigger
   visible at that TF's granularity. Not necessarily the TF with the
   highest confidence in isolation — the one where alignment produces
   the best asymmetric R:R.
3. Produce entry/stop/tp specifically calibrated to that optimal TF.
4. Produce a Pine v6 STRATEGY (not an indicator) tailored to the
   optimal-TF logic — so the trader can backtest it on that chart.

Output STRICTLY a single JSON object, no commentary, no markdown fences:

{
  "optimal_tf": "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1D" | "1W" | "1M",
  "signal": "Long" | "Short" | "Skip",
  "confidence": integer 0..100,
  "entry": number | null,
  "stop": number | null,
  "tp": number | null,
  "rationale": "3-5 sentences explaining WHY this TF is optimal, naming the specific alignment across timeframes that produces the setup",
  "per_tf": [
    {"tf": "1m", "signal": "Long"|"Short"|"Skip", "confidence": 0..100,
     "rationale": "one-line justification"},
    ... exactly one entry per timeframe, same order as the images ...
  ],
  "pine_code": "Pine v6 strategy() script implementing the optimal-TF entry logic. Must compile on TradingView. Use strategy(title=\\"MTF Analysis\\", overlay=true, initial_capital=10000, default_qty_type=strategy.fixed, default_qty_value=1, commission_type=strategy.commission.percent, commission_value=0.05). Expose entry/stop/tp as input.float so they're tweakable. Use strategy.entry on the trigger condition, strategy.exit with stop= and limit= for the bracket. Add hline() or plot() horizontal reference lines for entry/stop/tp so the trader sees the setup overlay. Use color.green for Long, color.red for Short, color.gray for Skip (in which case the strategy should not fire)."
}

If TF alignment is weak or conflicting, signal should be "Skip",
confidence should be low, and entry/stop/tp should be null. Never
fabricate price levels. optimal_tf should still be set to whichever TF
best illustrates why you're skipping (i.e., the clearest picture of
the conflict)."""


def _deep_user_text(symbol: str, timeframes: list[str]) -> str:
    return (
        f"Symbol: {symbol}\n"
        f"Timeframes (in the same order as the 9 screenshots below): "
        f"{', '.join(timeframes)}\n\n"
        "Analyze. Pick the optimal TF. Return the JSON object only."
    )


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


async def _capture(symbol: str, timeframe: str) -> dict:
    """Capture a single chart screenshot, emitting audit events the UI
    can stream via `/api/audit/tail?request_id=...`."""
    audit.log("analyze.capture_start", symbol=symbol, tf=timeframe)
    shot = await chart.screenshot(symbol, timeframe, None, area="chart")
    audit.log(
        "analyze.captured", symbol=symbol, tf=timeframe, path=shot["path"],
    )
    return {
        "tf": timeframe, "path": shot["path"],
        "symbol": shot.get("symbol"), "interval": shot.get("interval"),
    }


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _image_as_b64(path: str) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


async def _call_anthropic(capture: dict, symbol: str, timeframe: str,
                          model: str) -> tuple[str, dict, float]:
    from anthropic import AsyncAnthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to tradingview/.env "
            "(see .env.example) or export it in your shell."
        )
    client = AsyncAnthropic(api_key=api_key)

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _image_as_b64(capture["path"]),
            },
        },
        {"type": "text", "text": _user_text(symbol, timeframe)},
    ]

    resp = await client.messages.create(
        # 8k headroom: rationale + a real Pine v6 script plus the ~1-3k
        # reasoning tokens thinking-enabled models emit all fit. 4000
        # was too tight and silently empties the response.
        model=model, max_tokens=8000, system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "\n".join(text_parts)

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
    }
    cost = _anthropic_cost(usage, model)
    return text, usage, cost


_ANTHROPIC_PRICING = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-haiku-4-5":  (0.80, 4.0),
}


def _anthropic_cost(usage: dict, model: str) -> float:
    price = _ANTHROPIC_PRICING.get(model)
    if not price:
        return 0.0
    in_rate, out_rate = price
    return (usage["input_tokens"] * in_rate + usage["output_tokens"] * out_rate) / 1_000_000


async def _call_openai_compat(capture: dict, symbol: str, timeframe: str,
                              model: str, base_url: str | None
                              ) -> tuple[str, dict, float]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=base_url or "http://localhost:11434/v1",
        api_key=os.environ.get("OPENAI_API_KEY", "sk-local"),
    )
    content = [
        {"type": "text", "text": _user_text(symbol, timeframe)},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{_image_as_b64(capture['path'])}"},
        },
    ]
    resp = await client.chat.completions.create(
        model=model, max_tokens=8000,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    )
    text = resp.choices[0].message.content or ""
    u = getattr(resp, "usage", None)
    usage = {
        "input_tokens": getattr(u, "prompt_tokens", 0) if u else 0,
        "output_tokens": getattr(u, "completion_tokens", 0) if u else 0,
    }
    return text, usage, 0.0


async def _call_claude_web(capture: dict, symbol: str, timeframe: str,
                           model: str | None,
                           ) -> tuple[str, dict, float]:
    """Drive claude.ai via the attached Chrome. Same prompt as _call_anthropic,
    just delivered through the browser instead of the API. No API key
    required — uses the user's existing web subscription.

    `model` is a claude.ai display name ("Sonnet 4.6", "Opus 4.7",
    "Haiku 4.5") resolved by _resolve_model from any alias the UI sends."""
    from .claude_web import analyze_via_claude_web
    return await analyze_via_claude_web(
        capture["path"], _SYSTEM_PROMPT, _user_text(symbol, timeframe),
        model=model,
    )


# ---------------------------------------------------------------------------
# Deep (multi-image) LLM calls
# ---------------------------------------------------------------------------
# Same shape as the single-image versions above but take a list of
# captures and use the _DEEP_SYSTEM_PROMPT. Kept as separate functions
# rather than overloading the single-image ones because the message
# construction, max_tokens budget, and failure modes differ enough that
# a shared path hides more than it saves.


async def _call_anthropic_deep(captures: list[dict], symbol: str,
                               timeframes: list[str], model: str
                               ) -> tuple[str, dict, float]:
    from anthropic import AsyncAnthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to tradingview/.env."
        )
    client = AsyncAnthropic(api_key=api_key)

    content: list[dict] = []
    for c in captures:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _image_as_b64(c["path"]),
            },
        })
    content.append({"type": "text", "text": _deep_user_text(symbol, timeframes)})

    resp = await client.messages.create(
        # 12k for multi-image: per_tf[9] notes + integrated rationale +
        # a real Pine v6 strategy script plus thinking tokens all fit.
        model=model, max_tokens=12000, system=_DEEP_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "\n".join(text_parts)

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
    }
    cost = _anthropic_cost(usage, model)
    return text, usage, cost


async def _call_openai_compat_deep(captures: list[dict], symbol: str,
                                   timeframes: list[str], model: str,
                                   base_url: str | None,
                                   ) -> tuple[str, dict, float]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=base_url or "http://localhost:11434/v1",
        api_key=os.environ.get("OPENAI_API_KEY", "sk-local"),
    )
    content: list[dict] = [
        {"type": "text", "text": _deep_user_text(symbol, timeframes)},
    ]
    for c in captures:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{_image_as_b64(c['path'])}"},
        })
    resp = await client.chat.completions.create(
        model=model, max_tokens=12000,
        messages=[
            {"role": "system", "content": _DEEP_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    )
    text = resp.choices[0].message.content or ""
    u = getattr(resp, "usage", None)
    usage = {
        "input_tokens": getattr(u, "prompt_tokens", 0) if u else 0,
        "output_tokens": getattr(u, "completion_tokens", 0) if u else 0,
    }
    return text, usage, 0.0


async def _call_claude_web_deep(captures: list[dict], symbol: str,
                                timeframes: list[str], model: str | None,
                                ) -> tuple[str, dict, float]:
    from .claude_web import analyze_via_claude_web_multi
    return await analyze_via_claude_web_multi(
        [c["path"] for c in captures],
        _DEEP_SYSTEM_PROMPT,
        _deep_user_text(symbol, timeframes),
        model=model,
    )


_MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
    "haiku":  "claude-haiku-4-5",
}

# For claude_web we drive the browser UI, so we need the model's human-
# readable display name as it appears in the dropdown, not an API ID.
# Accepts short aliases ("sonnet") AND API IDs ("claude-sonnet-4-6") as
# keys so a single UI dropdown works across both Anthropic and
# claude.ai providers.
_CLAUDE_WEB_DISPLAY_NAMES = {
    "sonnet": "Sonnet 4.6",
    "opus":   "Opus 4.7",
    "haiku":  "Haiku 4.5",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-opus-4-7":   "Opus 4.7",
    "claude-haiku-4-5":  "Haiku 4.5",
}


def _resolve_model(provider: str, model: str | None) -> str:
    if provider == "claude_web":
        # Default to Sonnet 4.6 — good balance of speed and quality for
        # chart analysis; Opus is overkill for a structured JSON task,
        # Haiku is cheap but sometimes loses the schema.
        if not model:
            return "Sonnet 4.6"
        return _CLAUDE_WEB_DISPLAY_NAMES.get(model.lower(), model)
    if not model:
        if provider == "anthropic":
            return "claude-sonnet-4-6"
        # gemma4:31b was the winner of the 2026-04-18 4-model bench —
        # most stable signal, real pine code, 6× more input-token-efficient
        # than Qwen2.5/3-VL.
        if provider == "ollama":
            return "gemma4:31b"
        return "unknown"
    return _MODEL_ALIASES.get(model, model)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _parse_json(raw: str) -> dict:
    """Extract the first balanced JSON object. The prompt forbids markdown
    fences and leading commentary, but models still slip up sometimes."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", stripped)
    if not m:
        raise ValueError(f"no JSON object found in response: {stripped[:300]!r}")
    return json.loads(m.group(0))


# ---------------------------------------------------------------------------
# Pine script save
# ---------------------------------------------------------------------------


def _save_pine(symbol: str, pine_code: str) -> Path:
    _PINE_DIR.mkdir(parents=True, exist_ok=True)
    safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", symbol)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = _PINE_DIR / f"{safe_sym}_analysis_{ts}.pine"
    path.write_text(pine_code, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def analyze_chart(
    symbol: str,
    *,
    timeframe: str = DEFAULT_TIMEFRAME,
    provider: str = "ollama",
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Run a single-timeframe analysis and return the structured result.

    Captures the chart at `timeframe`, sends one vision-LLM turn, parses
    the JSON response, and saves the generated pine script to disk.
    Applying the pine to the chart is a separate explicit action.

    Providers:
      * ``ollama`` (default) — local, $0, ~85s on gemma4:31b
      * ``anthropic`` — Claude API, requires ANTHROPIC_API_KEY, ~10s
      * ``claude_web`` — drives claude.ai in the attached Chrome, uses
        your web subscription (no API key), ~30-60s
    """
    if provider not in ("anthropic", "ollama", "claude_web"):
        raise ValueError(
            f"unknown provider {provider!r}; "
            "valid: anthropic, ollama, claude_web"
        )
    tf = timeframe or DEFAULT_TIMEFRAME
    resolved_model = _resolve_model(provider, model)

    audit.log(
        "analyze.start", symbol=symbol, timeframe=tf,
        provider=provider, model=resolved_model,
    )
    t0 = time.time()

    cap = await _capture(symbol, tf)

    audit.log(
        "analyze.llm_request", provider=provider, model=resolved_model,
    )
    llm_t0 = time.time()
    if provider == "anthropic":
        raw, usage, cost = await _call_anthropic(cap, symbol, tf, resolved_model)
    elif provider == "claude_web":
        raw, usage, cost = await _call_claude_web(cap, symbol, tf, resolved_model)
    else:
        raw, usage, cost = await _call_openai_compat(
            cap, symbol, tf, resolved_model, base_url,
        )
    llm_elapsed = time.time() - llm_t0

    try:
        parsed = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        # Dump the full raw response to disk so a parse failure is
        # actually debuggable — the `raw_head` in the audit event is
        # capped at 500 chars and most failures happen deeper than that
        # (pine_code, long rationales, etc).
        dump_dir = _PINE_DIR.parent / "parse_failures"
        dump_dir.mkdir(parents=True, exist_ok=True)
        safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", symbol)
        ts = time.strftime("%Y%m%d-%H%M%S")
        dump_path = dump_dir / f"{safe_sym}_{provider}_{ts}.txt"
        try:
            dump_path.write_text(raw, encoding="utf-8")
        except Exception:
            dump_path = None  # writing the debug dump must never mask
                              # the original parse error
        audit.log(
            "analyze.parse_fail", error=str(e),
            raw_head=raw[:500], raw_len=len(raw),
            dump_path=str(dump_path) if dump_path else None,
        )
        raise RuntimeError(f"LLM returned invalid JSON: {e}") from e

    pine_path: Path | None = None
    if parsed.get("pine_code"):
        pine_path = _save_pine(symbol, parsed["pine_code"])

    result = {
        "symbol": symbol,
        "timeframe": tf,
        "signal": parsed.get("signal"),
        "confidence": parsed.get("confidence"),
        "entry": parsed.get("entry"),
        "stop": parsed.get("stop"),
        "tp": parsed.get("tp"),
        "rationale": parsed.get("rationale"),
        "pine_code": parsed.get("pine_code"),
        "pine_path": str(pine_path) if pine_path else None,
        "capture": {"tf": cap["tf"], "path": cap["path"]},
        "provider": provider,
        "model": resolved_model,
        "usage": usage,
        "cost_usd": cost,
        "elapsed_s": round(time.time() - t0, 2),
        "llm_elapsed_s": round(llm_elapsed, 2),
    }
    audit.log(
        "analyze.done",
        signal=result["signal"], confidence=result["confidence"],
        entry=result["entry"], stop=result["stop"], tp=result["tp"],
        cost_usd=cost, elapsed_s=result["elapsed_s"],
        pine_path=result["pine_path"],
    )
    return result


# ---------------------------------------------------------------------------
# Deep (multi-timeframe) public entry point
# ---------------------------------------------------------------------------


async def analyze_deep(
    symbol: str,
    *,
    timeframes: list[str] | None = None,
    provider: str = "claude_web",
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Run a 9-timeframe deep analysis and return the integrated result.

    Captures all 9 TFs (sequential CDP), then one multi-image LLM call
    that produces: an *optimal_tf* recommendation, consolidated entry/
    stop/tp at that TF, a per-TF breakdown, and a Pine v6 *strategy*
    script (not just an indicator) so the setup can be backtested.

    Defaults to claude_web because the 2026-04-19 live bench showed
    Sonnet beats Gemma on multi-image reasoning by a wide margin; the
    accuracy delta matters more here since deep analysis is slower.
    """
    if provider not in ("anthropic", "ollama", "claude_web"):
        raise ValueError(
            f"unknown provider {provider!r}; "
            "valid: anthropic, ollama, claude_web"
        )
    tfs = timeframes or DEFAULT_DEEP_TIMEFRAMES
    resolved_model = _resolve_model(provider, model)

    audit.log(
        "analyze.start", symbol=symbol, timeframes=tfs,
        provider=provider, model=resolved_model, mode="deep",
    )
    t0 = time.time()

    # Capture all TFs sequentially — all through the same CDP session,
    # so parallelism isn't possible without a second Chrome instance.
    captures: list[dict] = []
    for idx, tf in enumerate(tfs):
        audit.log(
            "analyze.capture_start", symbol=symbol, tf=tf,
            index=idx + 1, total=len(tfs),
        )
        shot = await chart.screenshot(symbol, tf, None, area="chart")
        captures.append({
            "tf": tf, "path": shot["path"],
            "symbol": shot.get("symbol"), "interval": shot.get("interval"),
        })
        audit.log(
            "analyze.captured", symbol=symbol, tf=tf,
            index=idx + 1, total=len(tfs), path=shot["path"],
        )

    audit.log(
        "analyze.llm_request", n_images=len(captures),
        provider=provider, model=resolved_model, mode="deep",
    )
    llm_t0 = time.time()
    if provider == "anthropic":
        raw, usage, cost = await _call_anthropic_deep(
            captures, symbol, tfs, resolved_model,
        )
    elif provider == "claude_web":
        raw, usage, cost = await _call_claude_web_deep(
            captures, symbol, tfs, resolved_model,
        )
    else:
        raw, usage, cost = await _call_openai_compat_deep(
            captures, symbol, tfs, resolved_model, base_url,
        )
    llm_elapsed = time.time() - llm_t0

    try:
        parsed = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        dump_dir = _PINE_DIR.parent / "parse_failures"
        dump_dir.mkdir(parents=True, exist_ok=True)
        safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", symbol)
        ts = time.strftime("%Y%m%d-%H%M%S")
        dump_path = dump_dir / f"{safe_sym}_deep_{provider}_{ts}.txt"
        try:
            dump_path.write_text(raw, encoding="utf-8")
        except Exception:
            dump_path = None
        audit.log(
            "analyze.parse_fail", error=str(e),
            raw_head=raw[:500], raw_len=len(raw),
            dump_path=str(dump_path) if dump_path else None, mode="deep",
        )
        raise RuntimeError(f"LLM returned invalid JSON: {e}") from e

    pine_path: Path | None = None
    if parsed.get("pine_code"):
        pine_path = _save_pine(symbol, parsed["pine_code"])

    # Guard against LLM hallucinating a TF outside the 9-set. If the model
    # returns e.g. "2h" or "3m", we blank the field rather than surface
    # an unusable value to the UI (which has no pill for it, so the
    # auto-chart-switch would silently fail). Null is an honest "no
    # recommendation" signal — better than a dangling string.
    optimal_tf = parsed.get("optimal_tf")
    if optimal_tf not in tfs:
        audit.log(
            "analyze.optimal_tf_invalid", provided=optimal_tf,
            valid=tfs, mode="deep",
        )
        optimal_tf = None

    result = {
        "mode": "deep",
        "symbol": symbol,
        "timeframes": tfs,
        "optimal_tf": optimal_tf,
        "signal": parsed.get("signal"),
        "confidence": parsed.get("confidence"),
        "entry": parsed.get("entry"),
        "stop": parsed.get("stop"),
        "tp": parsed.get("tp"),
        "rationale": parsed.get("rationale"),
        "per_tf": parsed.get("per_tf") or [],
        "pine_code": parsed.get("pine_code"),
        "pine_path": str(pine_path) if pine_path else None,
        "captures": [{"tf": c["tf"], "path": c["path"]} for c in captures],
        "provider": provider,
        "model": resolved_model,
        "usage": usage,
        "cost_usd": cost,
        "elapsed_s": round(time.time() - t0, 2),
        "llm_elapsed_s": round(llm_elapsed, 2),
    }
    audit.log(
        "analyze.done", mode="deep",
        optimal_tf=result["optimal_tf"],
        signal=result["signal"], confidence=result["confidence"],
        entry=result["entry"], stop=result["stop"], tp=result["tp"],
        cost_usd=cost, elapsed_s=result["elapsed_s"],
        pine_path=result["pine_path"],
    )
    return result
