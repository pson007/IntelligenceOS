"""AI Visual Coach — propose additive chart visuals from the live chart.

Workflow:
  1. Capture a screenshot of the active TradingView chart.
  2. (Optionally) load today's pre-session forecast JSON to give the
     LLM the structural context it needs to propose ADDITIVE visuals
     instead of duplicating the forecast overlay's drawings.
  3. Send (screenshot + forecast context) to a vision LLM with a strict
     JSON schema for proposed visuals.
  4. Server-assign each proposal a stable id (`v_xxxxxxxx`) so the UI
     can accept/reject individual proposals and the Sketchpad Pine
     composer can name its inputs deterministically.

Output of `analyze_chart_for_visuals` is the proposals dict — NOT the
sketchpad. Accepting proposals into the sketchpad is a separate step
(handled by ui_server endpoints).

Provider dispatch mirrors `analyze_mtf.py`. We reuse the underlying
provider client modules (`claude_web`, `chatgpt_web`, etc.) with the
Coach's own system prompt rather than going through `analyze_mtf`'s
`_call_*` wrappers — those bake in the trade-recommendation prompt
and would force a JSON-shape mismatch.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import analyze_mtf as _analyze_mtf  # for _parse_json + _resolve_model
from . import chart
from .lib import audit

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


_FORECASTS_DIR = Path(__file__).resolve().parent.parent / "forecasts"
_PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "sketchpad"

# Threads — multi-turn brainstorm sessions. Stateless on the provider
# side (every turn replays the full conversation as one prompt) so we
# don't need to hold a Playwright tab open across HTTP requests.
# Bounded by TTL — a forgotten chat won't leak forever.
_THREADS: dict[str, dict] = {}
_THREAD_TTL_S = 60 * 60 * 4  # 4 hours — covers a full trading day session

_VALID_COLORS = {
    "red", "green", "yellow", "blue", "aqua",
    "orange", "purple", "white", "gray",
}
_VALID_TYPES = {"level", "vline", "cross_alert"}

# Chat is only meaningful for providers we can drive multiple times in
# a session. claude_web / chatgpt_web are stateless replay; ollama can
# do native multi-turn but lacks a strong VL model in our local
# inventory; anthropic would be cleanest but the user has no API key.
_CHAT_VALID_PROVIDERS = {"claude_web", "chatgpt_web", "anthropic", "ollama"}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an elite day-trading analyst.

You receive:
  * ONE chart screenshot at the trader's currently-active timeframe.
  * (Optionally) the morning's pre-session forecast for this day —
    bias, key levels, GOAT window, invalidation conditions.

Your job has two parts:

  PART A — TRADE SIGNAL: ALWAYS propose ONE actionable call:
    * "Long"  — buy now with specific entry / stop / take-profit prices
    * "Short" — sell now with specific entry / stop / take-profit prices
    * "Hold"  — no trade right now (levels may be null OR hypothetical)

  PART B — ADDITIVE VISUALS: 0-6 supporting chart visuals (levels,
  vlines, cross alerts) that help the trader navigate the rest of the
  session. These are INDEPENDENT of the trade signal — useful structure
  even when the signal is Hold.

You may emit three visual types:

  1. "level"       — horizontal price line at a specific price.
                     Optionally fires a 2-sided cross alert.
  2. "vline"       — vertical time marker at a specific HH:MM (ET) on
                     today's date. Use for scheduled events.
  3. "cross_alert" — fires an alert when CLOSE crosses a price in a
                     SPECIFIC direction (above OR below). Includes a
                     dashed reference line at that price.

DO NOT DUPLICATE — the Forecast Overlay (separate indicator already
on the chart) already draws all of these:
  * Session OPEN price line.
  * Close-target zone (TP1 / TP2 dashed lines).
  * Morning low/high stop / invalidation level (locks at 10:00 ET).
  * Prior-day H / L / C (intraday pivots).
  * Session-anchored VWAP and ±1σ bands.
  * Initial Balance high/low (09:30–10:30 range).
  * Money Print time markers (vlines at 10:00, 12:00, 14:00, 16:00 ET).
  * Session phase tints, GOAT background tint.

Propose only ADDITIVE visuals: supply/demand the chart is currently
forming, intraday swing highs/lows the forecast didn't anticipate,
scheduled-event vlines NOT in the standard set (FOMC, CPI, NFP, FED
SPEAK), and conditional alerts the forecast overlay doesn't already
have.

Output STRICTLY a single JSON object, no commentary, no markdown
fences:

{
  "context_read": "1-2 sentences — what you see on the chart. Name specific structural features.",
  "signal": {
    "side":       "Long" | "Short" | "Hold",
    "entry":      <number | null — required when side ∈ {Long, Short}>,
    "stop":       <number | null — required when side ∈ {Long, Short}>,
    "tp":         <number | null — required when side ∈ {Long, Short}>,
    "rationale":  "1-2 sentences — why this side, why these levels.",
    "confidence": "low" | "med" | "high"
  },
  "visuals": [
    {
      "type": "level" | "vline" | "cross_alert",
      "label": "≤ 40 chars; chart-ready, e.g. 'supply rejection x3'",
      "color": "red" | "green" | "yellow" | "blue" | "aqua" | "orange" | "purple" | "white" | "gray",
      "rationale": "1 sentence — WHY this visual matters now.",
      "confidence": "low" | "med" | "high",
      "price":          <required for level + cross_alert: number>,
      "alert_on_cross": <optional for level: bool, default false>,
      "time_et":        <required for vline: "HH:MM" 24-hour ET>,
      "direction":      <required for cross_alert: "above" | "below">
    }
  ],
  "skip_rationale": null
}

Signal rules:
  * Long / Short MUST have all three numeric levels — never null.
  * For Long: entry < tp AND entry > stop (entry between stop and tp).
  * For Short: entry > tp AND entry < stop.
  * Risk : reward should be at least 1 : 1.5; aim for 1 : 2 or better.
    The system displays R:R; a low R:R weakens the call.
  * Hold: entry/stop/tp may be null, OR set to hypothetical "if-then"
    levels (e.g. "if it reclaims X, this becomes a Long with entry X,
    stop Y, tp Z"). Use null if no such conditional exists.
  * The trader's morning forecast (if shown above) is the structural
    plan — your signal can align with it OR call out divergence.

If you have nothing additive to propose for the visuals list, set
`skip_rationale` to a 1-sentence explanation and emit `visuals: []`.
The signal field is still required even when visuals is empty.

Color semantics — match the visual's role:
  * red    — invalidation, supply, broken-thesis alerts
  * green  — confirmation, demand, target-extend alerts
  * yellow — scheduled events, high-attention vlines
  * aqua   — neutral pivots, value-area highs/lows
  * orange — contrarian, mean-reversion zones
  * purple — institutional levels (auction, prior-week extremes)

Be conservative — 2-4 visuals is a typical good answer. 6 is the cap.
Empty `visuals: []` with a `skip_rationale` is honest when the
forecast overlay already covers what matters.
"""


