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

# 10-TF set for deep analysis. Order matters — the LLM references TFs
# by position in prompts ("image 1 is 30s, image 10 is 1W"), and the UI
# renders the per-TF breakdown in the same order. Mirrors the pill bar
# in ui/index.html — keep in sync when TFs are added/removed there.
DEFAULT_DEEP_TIMEFRAMES: list[str] = [
    "30s", "45s", "1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W",
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
  "unknowns": [
    {"what": "the specific thing you're uncertain about", "resolves_how": "what would answer it"},
    ... 0 to 3 entries. Empty array if nothing material is uncertain.
  ],
  "pine_code": "Pine v6 indicator() script that draws: entry as a horizontal line, stop and tp as horizontal lines with label.new() annotations. Must compile on TradingView. Use indicator(overlay=true). Use input.float for entry/stop/tp defaults so users can tweak. Use color.green for Long, color.red for Short, color.gray for Skip."
}

CRITICAL JSON escaping: the `pine_code` value is a JSON string, so
every double-quote *inside* the pine code MUST be escaped as \\"
(backslash-quote). Pine strings look like "Title" in source — in the
JSON output they must appear as \\"Title\\". Also escape newlines as
\\n. Example of correct output: "pine_code": "indicator(\\"My Title\\", overlay=true)\\nplot(close)".
Emitting unescaped quotes will break the downstream parser and drop
your entire response.

`unknowns` is required — include only *material* uncertainties that
could genuinely flip the signal or meaningfully change R:R. Examples:
upcoming economic events visible in session context, proximity to key
levels that haven't been decisively broken, missing volume/flow data,
news catalysts you can infer from time-of-day but not confirm. Do NOT
pad this — 0 entries is a valid and honest answer when the setup is
clear. Prefer quality over quantity.

If the chart data is ambiguous, low-liquidity, or insufficient, signal
should be "Skip", confidence should be low, and entry/stop/tp should be
null. Never fabricate price levels."""


def _user_text(symbol: str, timeframe: str,
               indicator_block: str | None = None,
               drawings_block: str | None = None) -> str:
    blocks = []
    if indicator_block:
        blocks.append(indicator_block)
    if drawings_block:
        blocks.append(drawings_block)
    suffix = ("\n\n" + "\n\n".join(blocks)) if blocks else ""
    return (
        f"Symbol: {symbol}\n"
        f"Timeframe: {timeframe}\n\n"
        f"Analyze. Return the JSON object only.{suffix}"
    )


def _format_indicator_block(values: list[dict] | None) -> str | None:
    """Render TV's Data Window snapshot as a markdown table the LLM
    can reference for exact numerical reads. Returns None when no
    values were available (so the prompt stays unchanged)."""
    if not values:
        return None
    lines = [
        "## INDICATOR VALUES (exact, read from chart memory — prefer these "
        "over visual reads off the screenshot)"
    ]
    any_value = False
    for group in values:
        title = group.get("title") or "(unnamed)"
        rows = []
        for v in group.get("values") or []:
            val = v.get("value")
            if val is None or val == "":
                continue
            name = v.get("name") or "?"
            rows.append(f"  - {name}: {val}")
            any_value = True
        if rows:
            lines.append(f"- **{title}**")
            lines.extend(rows)
    return "\n".join(lines) if any_value else None


def _format_drawings_block(drawings: dict | None) -> str | None:
    """Wrap user_drawings.format_for_prompt — defaults to None when no
    drawings exist on the chart."""
    if not drawings or not drawings.get("total"):
        return None
    from . import user_drawings as ud
    return ud.format_for_prompt(drawings)


# Deep analysis — 10 images, multi-TF integration, produces a backtestable
# Pine v6 STRATEGY (not just an indicator) so the trader can validate the
# setup on the optimal TF before committing. The "optimal_tf" field is
# the key differentiator vs single-TF: the model picks *where* to trade,
# not just *whether*.
_DEEP_SYSTEM_PROMPT = """You are an elite multi-timeframe day-trading analyst.

