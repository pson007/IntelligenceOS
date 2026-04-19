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


_MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
    "haiku":  "claude-haiku-4-5",
}


def _resolve_model(provider: str, model: str | None) -> str:
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

    Defaults to ``ollama`` so a full analysis costs $0. Pass
    ``provider="anthropic"`` explicitly to opt into Claude (requires
    ANTHROPIC_API_KEY).
    """
    if provider not in ("anthropic", "ollama"):
        raise ValueError(
            f"unknown provider {provider!r}; valid: anthropic, ollama"
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
    else:
        raw, usage, cost = await _call_openai_compat(
            cap, symbol, tf, resolved_model, base_url,
        )
    llm_elapsed = time.time() - llm_t0

    try:
        parsed = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        audit.log("analyze.parse_fail", error=str(e), raw_head=raw[:500])
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