def _format_forecast_block(forecast: dict | None) -> str:
    """Render the parts of a pre-session forecast JSON the Coach needs.

    Pasted as a context block in the user message — much smaller than
    the full JSON (which weighs ~15KB and has fields irrelevant to a
    visual-proposal task)."""
    if not forecast:
        return "## NO FORECAST FOR TODAY — propose visuals from the chart alone."
    pred  = forecast.get("predictions") or {}
    goat  = forecast.get("probable_goat") or {}
    bias  = forecast.get("tactical_bias") or {}
    tags  = forecast.get("prediction_tags") or {}
    canary = forecast.get("canary") or {}

    lines = ["## TODAY'S PRE-SESSION FORECAST (already drawn on chart)"]

    direction = pred.get("direction")
    conf      = pred.get("direction_confidence")
    if direction:
        lines.append(f"- Direction: **{direction}** (confidence {conf or '?'})")

    pct_lo = pred.get("predicted_net_pct_lo")
    pct_hi = pred.get("predicted_net_pct_hi")
    if pct_lo is not None and pct_hi is not None:
        lines.append(f"- Predicted net %: {pct_lo:+.2f}% to {pct_hi:+.2f}%")

    if pred.get("open_type"):
        lines.append(f"- Open type: {pred['open_type']}")
    if pred.get("structure"):
        lines.append(f"- Expected structure: {pred['structure']}")

    if goat.get("direction") and goat.get("time_window"):
        lines.append(f"- GOAT: {goat['direction']} in {goat['time_window']} window")

    if bias.get("bias"):
        lines.append(f"- Tactical bias: {bias['bias']}")
    if bias.get("invalidation"):
        lines.append(f"- Invalidation: {bias['invalidation']}")

    if tags.get("afternoon_drive"):
        lines.append(f"- Afternoon drive expectation: {tags['afternoon_drive']}")

    canary_thesis = canary.get("thesis_summary") if isinstance(canary, dict) else None
    if canary_thesis:
        lines.append(f"- Canary thesis: {canary_thesis}")

    return "\n".join(lines)


def _user_text(symbol: str, timeframe: str, forecast_block: str) -> str:
    now_et = time.strftime("%H:%M", time.localtime())  # local; the
    # M3 Mac is set to ET so this is fine. If the user moves the
    # machine, the zoneinfo import would be the surgical fix.
    return (
        f"Symbol: {symbol}\n"
        f"Timeframe: {timeframe}\n"
        f"Now: {now_et} (local; expect ET)\n\n"
        f"{forecast_block}\n\n"
        "Analyze the screenshot. Propose 0-6 ADDITIVE visuals.\n"
        "Return the JSON object only."
    )


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


async def _capture(symbol: str, timeframe: str) -> dict:
    """Single-frame chart capture. Same shape as analyze_mtf._capture but
    we don't need indicator values — the Coach's job is visual structure,
    not exact numerical reads."""
    audit.log("coach.capture_start", symbol=symbol, tf=timeframe)
    shot = await chart.screenshot(symbol, timeframe, None, area="chart")
    audit.log("coach.captured", symbol=symbol, tf=timeframe, path=shot["path"])
    return {
        "tf": timeframe, "path": shot["path"],
        "symbol": shot.get("symbol"), "interval": shot.get("interval"),
    }


def _image_as_b64(path: str) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