You will receive 10 chart screenshots for a single symbol across these
timeframes in order: 30s, 45s, 1m, 5m, 15m, 30m, 1h, 4h, 1D, 1W.

How to read the stack:
- Higher TFs (1D/1W) set regime and directional bias.
- Intermediate TFs (1h/4h) show setup structure and key levels.
- Lower TFs (1m/5m/15m/30m) show trigger and entry precision.
- Sub-minute TFs (30s/45s) show microstructure for scalp timing only —
  do not use them to set directional bias.

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
  "optimal_tf": "30s" | "45s" | "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1D" | "1W",
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
  "unknowns": [
    {"what": "the specific thing you're uncertain about", "resolves_how": "what would answer it"},
    ... 0 to 3 entries. Empty array if nothing material is uncertain.
  ],
  "pine_code": "Pine v6 strategy() script implementing the optimal-TF entry logic. Must compile on TradingView. Use strategy(title=\\"MTF Analysis\\", overlay=true, initial_capital=10000, default_qty_type=strategy.fixed, default_qty_value=1, commission_type=strategy.commission.percent, commission_value=0.05). Expose entry/stop/tp as input.float so they're tweakable. Use strategy.entry on the trigger condition, strategy.exit with stop= and limit= for the bracket. Add hline() or plot() horizontal reference lines for entry/stop/tp so the trader sees the setup overlay. Use color.green for Long, color.red for Short, color.gray for Skip (in which case the strategy should not fire)."
}

CRITICAL JSON escaping: the `pine_code` value is a JSON string, so
every double-quote *inside* the pine code MUST be escaped as \\"
(backslash-quote) and every newline as \\n. Pine strings look like
"Title" in source — in the JSON they must appear as \\"Title\\".
Emitting unescaped quotes will break the downstream parser and drop
your entire response.

`unknowns` is required — include only *material* uncertainties that
could genuinely flip the signal or meaningfully change R:R. Examples:
upcoming economic events, proximity to key cross-TF levels that
haven't been decisively resolved, missing volume/flow data at the
optimal TF, conflicts between higher-TF regime and lower-TF trigger.
Do NOT pad — 0 entries is a valid and honest answer.

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
    """Capture a single chart screenshot + indicator values in one
    CDP-attached session. Emits audit events the UI streams via
    `/api/audit/tail?request_id=...`.

    Indicator values come from TV's Data Window via the JS API — exact
    numerical outputs (RSI, EMA, strategy entry/stop) that get injected
    into the LLM prompt so the vision model doesn't have to read faded
    panel text in the PNG."""
    audit.log("analyze.capture_start", symbol=symbol, tf=timeframe)
    shot = await chart.screenshot(
        symbol, timeframe, None, area="chart", read_indicator_values=True,
    )
    audit.log(
        "analyze.captured", symbol=symbol, tf=timeframe, path=shot["path"],
    )
    return {
        "tf": timeframe, "path": shot["path"],
        "symbol": shot.get("symbol"), "interval": shot.get("interval"),
        "indicator_values": shot.get("indicator_values"),
        "user_drawings": shot.get("user_drawings"),
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
        {"type": "text", "text": _user_text(symbol, timeframe, _format_indicator_block(capture.get("indicator_values")), _format_drawings_block(capture.get("user_drawings")))},
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
        {"type": "text", "text": _user_text(symbol, timeframe, _format_indicator_block(capture.get("indicator_values")), _format_drawings_block(capture.get("user_drawings")))},
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
        capture["path"], _SYSTEM_PROMPT, _user_text(symbol, timeframe, _format_indicator_block(capture.get("indicator_values")), _format_drawings_block(capture.get("user_drawings"))),
        model=model,
    )