# ---------------------------------------------------------------------------
# Provider calls — reuse underlying client modules with the Coach prompt.
# Each returns (raw_text, usage_dict, cost_usd) — same contract as the
# `_call_*` wrappers in analyze_mtf.py, just with our prompt baked in.
# ---------------------------------------------------------------------------


async def _call_claude_web(image_path: str, system_prompt: str, user_text: str,
                           model: str | None) -> tuple[str, dict, float]:
    from .claude_web import analyze_via_claude_web
    return await analyze_via_claude_web(image_path, system_prompt, user_text, model=model)


async def _call_chatgpt_web(image_path: str, system_prompt: str, user_text: str,
                            model: str | None) -> tuple[str, dict, float]:
    from .chatgpt_web import analyze_via_chatgpt_web
    return await analyze_via_chatgpt_web(image_path, system_prompt, user_text, model=model)


async def _call_anthropic(image_path: str, system_prompt: str, user_text: str,
                          model: str) -> tuple[str, dict, float]:
    from anthropic import AsyncAnthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in tradingview/.env")
    client = AsyncAnthropic(api_key=api_key)
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _image_as_b64(image_path),
            },
        },
        {"type": "text", "text": user_text},
    ]
    resp = await client.messages.create(
        model=model, max_tokens=4000, system=system_prompt,
        messages=[{"role": "user", "content": content}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "\n".join(text_parts)
    usage = {
        "input_tokens":  getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
    }
    cost = _analyze_mtf._anthropic_cost(usage, model)
    return text, usage, cost


async def _call_openai_compat(image_path: str, system_prompt: str, user_text: str,
                              model: str, base_url: str | None
                              ) -> tuple[str, dict, float]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        base_url=base_url or "http://localhost:11434/v1",
        api_key=os.environ.get("OPENAI_API_KEY", "sk-local"),
    )
    content = [
        {"type": "text", "text": user_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{_image_as_b64(image_path)}"},
        },
    ]
    resp = await client.chat.completions.create(
        model=model, max_tokens=4000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": content},
        ],
    )
    text = resp.choices[0].message.content or ""
    u = getattr(resp, "usage", None)
    usage = {
        "input_tokens":  getattr(u, "prompt_tokens", 0)     if u else 0,
        "output_tokens": getattr(u, "completion_tokens", 0) if u else 0,
    }
    return text, usage, 0.0


# ---------------------------------------------------------------------------
# Proposal sanitization
# ---------------------------------------------------------------------------


def _new_visual_id() -> str:
    """8-char hex prefixed with `v_` — fits inside Pine identifier rules
    (alphanum + underscore, must start with letter/underscore) and is
    short enough to stamp into 5+ Pine identifiers per visual."""
    return f"v_{secrets.token_hex(4)}"


_VALID_SIDES = {"Long", "Short", "Hold"}


def _sanitize_signal(raw) -> dict | None:
    """Normalize the LLM's `signal` payload into a consistent shape.

    Returns the cleaned signal dict (with computed `r_r`) on success,
    or None if the payload is missing/garbage. Long/Short require all
    three numeric levels AND geometric consistency (entry between stop
    and tp on the correct side); a Long with stop > entry is silently
    coerced to Hold rather than rendered as an upside-down trade.
    """
    if not isinstance(raw, dict):
        return None
    side = str(raw.get("side") or "").strip().capitalize()
    if side not in _VALID_SIDES:
        return None

    confidence = (raw.get("confidence") or "med").strip().lower()
    if confidence not in ("low", "med", "high"):
        confidence = "med"
    rationale = str(raw.get("rationale") or "").strip()[:400]

    # Hold is the lenient case — levels optional. Long/Short require
    # all three numerics AND the right geometry, else demote to Hold.
    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    entry = _num(raw.get("entry"))
    stop  = _num(raw.get("stop"))
    tp    = _num(raw.get("tp"))

    if side in ("Long", "Short"):
        if entry is None or stop is None or tp is None:
            side = "Hold"
        elif side == "Long" and not (stop < entry < tp):
            side = "Hold"
        elif side == "Short" and not (tp < entry < stop):
            side = "Hold"

    r_r = None
    if side in ("Long", "Short") and entry is not None and stop is not None and tp is not None:
        risk = abs(entry - stop)
        reward = abs(tp - entry)
        if risk > 0:
            r_r = round(reward / risk, 2)

    return {
        "side":       side,
        "entry":      entry,
        "stop":       stop,
        "tp":         tp,
        "rationale":  rationale,
        "confidence": confidence,
        "r_r":        r_r,
    }


def _synthesize_trade_visuals(signal: dict | None) -> list[dict]:
    """Render an actionable signal (Long/Short with all three numeric
    levels) as three `level` visuals: ENTRY (yellow), STOP (red), TP
    (green). These prepend the proposals list so when the trader
    accepts them they flow through the standard sketchpad pipeline
    and become Pine on the chart.

    Hold signals — or Long/Short missing any level — return [] since
    there's nothing concrete to draw."""
    if not isinstance(signal, dict):
        return []
    side = signal.get("side")
    if side not in ("Long", "Short"):
        return []
    entry, stop, tp = signal.get("entry"), signal.get("stop"), signal.get("tp")
    if any(v is None for v in (entry, stop, tp)):
        return []

    rr = signal.get("r_r")
    rr_suffix = f" · {rr}R" if rr else ""
    confidence = signal.get("confidence") or "med"

    return [
        {"id": _new_visual_id(), "type": "level",
         "label": f"ENTRY {side.lower()}", "color": "yellow",
         "rationale": f"Coach signal · {side}{rr_suffix}",
         "confidence": confidence, "price": float(entry),
         "alert_on_cross": True, "role": "trade_entry"},
        {"id": _new_visual_id(), "type": "level",
         "label": "STOP", "color": "red",
         "rationale": "Coach signal · invalidation",
         "confidence": confidence, "price": float(stop),
         "alert_on_cross": True, "role": "trade_stop"},
        {"id": _new_visual_id(), "type": "level",
         "label": "TP", "color": "green",
         "rationale": "Coach signal · take-profit target",
         "confidence": confidence, "price": float(tp),
         "alert_on_cross": True, "role": "trade_tp"},
    ]


def _sanitize_visual(raw: dict) -> dict | None:
    """Validate one proposed visual against the schema. Returns None on
    invalid — caller filters Nones rather than raising, so a single
    malformed proposal doesn't drop the whole batch."""
    if not isinstance(raw, dict):
        return None
    vtype = (raw.get("type") or "").strip().lower()
    if vtype not in _VALID_TYPES:
        return None

    color = (raw.get("color") or "white").strip().lower()
    if color not in _VALID_COLORS:
        color = "white"

    label = str(raw.get("label") or "").strip()[:60]
    if not label:
        label = vtype  # fall back to the type so the chart isn't blank

    confidence = (raw.get("confidence") or "med").strip().lower()
    if confidence not in ("low", "med", "high"):
        confidence = "med"

    visual: dict[str, Any] = {
        "id":         _new_visual_id(),
        "type":       vtype,
        "label":      label,
        "color":      color,
        "rationale":  str(raw.get("rationale") or "").strip()[:280],
        "confidence": confidence,
    }

    if vtype == "level":
        try:
            visual["price"] = float(raw["price"])
        except (KeyError, TypeError, ValueError):
            return None
        visual["alert_on_cross"] = bool(raw.get("alert_on_cross"))

    elif vtype == "vline":
        time_et = (raw.get("time_et") or "").strip()
        if not re.match(r"^\d{1,2}:\d{2}$", time_et):
            return None
        try:
            hh_s, mm_s = time_et.split(":", 1)
            hh, mm = int(hh_s), int(mm_s)
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                return None
        except ValueError:
            return None
        visual["time_et"] = f"{hh:02d}:{mm:02d}"

    elif vtype == "cross_alert":
        try:
            visual["price"] = float(raw["price"])
        except (KeyError, TypeError, ValueError):
            return None
        direction = (raw.get("direction") or "").strip().lower()
        if direction not in ("above", "below"):
            return None
        visual["direction"] = direction

    return visual