async def _call_chatgpt_web(capture: dict, symbol: str, timeframe: str,
                            model: str | None,
                            ) -> tuple[str, dict, float]:
    """Drive chatgpt.com via the attached Chrome. Same shape as
    _call_claude_web, different site. No API key required — uses the
    user's existing ChatGPT subscription.

    `model` is a ChatGPT display label ("Instant", "Thinking") resolved
    by _resolve_model from any alias the UI sends."""
    from .chatgpt_web import analyze_via_chatgpt_web
    return await analyze_via_chatgpt_web(
        capture["path"], _SYSTEM_PROMPT, _user_text(symbol, timeframe, _format_indicator_block(capture.get("indicator_values")), _format_drawings_block(capture.get("user_drawings"))),
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


async def _call_chatgpt_web_deep(captures: list[dict], symbol: str,
                                 timeframes: list[str], model: str | None,
                                 ) -> tuple[str, dict, float]:
    from .chatgpt_web import analyze_via_chatgpt_web_multi
    return await analyze_via_chatgpt_web_multi(
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

# ChatGPT's modern picker uses the simplified Instant / Thinking
# routing (not a full model dropdown). Aliases cover variations the
# UI or user might send.
_CHATGPT_WEB_DISPLAY_NAMES = {
    "instant":  "Instant",
    "thinking": "Thinking",
    "fast":     "Instant",
    "deep":     "Thinking",
    "gpt-instant":  "Instant",
    "gpt-thinking": "Thinking",
}


def _resolve_model(provider: str, model: str | None) -> str:
    if provider == "claude_web":
        # Default to Sonnet 4.6 — good balance of speed and quality for
        # chart analysis; Opus is overkill for a structured JSON task,
        # Haiku is cheap but sometimes loses the schema.
        if not model:
            return "Sonnet 4.6"
        return _CLAUDE_WEB_DISPLAY_NAMES.get(model.lower(), model)
    if provider == "chatgpt_web":
        # Default to Instant — fast routing that handles structured JSON
        # reliably. Thinking is slower but better-reasoned when the user
        # explicitly wants it (pressure test, hard calls).
        if not model:
            return "Instant"
        return _CHATGPT_WEB_DISPLAY_NAMES.get(model.lower(), model)
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


def _sanitize_unknowns(raw) -> list[dict]:
    """Normalize the LLM's `unknowns` output into a consistent shape.

    Accepts what the model actually returns, not what it should return:
      * list of objects with {what, resolves_how} — the canonical shape
      * list of plain strings — coerce to {what: string, resolves_how: ""}
      * None / non-list — return empty list
    Also caps at 5 entries to prevent a runaway "every possible unknown"
    response from burying the real signal. 0 entries is valid.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[:5]:
        if isinstance(item, dict):
            what = str(item.get("what") or "").strip()
            if not what:
                continue
            out.append({
                "what": what,
                "resolves_how": str(item.get("resolves_how") or "").strip(),
            })
        elif isinstance(item, str) and item.strip():
            out.append({"what": item.strip(), "resolves_how": ""})
    return out


def _repair_pine_code_quotes(raw: str) -> str:
    """Defensive repair for the most common LLM JSON failure mode:
    unescaped double-quotes inside the `pine_code` string value.

    Pine v6 uses `"..."` for string literals (titles, labels, color
    names). When an LLM emits pine code as a JSON string value, it
    must escape every internal `"` as `\\"` — but models often forget,
    especially on mid-complexity scripts. The result: JSON parse fails
    somewhere inside the pine body.

    This repair is narrow: it only rewrites the `pine_code` value,
    only when there's exactly one such key, and only when the value
    extends to the final closing-quote-before-`}`. Anything else falls
    through to the caller's error path unchanged.

    Idempotent in the "already correct" case — if the pine_code is
    already properly escaped, re-escaping is a no-op because we only
    target `"` NOT preceded by `\\`.
    """
    # Locate the pine_code field. Tolerant of whitespace variations.
    key_m = re.search(r'("pine_code"\s*:\s*)"', raw)
    if not key_m:
        return raw
    value_start = key_m.end()

    # The value runs to the LAST `"` before the object's closing `}`.
    # We anchor on `"\s*}\s*$` so truncated responses don't get repaired
    # into something subtly wrong.
    tail_m = re.search(r'"\s*}\s*$', raw)
    if not tail_m:
        return raw
    value_end = tail_m.start()

    content = raw[value_start:value_end]
    # Escape `"` that isn't already backslash-escaped. Doesn't handle
    # the `\\"` edge case perfectly (that'd need counting consecutive
    # backslashes), but pine code rarely contains literal backslashes.
    fixed = re.sub(r'(?<!\\)"', r'\\"', content)
    return raw[:value_start] + fixed + raw[value_end:]


def _parse_json(raw: str) -> dict:
    """Extract the first balanced JSON object. The prompt forbids markdown
    fences and leading commentary, but models still slip up sometimes.
    A targeted repair pass handles the most common failure (unescaped
    double-quotes inside pine_code) before giving up."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            # Try the pine_code-quote repair. Only retry once to avoid
            # infinite loops on genuinely malformed responses.
            repaired = _repair_pine_code_quotes(stripped)
            if repaired != stripped:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass
    m = re.search(r"\{[\s\S]*\}", stripped)
    if not m:
        raise ValueError(f"no JSON object found in response: {stripped[:300]!r}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # Last chance: repair the regex-extracted block too.
        repaired = _repair_pine_code_quotes(m.group(0))
        if repaired != m.group(0):
            return json.loads(repaired)
        raise


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


def _build_levels_pine(
    symbol: str, signal: str | None,
    entry: float | None, stop: float | None, tp: float | None,
) -> str | None:
    """Deterministic pine template that draws Entry / Stop / TP as
    horizontal lines with labels. Called instead of using LLM-generated
    pine for single-TF analyses — the LLM tends to write top-level
    `line.new` / `label.new` calls that fire every bar and get culled
    by Pine's default `max_lines_count=50` / `max_labels_count=50`.

    This version:
      * uses `hline()` for the horizontal levels — declarative, one
        line per level, extends both directions across the whole chart.
      * creates labels ONCE on the last bar with `var` + `barstate.islast`,
        so exactly three labels exist at any time (no bar-by-bar churn).
      * colors Long setups green (TP)/red (Stop), Short the mirror,
        Skip gray — same convention as the result card's signal pill.
      * exposes entry/stop/tp as `input.float` so the trader can tweak
        without re-running analyze.

    Returns None if entry/stop/tp aren't all numeric — nothing sensible
    to draw without all three levels.
    """
    if not all(isinstance(v, (int, float)) for v in (entry, stop, tp)):
        return None

    sig = (signal or "Skip").strip()
    # Color semantics: TP is always the "good" direction, Stop the
    # "bad" one. Skip draws gray for both — indicates "not a setup,
    # just reference marks."
    if sig == "Long":
        tp_color, stop_color = "color.new(color.green, 0)", "color.new(color.red, 0)"
    elif sig == "Short":
        tp_color, stop_color = "color.new(color.green, 0)", "color.new(color.red, 0)"
    else:
        tp_color = stop_color = "color.new(color.gray, 0)"
    entry_color = "color.new(color.yellow, 0)"

    # Pine v6 script. `hline` takes a `simple float` — we pass the
    # input.float values directly (input.float returns simple).
    return f"""//@version=6
indicator("Trade Levels — {symbol} {sig}", overlay=true,
          max_labels_count=10)

entryInput = input.float({entry}, "Entry", step=0.25)
stopInput  = input.float({stop},  "Stop",  step=0.25)
tpInput    = input.float({tp},    "Take Profit", step=0.25)

// --- horizontal level lines (one per level, static across chart) ---
hline(entryInput, "Entry", color={entry_color},
      linestyle=hline.style_solid, linewidth=1)
hline(stopInput,  "Stop",  color={stop_color},
      linestyle=hline.style_dashed, linewidth=1)
hline(tpInput,    "TP",    color={tp_color},
      linestyle=hline.style_dashed, linewidth=1)

// --- labels pinned to the most-recent bar, reused in-place ---
// `var` keeps a single label across bar history; on each new last-bar
// tick we delete-and-recreate so the label moves to the right edge.
var label entryLbl = na
var label stopLbl  = na
var label tpLbl    = na

if barstate.islast
    label.delete(entryLbl)
    label.delete(stopLbl)
    label.delete(tpLbl)
    entryLbl := label.new(bar_index, entryInput,
        "Entry " + str.tostring(entryInput),
        color={entry_color}, textcolor=color.black,
        style=label.style_label_left, size=size.small)
    stopLbl := label.new(bar_index, stopInput,
        "Stop " + str.tostring(stopInput),
        color={stop_color}, textcolor=color.white,
        style=label.style_label_left, size=size.small)
    tpLbl := label.new(bar_index, tpInput,
        "TP " + str.tostring(tpInput),
        color={tp_color}, textcolor=color.white,
        style=label.style_label_left, size=size.small)
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def pressure_test(
    symbol: str,
    *,
    timeframe: str = DEFAULT_TIMEFRAME,
    combos: list[dict] | None = None,
    base_url: str | None = None,
) -> dict:
    """Run the same captured chart through multiple (provider, model)
    combos and return a consensus summary.

    Used when a trade is meaningful enough that a second (third) opinion
    is worth the extra wait. Captures ONCE so all providers see the
    exact same chart state — a 30-second market move between provider
    calls would pollute the comparison.

    Returns shape:
        {
          "symbol": str, "timeframe": str, "capture": {...},
          "results": [
              {"provider": ..., "model": ..., "signal": ..., "confidence": ...,
               "entry": ..., "stop": ..., "tp": ..., "rationale": ..., "elapsed_s": ...},
              ... one per combo (failed combos carry "error" instead)
          ],
          "consensus": {
              "direction": "Long"|"Short"|"Skip"|None,
              "agree": int,           # providers matching top_signal
              "total": int,           # providers that returned a signal
              "all_agree": bool,
              "entry_spread": float|None,  # max-min across providers with same direction
              "stop_spread": float|None,
              "tp_spread": float|None,
          },
          "elapsed_s": float,
        }
    """
    # Default combo: four distinct perspectives across three families.
    # Sonnet + Opus share training data so they'll often agree; ChatGPT
    # Instant is a cross-family OpenAI crosscheck; Gemma is the local
    # out-of-distribution crosscheck. Agreement across >= 2 families is
    # a stronger signal than within-family majority.
    if combos is None:
        # Default ensemble — claude_web removed from defaults until
        # claude.ai's UI stabilizes (current build has no file-input
        # selector reachable + the model dropdown won't open via
        # automation; pressure test runs reliably failed with both).
        # Caller can still pass `combos=` explicitly to include it.
        combos = [
            {"provider": "chatgpt_web", "model": "instant"},
            {"provider": "chatgpt_web", "model": "thinking"},
            {"provider": "ollama",      "model": "gemma4:31b"},
        ]

    audit.log(
        "pressure_test.start", symbol=symbol, timeframe=timeframe,
        combos=[{"provider": c["provider"], "model": c.get("model")} for c in combos],
    )
    t0 = time.time()

    # Capture ONCE — all providers see the same PNG.
    cap = await _capture(symbol, timeframe)

    results: list[dict] = []
    for idx, combo in enumerate(combos, 1):
        provider = combo["provider"]
        model_alias = combo.get("model")
        resolved_model = _resolve_model(provider, model_alias)
        c_t0 = time.time()
        audit.log(
            "pressure_test.provider_start",
            index=idx, total=len(combos),
            provider=provider, model=resolved_model,
        )
        try:
            if provider == "anthropic":
                raw, usage, cost = await _call_anthropic(
                    cap, symbol, timeframe, resolved_model,
                )
            elif provider == "claude_web":
                raw, usage, cost = await _call_claude_web(
                    cap, symbol, timeframe, resolved_model,
                )
            elif provider == "chatgpt_web":
                raw, usage, cost = await _call_chatgpt_web(
                    cap, symbol, timeframe, resolved_model,
                )
            elif provider == "ollama":
                raw, usage, cost = await _call_openai_compat(
                    cap, symbol, timeframe, resolved_model, base_url,
                )
            else:
                raise ValueError(f"unknown provider: {provider!r}")
            parsed = _parse_json(raw)
            results.append({
                "provider":   provider,
                "model":      resolved_model,
                "signal":     parsed.get("signal"),
                "confidence": parsed.get("confidence"),
                "entry":      parsed.get("entry"),
                "stop":       parsed.get("stop"),
                "tp":         parsed.get("tp"),
                "rationale":  parsed.get("rationale"),
                "unknowns":   _sanitize_unknowns(parsed.get("unknowns")),
                "cost_usd":   cost,
                "elapsed_s":  round(time.time() - c_t0, 2),
            })
            audit.log(
                "pressure_test.provider_done",
                index=idx, provider=provider, model=resolved_model,
                signal=parsed.get("signal"),
                confidence=parsed.get("confidence"),
                elapsed_s=round(time.time() - c_t0, 2),
            )
        except Exception as e:
            results.append({
                "provider":   provider,
                "model":      resolved_model,
                "error":      f"{type(e).__name__}: {e}",
                "elapsed_s":  round(time.time() - c_t0, 2),
            })
            audit.log(
                "pressure_test.provider_fail",
                index=idx, provider=provider, model=resolved_model,
                error=f"{type(e).__name__}: {e}",
            )

    consensus = _consensus_from_results(results)
    elapsed = round(time.time() - t0, 2)
    audit.log(
        "pressure_test.done",
        direction=consensus["direction"],
        agree=consensus["agree"], total=consensus["total"],
        all_agree=consensus["all_agree"], elapsed_s=elapsed,
    )
    return {
        "symbol": symbol, "timeframe": timeframe,
        "capture": {"tf": cap["tf"], "path": cap["path"]},
        "results": results,
        "consensus": consensus,
        "elapsed_s": elapsed,
    }


def _consensus_from_results(results: list[dict]) -> dict:
    """Aggregate per-provider results into a consensus shape.

    `direction` is the most-voted signal among providers that returned
    one (errored providers don't vote). `agree` is how many providers
    voted with the majority. Spread fields are computed only across
    providers that agreed on direction AND have numeric levels —
    showing "entry range 26,800-26,842" is only meaningful when the
    endpoints are the same direction."""
    signals = [r.get("signal") for r in results if r.get("signal")]
    if not signals:
        return {
            "direction": None, "agree": 0, "total": 0,
            "all_agree": False,
            "entry_spread": None, "stop_spread": None, "tp_spread": None,
        }
    # Pick the most common signal. Tie-break doesn't matter for UI
    # ("split decision" is the story regardless of which way the tie
    # falls).
    from collections import Counter
    counter = Counter(signals)
    direction, agree = counter.most_common(1)[0]

    agreeing = [
        r for r in results
        if r.get("signal") == direction
        and isinstance(r.get("entry"), (int, float))
        and isinstance(r.get("stop"), (int, float))
        and isinstance(r.get("tp"), (int, float))
    ]
    def spread(key):
        vals = [r[key] for r in agreeing]
        return round(max(vals) - min(vals), 2) if len(vals) >= 2 else None

    return {
        "direction": direction,
        "agree": agree,
        "total": len(signals),
        "all_agree": agree == len(signals),
        "entry_spread": spread("entry"),
        "stop_spread": spread("stop"),
        "tp_spread": spread("tp"),
    }


async def analyze_chart(
    symbol: str,
    *,
    timeframe: str = DEFAULT_TIMEFRAME,
    provider: str = "chatgpt_web",
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Run a single-timeframe analysis and return the structured result.

    Captures the chart at `timeframe`, sends one vision-LLM turn, parses
    the JSON response, and saves the generated pine script to disk.
    Applying the pine to the chart is a separate explicit action.

    Providers:
      * ``chatgpt_web`` (default) — drives chatgpt.com in the attached
        Chrome, uses your ChatGPT subscription (no API key), ~15-40s
      * ``claude_web`` — drives claude.ai in the attached Chrome, uses
        your Max subscription (no API key), ~20-30s
      * ``anthropic`` — Claude API, requires ANTHROPIC_API_KEY, ~10s
      * ``ollama`` — local, $0, ~85s on gemma4:31b
    """
    if provider not in ("anthropic", "ollama", "claude_web", "chatgpt_web"):
        raise ValueError(
            f"unknown provider {provider!r}; "
            "valid: anthropic, ollama, claude_web, chatgpt_web"
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
    elif provider == "chatgpt_web":
        raw, usage, cost = await _call_chatgpt_web(cap, symbol, tf, resolved_model)
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

    # Replace the LLM's pine with a deterministic template built from
    # the parsed numeric levels. The LLM tends to write top-level
    # `line.new`/`label.new` that fire every bar and get culled by
    # Pine's default max-lines/max-labels limits — `_build_levels_pine`
    # uses `hline` + `var` + `barstate.islast` so the overlay is
    # stable and actually visible on the chart.
    pine_code = _build_levels_pine(
        symbol,
        parsed.get("signal"),
        parsed.get("entry"),
        parsed.get("stop"),
        parsed.get("tp"),
    ) or parsed.get("pine_code")  # fall back to LLM pine only if we
                                   # couldn't build one (missing levels)
    pine_path: Path | None = None
    if pine_code:
        pine_path = _save_pine(symbol, pine_code)

    result = {
        "symbol": symbol,
        "timeframe": tf,
        "signal": parsed.get("signal"),
        "confidence": parsed.get("confidence"),
        "entry": parsed.get("entry"),
        "stop": parsed.get("stop"),
        "tp": parsed.get("tp"),
        "rationale": parsed.get("rationale"),
        "unknowns": _sanitize_unknowns(parsed.get("unknowns")),
        # `pine_code` in the result mirrors what was written to disk —
        # so exports (JSON/MD/PDF) and the UI show the SAME script
        # that apply-pine will paste into TradingView.
        "pine_code": pine_code,
        "pine_path": str(pine_path) if pine_path else None,
        "capture": {"tf": cap["tf"], "path": cap["path"]},
        "provider": provider,
        "model": resolved_model,
        "usage": usage,
        "cost_usd": cost,
        "elapsed_s": round(time.time() - t0, 2),
        "llm_elapsed_s": round(llm_elapsed, 2),
        # Canonical local-time ISO timestamp of when the analysis
        # completed. Used by the UI to show when the prediction was
        # made and by the export endpoint to stamp filenames.
        "iso_ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
    }
    # Persist the decision for calibration (Phase 1 — see
    # HumanOS Product thesis - Trading.md). Failure is logged via audit
    # but never raised — a broken DB must not fail the analysis flow.
    from . import decision_log
    decision_log.log_decision(result, audit.current_request_id.get() or "")

    # Embed this (provider, model, confidence_bucket)'s historical track
    # so the UI can render the inline calibration chip beside the live
    # confidence number. Silent-fail — a broken read shouldn't withhold
    # the analysis result.
    try:
        result["calibration"] = decision_log.bucket_track(
            provider, resolved_model, result.get("confidence"),
        )
    except Exception as e:
        audit.log("decision_log.bucket_track_fail", error=f"{type(e).__name__}: {e}")
        result["calibration"] = None

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
    provider: str = "chatgpt_web",
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Run a 10-timeframe deep analysis and return the integrated result.

    Captures all 10 TFs (sequential CDP), then one multi-image LLM call
    that produces: an *optimal_tf* recommendation, consolidated entry/
    stop/tp at that TF, a per-TF breakdown, and a Pine v6 *strategy*
    script (not just an indicator) so the setup can be backtested.

    Defaults to chatgpt_web — same provider as single-TF Analyze, so
    the deck doesn't flip backends between the two modes. Override via
    the UI's provider dropdown or by passing `provider=` explicitly.
    """
    if provider not in ("anthropic", "ollama", "claude_web", "chatgpt_web"):
        raise ValueError(
            f"unknown provider {provider!r}; "
            "valid: anthropic, ollama, claude_web, chatgpt_web"
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
    elif provider == "chatgpt_web":
        raw, usage, cost = await _call_chatgpt_web_deep(
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

    # Same pine-overlay treatment as single-TF: discard the LLM's
    # strategy script (which suffers from the same per-bar
    # line.new/label.new culling bug) and use the deterministic
    # levels template. This unifies the apply-pine workflow across
    # Analyze and Deep — both produce a clean Entry/Stop/TP overlay
    # that survives Pine's max_lines/max_labels limits, and the
    # post-apply screenshot attaches to the decision row identically
    # for both modes. Falls back to LLM pine only if levels are missing.
    pine_code = _build_levels_pine(
        symbol,
        parsed.get("signal"),
        parsed.get("entry"),
        parsed.get("stop"),
        parsed.get("tp"),
    ) or parsed.get("pine_code")
    pine_path: Path | None = None
    if pine_code:
        pine_path = _save_pine(symbol, pine_code)

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
        "unknowns": _sanitize_unknowns(parsed.get("unknowns")),
        "signal": parsed.get("signal"),
        "confidence": parsed.get("confidence"),
        "entry": parsed.get("entry"),
        "stop": parsed.get("stop"),
        "tp": parsed.get("tp"),
        "rationale": parsed.get("rationale"),
        "per_tf": parsed.get("per_tf") or [],
        # `pine_code` mirrors what's on disk (the deterministic levels
        # template, NOT the LLM strategy) so the UI's apply-pine button
        # and the JSON/MD/PDF exporters all see the same script.
        "pine_code": pine_code,
        "pine_path": str(pine_path) if pine_path else None,
        "captures": [{"tf": c["tf"], "path": c["path"]} for c in captures],
        "provider": provider,
        "model": resolved_model,
        "usage": usage,
        "cost_usd": cost,
        "elapsed_s": round(time.time() - t0, 2),
        "llm_elapsed_s": round(llm_elapsed, 2),
        "iso_ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
    }
    # Same calibration hook as single-TF — mode="deep" lets the
    # reconciler and calibration queries slice on the decision shape.
    from . import decision_log
    decision_log.log_decision(result, audit.current_request_id.get() or "")

    try:
        result["calibration"] = decision_log.bucket_track(
            provider, resolved_model, result.get("confidence"),
        )
    except Exception as e:
        audit.log("decision_log.bucket_track_fail", error=f"{type(e).__name__}: {e}")
        result["calibration"] = None

    audit.log(
        "analyze.done", mode="deep",
        optimal_tf=result["optimal_tf"],
        signal=result["signal"], confidence=result["confidence"],
        entry=result["entry"], stop=result["stop"], tp=result["tp"],
        cost_usd=cost, elapsed_s=result["elapsed_s"],
        pine_path=result["pine_path"],
    )
    return result