def _persist_proposal(symbol: str, date: str, raw: str, parsed: dict,
                      visuals: list[dict], provider: str, model: str,
                      elapsed_s: float) -> None:
    """Append a record of the LLM call to the per-day proposals JSONL.

    Used later to bench provider quality on visual proposals (which
    visuals end up accepted vs rejected) and to debug bad proposals
    by replaying the raw response."""
    try:
        _PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", symbol)
        path = _PROPOSALS_DIR / f"{safe_sym}_{date}_proposals.jsonl"
        entry = {
            "ts":        time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "provider":  provider,
            "model":     model,
            "elapsed_s": round(elapsed_s, 2),
            "n_visuals": len(visuals),
            "context_read":   parsed.get("context_read"),
            "skip_rationale": parsed.get("skip_rationale"),
            "visuals":   visuals,
            "raw_head":  raw[:1000],
        }
        with path.open("a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        audit.log("coach.proposal_persist_fail",
                  err=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Forecast loader — best-effort, never raises
# ---------------------------------------------------------------------------


def _load_today_forecast(symbol: str, date: str) -> dict | None:
    """Find the pre-session forecast JSON for (symbol, date) or None.

    The forecasts/ convention strips non-alphanumerics, so MNQ1! lives
    on disk as MNQ1_<date>_pre_session.json. We try the stripped form
    first, then the literal form as a fallback for any legacy file."""
    stripped = re.sub(r"[^A-Za-z0-9]+", "", symbol)
    for name in (f"{stripped}_{date}_pre_session.json",
                 f"{symbol}_{date}_pre_session.json"):
        path = _FORECASTS_DIR / name
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception as e:
                audit.log("coach.forecast_read_fail",
                          path=str(path), err=f"{type(e).__name__}: {e}")
                return None
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def analyze_chart_for_visuals(
    symbol: str,
    *,
    timeframe: str = "5m",
    provider: str = "claude_web",
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Capture the chart, ask a vision LLM for additive visuals, return
    the proposals dict (with server-assigned ids).

    Returns shape:
        {
          "symbol":       str,
          "timeframe":    str,
          "provider":     str,
          "model":        str,
          "context_read": str,
          "visuals":      [ {id, type, label, color, rationale,
                             confidence, ...type-specific} ],
          "skip_rationale": str | None,
          "capture":      {tf, path},
          "elapsed_s":    float,
          "llm_elapsed_s": float,
          "iso_ts":       str,
        }
    """
    if provider not in ("anthropic", "ollama", "claude_web", "chatgpt_web"):
        raise ValueError(
            f"unknown provider {provider!r}; "
            "valid: anthropic, ollama, claude_web, chatgpt_web"
        )
    resolved_model = _analyze_mtf._resolve_model(provider, model)
    date = time.strftime("%Y-%m-%d", time.localtime())

    audit.log(
        "coach.start", symbol=symbol, timeframe=timeframe,
        provider=provider, model=resolved_model, date=date,
    )
    t0 = time.time()

    cap = await _capture(symbol, timeframe)
    forecast = _load_today_forecast(symbol, date)
    forecast_block = _format_forecast_block(forecast)
    user_text = _user_text(symbol, timeframe, forecast_block)

    audit.log(
        "coach.llm_request", provider=provider, model=resolved_model,
        forecast_loaded=forecast is not None,
    )
    llm_t0 = time.time()
    if provider == "claude_web":
        raw, usage, cost = await _call_claude_web(
            cap["path"], _SYSTEM_PROMPT, user_text, resolved_model,
        )
    elif provider == "chatgpt_web":
        raw, usage, cost = await _call_chatgpt_web(
            cap["path"], _SYSTEM_PROMPT, user_text, resolved_model,
        )
    elif provider == "anthropic":
        raw, usage, cost = await _call_anthropic(
            cap["path"], _SYSTEM_PROMPT, user_text, resolved_model,
        )
    else:
        raw, usage, cost = await _call_openai_compat(
            cap["path"], _SYSTEM_PROMPT, user_text, resolved_model, base_url,
        )
    llm_elapsed = time.time() - llm_t0

    try:
        parsed = _analyze_mtf._parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        # Reuse the same parse_failures dump pattern as analyze_mtf so
        # a bad coach response is debuggable without re-running the LLM.
        dump_dir = _PROPOSALS_DIR / "parse_failures"
        dump_dir.mkdir(parents=True, exist_ok=True)
        safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", symbol)
        ts = time.strftime("%Y%m%d-%H%M%S")
        dump_path = dump_dir / f"{safe_sym}_coach_{provider}_{ts}.txt"
        try:
            dump_path.write_text(raw, encoding="utf-8")
        except Exception:
            dump_path = None
        audit.log(
            "coach.parse_fail", error=str(e),
            raw_head=raw[:500], raw_len=len(raw),
            dump_path=str(dump_path) if dump_path else None,
        )
        raise RuntimeError(f"LLM returned invalid JSON: {e}") from e

    # Sanitize each proposed visual; drop the malformed ones rather than
    # rejecting the whole batch. Each survivor gets a fresh server-assigned
    # id so the UI / sketchpad pipeline can address them deterministically.
    raw_visuals = parsed.get("visuals") or []
    if not isinstance(raw_visuals, list):
        raw_visuals = []
    additive_visuals: list[dict] = []
    for v in raw_visuals[:6]:  # cap matches the prompt
        sanitized = _sanitize_visual(v)
        if sanitized:
            additive_visuals.append(sanitized)

    # Signal — Long/Short/Hold + entry/stop/tp. Synthesize 3 trade-level
    # visuals (entry/stop/tp) when actionable, prepended so the trader
    # sees them at the top of the proposals list ready to accept.
    signal = _sanitize_signal(parsed.get("signal"))
    trade_visuals = _synthesize_trade_visuals(signal)
    visuals = trade_visuals + additive_visuals

    elapsed = round(time.time() - t0, 2)

    # Spin up a chat thread seeded with this analysis. The user can
    # immediately follow up to brainstorm without re-capturing the
    # chart. Thread reuses the same screenshot for the full session.
    thread_id = _new_thread_id()
    context_read = str(parsed.get("context_read") or "").strip()
    skip_rationale = (str(parsed.get("skip_rationale")).strip()
                      if parsed.get("skip_rationale") else None)
    initial_assistant_text = _summarize_initial_response(
        context_read, visuals, skip_rationale, signal,
    )
    _THREADS[thread_id] = {
        "symbol":          symbol,
        "timeframe":       timeframe,
        "provider":        provider,
        "model":           resolved_model,
        "image_path":      cap["path"],
        "messages": [
            {"role": "user", "text": "(initial analyze: capture chart, propose additive visuals)"},
            {"role": "assistant", "text": initial_assistant_text,
             "visuals_proposed": [v["id"] for v in visuals]},
        ],
        "started_at":      time.time(),
        "last_activity":   time.time(),
        "n_turns":         1,
    }

    result = {
        "thread_id":      thread_id,
        "symbol":         symbol,
        "timeframe":      timeframe,
        "provider":       provider,
        "model":          resolved_model,
        "context_read":   context_read,
        "signal":         signal,
        "visuals":        visuals,
        "skip_rationale": skip_rationale,
        "capture":        {"tf": cap["tf"], "path": cap["path"]},
        "usage":          usage,
        "cost_usd":       cost,
        "elapsed_s":      elapsed,
        "llm_elapsed_s":  round(llm_elapsed, 2),
        "iso_ts":         time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
    }

    _persist_proposal(symbol, date, raw, parsed, visuals,
                      provider, resolved_model, elapsed)

    audit.log(
        "coach.done", n_visuals=len(visuals),
        provider=provider, model=resolved_model,
        signal_side=(signal or {}).get("side"),
        signal_rr=(signal or {}).get("r_r"),
        elapsed_s=elapsed, llm_elapsed_s=round(llm_elapsed, 2),
        cost_usd=cost, thread_id=thread_id,
    )
    return result


# ---------------------------------------------------------------------------
# Chat — multi-turn brainstorm on top of an Analyze run
#
# Stateless replay over browser-driven providers: every chat turn opens
# a fresh provider tab and sends the FULL conversation as one prompt.
# Slow (~30s/turn) but trivial to implement — no Playwright lifecycle
# management, no shared browser state across HTTP requests.
#
# When the chat reply contains visual proposals, they're emitted in a
# JSON code-fence the response prompt asks for and extracted server-side.
# Each extracted visual gets a fresh server-assigned id so it can be
# accept/rejected through the same `/api/sketchpad/.../accept` endpoint
# as the initial analyze proposals.
# ---------------------------------------------------------------------------


_CHAT_SYSTEM_PROMPT = _SYSTEM_PROMPT + """

== CHAT MODE ==

You are now in a multi-turn brainstorm with the trader. The conversation
transcript appears at the end of the user message. Respond to the LATEST
trader message conversationally — short, focused, no preamble.

CRITICAL — NEVER WRITE PINE CODE IN CHAT REPLIES.

A deterministic Pine composer downstream renders ANY visual you propose
into Pine v6 source automatically. You have ONE job: describe the visual
as STRUCTURED JSON. The system handles the Pine.

If the trader asks for "Pine for X" or "code a Pine that does Y" or
"write me a script", DO NOT emit ```pine``` blocks. Instead, describe
the visual as a JSON proposal — that proposal becomes Pine on the chart
the moment the trader accepts and applies it.

A chat reply may include EITHER OR BOTH of these structured updates,
embedded as a single JSON code fence (always with the `json` lang tag)
at the end of your message:

  * `new_signal` — to revise the trade signal (change side, adjust
    entry/stop/tp, or downgrade to Hold). Only emit when the chart or
    the user's input materially changes the call. Otherwise the
    previous signal stands.
  * `new_visuals` — to add new chart visuals (level / vline /
    cross_alert).

Schema (one or both keys; omit either when not updating):

```json
{
  "new_signal": {
    "side": "Long"|"Short"|"Hold",
    "entry": ..., "stop": ..., "tp": ...,
    "rationale": "...",
    "confidence": "low"|"med"|"high"
  },
  "new_visuals": [
    {"type": "level"|"vline"|"cross_alert",
     "label": "...", "color": "...",
     "rationale": "...", "confidence": "low"|"med"|"high",
     "price": ...,                    // required for level + cross_alert
     "alert_on_cross": true|false,   // optional for level
     "time_et": "HH:MM",             // required for vline
     "direction": "above"|"below"    // required for cross_alert
    }
  ]
}
```

Rules:
  * The fence MUST start with three backticks + the literal word `json`.
  * The fence body MUST be valid JSON parseable by `JSON.parse`.
  * Only include keys that are actually updating — most chat turns
    are pure discussion and need no fence at all.
  * NEVER emit ```pine``` or any other code-fence language. Pine is
    generated by the system from your JSON, not by you.
  * If the chart needs an indicator the three visual types (level /
    vline / cross_alert) can't express, say so in plain text and
    suggest the closest approximation — don't try to write Pine.

Trade signal rules in chat are the same as the initial analyze:
Long/Short require numeric entry/stop/tp; Hold may have null or
hypothetical levels; entry must be between stop and tp on the
appropriate side.

Visuals already accepted in earlier turns are NOT shown to you; trust
the user when they tell you what's already on the chart.

Keep replies tight (1-4 sentences typical). Avoid restating the trader's
message. Avoid markdown headers. The chart context never changes mid-
conversation — the original screenshot is still attached.
"""


_VISUAL_FENCE_RX = re.compile(
    r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.MULTILINE,
)
# Diagnostic fences — used to flag chat replies that contain Pine code
# instead of a structured JSON proposal. Helps catch prompt-engineering
# misses where the LLM ignores the "describe as JSON" rule.
_PINE_FENCE_RX = re.compile(r"```pine\b", re.IGNORECASE)
_ANY_FENCE_RX  = re.compile(r"```(\w+)?", re.IGNORECASE)


def _new_thread_id() -> str:
    return f"th_{secrets.token_hex(5)}"


def _summarize_initial_response(context_read: str, visuals: list[dict],
                                skip_rationale: str | None,
                                signal: dict | None = None) -> str:
    """Render the analyze result as the assistant's first chat message.

    Used to seed the thread so a chat turn that follows the initial
    Analyze has continuity (the LLM sees its own first response in the
    transcript)."""
    parts = [context_read or "(analyzed the chart)"]

    if signal and signal.get("side"):
        side = signal["side"]
        if side in ("Long", "Short") and signal.get("entry") is not None:
            rr_part = f" · {signal['r_r']}R" if signal.get("r_r") else ""
            parts.append(
                f"\n\nSignal: **{side}**{rr_part} "
                f"(confidence {signal.get('confidence') or '?'}) — "
                f"entry {signal['entry']:,.2f} · "
                f"stop {signal['stop']:,.2f} · "
                f"tp {signal['tp']:,.2f}"
            )
        else:
            parts.append(f"\n\nSignal: **Hold** ({signal.get('confidence') or '?'})")
        if signal.get("rationale"):
            parts.append(f"\n{signal['rationale']}")

    if visuals:
        bullets = []
        for v in visuals:
            if v["type"] == "level":
                bullets.append(f"  - level @ {v['price']:,.2f} — {v['label']}")
            elif v["type"] == "vline":
                bullets.append(f"  - vline {v['time_et']} ET — {v['label']}")
            elif v["type"] == "cross_alert":
                arrow = "↑" if v["direction"] == "above" else "↓"
                bullets.append(
                    f"  - cross_alert {arrow} {v['price']:,.2f} — {v['label']}"
                )
        parts.append(f"\n\nProposed {len(visuals)} visuals:\n" + "\n".join(bullets))
    elif skip_rationale:
        parts.append(f"\n\nNo additive visuals: {skip_rationale}")
    return "".join(parts)


def _extract_chat_payload(text: str) -> tuple[str, list[dict], dict | None]:
    """Parse a chat reply for structured updates and return
    (cleaned_text, new_visuals, new_signal).

    Tolerant of common LLM formatting variations: ```json``` and bare
    ``` are both recognized; extra text before/after the fence is
    preserved in `cleaned_text` so the displayed reply still reads well.
    Multiple fences are merged — last-wins for `new_signal`, accumulate
    for `new_visuals`.
    """
    matches = list(_VISUAL_FENCE_RX.finditer(text))
    if not matches:
        return text, [], None

    new_visuals: list[dict] = []
    new_signal: dict | None = None
    for m in matches:
        raw_json = m.group(1)
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue

        candidates = parsed.get("new_visuals")
        if isinstance(candidates, list):
            for v in candidates[:6]:
                sanitized = _sanitize_visual(v)
                if sanitized:
                    new_visuals.append(sanitized)

        sig_candidate = parsed.get("new_signal")
        if isinstance(sig_candidate, dict):
            sanitized_sig = _sanitize_signal(sig_candidate)
            if sanitized_sig:
                new_signal = sanitized_sig  # last fence wins

    cleaned = _VISUAL_FENCE_RX.sub("", text).strip()
    return cleaned, new_visuals, new_signal


# Back-compat shim — older smoke tests + callers expect the 2-tuple
# shape. Internal code uses _extract_chat_payload directly.
def _extract_chat_visuals(text: str) -> tuple[str, list[dict]]:
    cleaned, visuals, _signal = _extract_chat_payload(text)
    return cleaned, visuals


def _build_chat_user_text(thread: dict, latest_message: str) -> str:
    """Render the conversation as a single prompt body for a stateless
    provider call.

    Format intentionally simple — `[user] ... [assistant] ...` — because
    we're not relying on the provider's native chat structure (each turn
    opens a fresh tab; no real chat session exists)."""
    forecast = _load_today_forecast(
        thread["symbol"],
        time.strftime("%Y-%m-%d", time.localtime(thread["started_at"])),
    )
    forecast_block = _format_forecast_block(forecast)

    transcript_lines = []
    for m in thread["messages"]:
        role = m.get("role", "user")
        text = m.get("text", "").strip()
        if not text:
            continue
        transcript_lines.append(f"[{role}]\n{text}")
    transcript_lines.append(f"[user]\n{latest_message.strip()}")
    transcript = "\n\n".join(transcript_lines)

    return (
        f"Symbol: {thread['symbol']}\n"
        f"Timeframe: {thread['timeframe']}\n"
        f"Now: {time.strftime('%H:%M', time.localtime())} (local; expect ET)\n\n"
        f"{forecast_block}\n\n"
        "== CONVERSATION SO FAR ==\n"
        f"{transcript}\n\n"
        "Respond to the LATEST [user] message. Embed any new visuals in "
        "a `new_visuals` JSON code-fence per the chat-mode instructions."
    )


def _purge_old_threads() -> None:
    """Drop threads inactive longer than TTL. Called opportunistically
    on each chat turn — proportional to activity, no background sweeper."""
    cutoff = time.time() - _THREAD_TTL_S
    stale = [tid for tid, t in _THREADS.items()
             if (t.get("last_activity") or 0) < cutoff]
    for tid in stale:
        _THREADS.pop(tid, None)


def get_thread(thread_id: str) -> dict | None:
    """Return a serializable view of the thread, or None if not found.
    The image_path is exposed so the UI can show what the LLM is
    looking at; the in-memory `_task` (if any) is omitted."""
    t = _THREADS.get(thread_id)
    if not t:
        return None
    return {
        "thread_id":     thread_id,
        "symbol":        t["symbol"],
        "timeframe":     t["timeframe"],
        "provider":      t["provider"],
        "model":         t["model"],
        "image_path":    t.get("image_path"),
        "messages":      list(t["messages"]),
        "started_at":    t["started_at"],
        "last_activity": t["last_activity"],
        "n_turns":       t["n_turns"],
    }


def _persist_chat_turn(symbol: str, date: str, thread_id: str,
                       n_turns: int, message: str, raw: str,
                       cleaned_reply: str, new_visuals: list[dict],
                       provider: str, model: str, elapsed_s: float,
                       diagnostics: dict) -> None:
    """Append a record of one chat turn to a per-day JSONL.

    Used to debug "the LLM said X but extraction returned 0 visuals"
    — without this, the only post-mortem signal is the audit log,
    which only stores summary counts."""
    try:
        _PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", symbol)
        path = _PROPOSALS_DIR / f"{safe_sym}_{date}_chat.jsonl"
        entry = {
            "ts":          time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "thread_id":   thread_id,
            "n_turns":     n_turns,
            "provider":    provider,
            "model":       model,
            "elapsed_s":   round(elapsed_s, 2),
            "user_msg":    message,
            "raw_reply":   raw,
            "cleaned_reply": cleaned_reply,
            "n_new_visuals": len(new_visuals),
            "new_visual_ids": [v["id"] for v in new_visuals],
            **diagnostics,
        }
        with path.open("a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        audit.log("coach.chat_persist_fail",
                  err=f"{type(e).__name__}: {e}")


async def chat_turn(thread_id: str, message: str) -> dict:
    """Send one user message into a chat thread and return the assistant
    reply + any new visual proposals extracted from the reply.

    Replays the full conversation transcript as a single prompt to the
    same provider/model the thread was started with. Slow but stateless
    — no browser session lifecycle to manage.
    """
    _purge_old_threads()

    thread = _THREADS.get(thread_id)
    if not thread:
        raise KeyError(f"unknown thread_id {thread_id!r}")

    if not message or not message.strip():
        raise ValueError("message is required")

    provider = thread["provider"]
    model = thread["model"]
    image_path = thread["image_path"]

    audit.log(
        "coach.chat_start", thread_id=thread_id,
        n_turns=thread["n_turns"], provider=provider, model=model,
        msg_len=len(message),
    )
    t0 = time.time()
    user_text = _build_chat_user_text(thread, message)

    if provider == "claude_web":
        raw, _usage, _cost = await _call_claude_web(
            image_path, _CHAT_SYSTEM_PROMPT, user_text, model,
        )
    elif provider == "chatgpt_web":
        raw, _usage, _cost = await _call_chatgpt_web(
            image_path, _CHAT_SYSTEM_PROMPT, user_text, model,
        )
    elif provider == "anthropic":
        raw, _usage, _cost = await _call_anthropic(
            image_path, _CHAT_SYSTEM_PROMPT, user_text, model,
        )
    else:
        raw, _usage, _cost = await _call_openai_compat(
            image_path, _CHAT_SYSTEM_PROMPT, user_text, model, None,
        )
    elapsed = time.time() - t0

    cleaned_reply, new_visuals_only, new_signal = _extract_chat_payload(raw)

    # When the chat proposes a new actionable signal, synthesize the
    # entry/stop/tp trade-level visuals and merge them into the
    # new_visuals list — same shape as the initial Analyze, so the UI
    # treats them uniformly.
    new_trade_visuals = _synthesize_trade_visuals(new_signal)
    new_visuals = new_trade_visuals + new_visuals_only

    # Diagnostics — quick flags so we can grep the audit log for the
    # exact failure mode without reading the persisted JSONL.
    fence_kinds = [m.group(1) or "(none)" for m in _ANY_FENCE_RX.finditer(raw)]
    diagnostics = {
        "has_pine_fence": bool(_PINE_FENCE_RX.search(raw)),
        "has_json_fence": any(k.lower() == "json" for k in fence_kinds),
        "fence_kinds":    fence_kinds[:8],
        "has_new_signal": new_signal is not None,
        "raw_head":       raw[:600],
    }

    # Append both turns to the thread. The user message goes in BEFORE
    # the assistant's reply so the next turn's transcript is in order.
    thread["messages"].append({"role": "user", "text": message.strip()})
    thread["messages"].append({
        "role": "assistant",
        "text": cleaned_reply or "(empty reply)",
        "visuals_proposed": [v["id"] for v in new_visuals],
        "signal_updated":   new_signal,
    })
    thread["n_turns"] += 1
    thread["last_activity"] = time.time()

    # Persist + audit. The persisted JSONL is the post-mortem source of
    # truth; the audit log is the live-tail signal.
    date = time.strftime("%Y-%m-%d", time.localtime(thread["started_at"]))
    _persist_chat_turn(
        thread["symbol"], date, thread_id, thread["n_turns"],
        message, raw, cleaned_reply, new_visuals,
        provider, model, elapsed, diagnostics,
    )

    audit.log(
        "coach.chat_done", thread_id=thread_id,
        elapsed_s=round(elapsed, 2),
        n_new_visuals=len(new_visuals),
        new_signal_side=(new_signal or {}).get("side"),
        reply_len=len(cleaned_reply),
        has_pine_fence=diagnostics["has_pine_fence"],
        has_json_fence=diagnostics["has_json_fence"],
        fence_kinds=diagnostics["fence_kinds"],
    )

    return {
        "thread_id":   thread_id,
        "reply":       cleaned_reply,
        "new_visuals": new_visuals,
        "new_signal":  new_signal,
        "n_turns":     thread["n_turns"],
        "elapsed_s":   round(elapsed, 2),
    }
