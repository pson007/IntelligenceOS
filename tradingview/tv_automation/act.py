"""Vision-loop driver — `tv act "<goal>"`.

Wraps the existing `describe-screen` / `click-label` / `click-at`
primitives in an LLM-in-loop: each iteration takes a screenshot,
sends (goal, inventory, screenshot, history) to the configured LLM,
parses the returned decision, executes one atomic action, loops
until `done`.

This is Phase 1 of VISION_LOOP_PLAN.md — the "see → understand →
choose → act → verify" cycle with an LLM in the inner loop.

Three providers are supported:
  - anthropic  — Claude via the Anthropic SDK (requires ANTHROPIC_API_KEY)
  - ollama     — any Ollama model via its OpenAI-compatible endpoint
                 (default http://localhost:11434/v1, no key)
  - mlx        — any mlx_lm.server / mlx-vlm server (OpenAI-compatible,
                 default http://localhost:8080/v1, no key)

Vision is on by default for `anthropic`; off by default for local
providers (they're usually text-only unless you pulled a VL model).
Pass `--vision` to force-include the screenshot on local providers.

CLI:
    tv act "open the watchlist sidebar"                          # anthropic default
    tv act "add SPY" --provider ollama --model qwen3.5:27b       # local text-only
    tv act "open alerts" --provider ollama --model qwen2.5vl:7b --vision
    tv act "<goal>" --max-steps 15 --max-cost-usd 1.00
    tv act "<goal>" --read-only         # refuses mutating actions
    tv act "<goal>" --dry-run           # model decides, nothing executes
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import chart
from .lib import audit
from .lib.cli import run
from .lib.errors import GoalUnachievableError, LoopBudgetExceededError

# Load .env at module import so ANTHROPIC_API_KEY is available whether
# invoked from the tv shim, `python -m`, or anywhere else.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# Per-million-token (input, output) USD pricing for Anthropic. Approximate
# — enough to drive the budget guard, not invoice-accurate. Local
# providers (ollama, mlx) are zero-cost; the budget guard is a no-op.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-haiku-4-5":  (0.80, 4.0),
}
_MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
    "haiku":  "claude-haiku-4-5",
}

# Provider defaults: (base_url, default_model, supports_cost, vision_default).
# vision_default=True means we include the screenshot unless --text-only.
# vision_default=False (local providers) means we OMIT the screenshot
# unless --vision is passed — most local models pulled aren't VL.
_PROVIDER_DEFAULTS: dict[str, dict] = {
    "anthropic": {
        "base_url": None,  # SDK default
        "default_model": "claude-sonnet-4-6",
        "has_cost": True,
        "vision_default": True,
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen3.5:27b",
        "has_cost": False,
        "vision_default": False,
        "api_key_env": None,  # ollama ignores the key
    },
    "mlx": {
        "base_url": "http://localhost:8080/v1",
        "default_model": None,  # user must specify — no stable default
        "has_cost": False,
        "vision_default": False,
        "api_key_env": None,
    },
}

_DEFAULT_PROVIDER = "anthropic"
_MAX_STEPS_DEFAULT = 10
_MAX_COST_DEFAULT = 0.50

# Per-call reserve used by the PRE-flight budget check. Rough upper bound
# for one turn's (inventory + history + screenshot) × max_tokens output
# so we refuse to fire a call whose worst-case cost would overshoot. Set
# conservatively; overshoot after this is measured in cents, not dollars.
_PER_CALL_RESERVE_USD = {
    "claude-sonnet-4-6": 0.05,
    "claude-opus-4-7":   0.30,
    "claude-haiku-4-5":  0.01,
}

# Prune the inventory before sending — the full list can hit 100+ items
# and the model's attention degrades on long structured lists. 30 is a
# balance: enough to cover most relevant targets, short enough to keep
# the model focused.
_INVENTORY_TOP_K = 30

_TRANSCRIPT_DIR = Path.home() / "Desktop" / "TradingView" / "act_transcripts"

# Actions we classify as "mutating" for --read-only mode. Conservative:
# any click_label whose query matches these patterns gets rejected, as
# does any press of Enter in a form-like context. Not a perfect filter
# (a `click_at` on a Buy button at known coords would slip through) but
# catches the obvious cases.
_MUTATING_QUERY_RE = re.compile(
    r"\b(buy|sell|submit|place|confirm|delete|remove|cancel|close|save)\b",
    re.IGNORECASE,
)


_SYSTEM_PROMPT = """You are a vision-driven UI driver for TradingView, \
running inside a headless automation loop.

Each turn you receive:
  - GOAL: a natural-language objective.
  - SCREENSHOT: a PNG of the current browser viewport.
  - INVENTORY: a JSON list of clickable elements, each with rect, \
center, and a label hint (data_name / aria_label / text).
  - HISTORY: prior turns' decisions and their results.

You output ONE action per turn as a single JSON object, nothing else:

  {"action": "click_label", "query": "<free-text element description>", "reason": "<why>"}
  {"action": "click_at",    "x": <int>, "y": <int>, "reason": "<why>"}
  {"action": "type",        "text": "<text>", "reason": "<why>"}
  {"action": "press",       "key": "<key or chord, e.g. Escape, Enter, ControlOrMeta+S>", "reason": "<why>"}
  {"action": "describe_only","reason": "<why re-scan without acting>"}
  {"action": "done",        "result": "<short success summary>"}
  {"action": "fail",        "reason": "<why the goal is unreachable>"}

Guidance:
  - Prefer click_label over click_at when the target has a hint in the \
inventory. It auto-corrects for nested-child click traps.
  - Use click_at only for canvas-rendered targets (chart candles, \
drawings) or when the inventory has no match.
  - `describe_only` re-observes without acting — use after a click \
that likely opened a menu/modal you need to see.
  - Emit `done` once the goal is clearly achieved; `fail` when blocked \
(e.g. missing permissions, goal references non-existent UI). Do NOT \
emit `fail` just because you're stuck — try `describe_only` first.
  - Your reasoning is visible in the audit log; keep `reason` short \
but specific (1 sentence)."""


def _resolve_model(name: str) -> str:
    return _MODEL_ALIASES.get(name, name)


def _compute_cost_anthropic(usage: Any, model: str) -> float:
    """Estimate USD cost from the Anthropic SDK's usage object.
    Cache-read and cache-creation tokens bill at different rates — but
    the MVP loop doesn't use prompt caching, so we treat them all as
    regular input."""
    in_rate, out_rate = _PRICING.get(model, _PRICING["claude-sonnet-4-6"])
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    total_input = input_tokens + cache_read + cache_create
    return (total_input * in_rate + output_tokens * out_rate) / 1_000_000


def _usage_dict_anthropic(usage: Any) -> dict:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return {k: getattr(usage, k, None) for k in (
        "input_tokens", "output_tokens",
        "cache_read_input_tokens", "cache_creation_input_tokens",
    )}


def _usage_dict_openai(usage: Any) -> dict:
    """OpenAI-compat usage shape: prompt_tokens / completion_tokens /
    total_tokens. Some local servers (ollama/mlx) omit usage entirely —
    we tolerate that with None defaults."""
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return {k: getattr(usage, k, None) for k in (
        "prompt_tokens", "completion_tokens", "total_tokens",
    )}


def _prune_inventory(elements: list[dict], goal: str) -> list[dict]:
    """Keep the most likely-relevant inventory entries. Scoring is a
    simple token-overlap heuristic — exact codebase-awareness is
    unnecessary here; the model will fill in the rest from the screenshot.

    Stage 1: always keep items whose label tokens overlap with goal tokens.
    Stage 2: fill remaining slots with the spatially-first items (reading
    order) until we hit the cap."""
    if len(elements) <= _INVENTORY_TOP_K:
        return elements

    goal_tokens = {t.lower() for t in re.findall(r"[a-zA-Z0-9]+", goal) if len(t) > 2}

    def score(e: dict) -> int:
        hay = " ".join(filter(None, [
            e.get("data_name"), e.get("aria_label"),
            e.get("title"), e.get("text"),
        ])).lower()
        hay_tokens = set(re.findall(r"[a-zA-Z0-9]+", hay))
        return len(goal_tokens & hay_tokens)

    scored = sorted(elements, key=lambda e: (-score(e),
                                             e.get("rect", {}).get("y", 0),
                                             e.get("rect", {}).get("x", 0)))
    return scored[:_INVENTORY_TOP_K]


def _compact_inventory(elements: list[dict]) -> list[dict]:
    """Strip inventory entries down to what the model needs. Drops
    classes/raw selectors/etc. — keeps label hints + center + rect."""
    out = []
    for e in elements:
        out.append({
            "data_name": e.get("data_name"),
            "aria_label": e.get("aria_label"),
            "id": e.get("id"),
            "text": e.get("text") or None,
            "center": e.get("center"),
            "rect": e.get("rect"),
        })
    return out


def _image_as_b64(path: str) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


def _anthropic_image_block(path: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": _image_as_b64(path),
        },
    }


def _openai_image_block(path: str) -> dict:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{_image_as_b64(path)}"},
    }


def _build_payload(goal: str, snap: dict, inventory: list[dict],
                   history: list[dict]) -> str:
    """Serialize the text half of the user turn: goal + inventory +
    history. Provider-neutral — provider-specific message assembly
    (whether to attach the screenshot, and in what content-block shape)
    happens in `_call_*` helpers."""
    history_summary = []
    for h in history[-6:]:  # last 6 steps — enough context, bounded tokens
        d = h.get("decision", {})
        r = h.get("action_result", {})
        history_summary.append({
            "step": h.get("step"),
            "decision": d,
            "result_ok": r.get("ok"),
            "result_error": r.get("error") or r.get("reason"),
            "element_after": (r.get("click_result", {}) or {}).get("element_after"),
        })

    payload = {
        "goal": goal,
        "viewport": snap.get("viewport"),
        "inventory_count_total": snap.get("element_count"),
        "inventory_count_sent": len(inventory),
        "inventory": inventory,
        "history": history_summary,
    }
    return json.dumps(payload, indent=2, default=str)


def _parse_decision(raw: str) -> dict:
    """Extract the JSON object from the model's response. Tolerant of a
    leading explanation line the model might add despite the system
    prompt — we find the first `{...}` block and parse it."""
    stripped = raw.strip()
    # Fast path — response is pure JSON.
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    # Fallback — find the first balanced JSON object.
    m = re.search(r"\{[\s\S]*\}", stripped)
    if not m:
        return {"action": "fail", "reason": f"could not parse decision: {stripped[:200]!r}"}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"action": "fail", "reason": f"JSON parse error: {e}: {m.group(0)[:200]!r}"}


def _text_from_anthropic(resp: Any) -> str:
    """Concatenate text blocks from an Anthropic Message."""
    out = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            out.append(block.text)
    return "\n".join(out)


async def _call_anthropic(client: Any, *, model: str, system: str,
                          text: str, image_path: str | None) -> tuple[str, dict, float]:
    """One turn against the Anthropic API. Returns (text, usage_dict, cost_usd)."""
    content: list[dict] = []
    if image_path:
        content.append(_anthropic_image_block(image_path))
    content.append({"type": "text", "text": text})
    resp = await client.messages.create(
        model=model, max_tokens=800, system=system,
        messages=[{"role": "user", "content": content}],
    )
    return (
        _text_from_anthropic(resp),
        _usage_dict_anthropic(resp.usage),
        _compute_cost_anthropic(resp.usage, model),
    )


async def _call_openai_compat(client: Any, *, model: str, system: str,
                              text: str, image_path: str | None
                              ) -> tuple[str, dict, float]:
    """One turn against an OpenAI-compatible endpoint (Ollama, MLX, LM
    Studio, vLLM, etc.). Returns (text, usage_dict, cost_usd=0)."""
    content: list[dict] = [{"type": "text", "text": text}]
    if image_path:
        content.append(_openai_image_block(image_path))
    resp = await client.chat.completions.create(
        model=model, max_tokens=800,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    )
    choice = resp.choices[0].message
    text_out = choice.content or ""
    return (text_out, _usage_dict_openai(getattr(resp, "usage", None)), 0.0)


def _is_mutating(decision: dict) -> bool:
    """Best-effort check for --read-only mode. Conservative: a query
    matching buy/sell/place/submit/etc. is mutating; a click_at is
    opaquely mutating (we can't see its intent), so we flag it too."""
    action = decision.get("action")
    if action == "click_label":
        return bool(_MUTATING_QUERY_RE.search(decision.get("query", "")))
    if action == "click_at":
        return True  # can't introspect intent — be safe
    if action == "type":
        return bool(decision.get("text"))  # typing mutates form state
    if action == "press":
        key = decision.get("key", "")
        # Enter submits forms; ControlOrMeta+S saves.
        return key in ("Enter", "ControlOrMeta+S")
    return False


async def _type_text(text: str) -> dict:
    """Type into the currently-focused element. Uses `page.keyboard.type`
    which dispatches per-character events (what React/Monaco listen for)."""
    from preflight import ensure_automation_chromium
    from session import tv_context

    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await chart._find_or_open_chart(ctx)
        await page.keyboard.type(text)
        await page.wait_for_timeout(100)
        audit.log("act.type", text_length=len(text))
        return {"ok": True, "action": "type", "text_length": len(text)}


async def _press_key(key: str) -> dict:
    """Press a single key or Playwright-style chord (Alt+T, ControlOrMeta+S)."""
    from preflight import ensure_automation_chromium
    from session import tv_context

    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await chart._find_or_open_chart(ctx)
        await page.keyboard.press(key)
        await page.wait_for_timeout(150)
        audit.log("act.press", key=key)
        return {"ok": True, "action": "press", "key": key}


async def _execute(decision: dict) -> dict:
    """Run the action from a parsed decision. Returns a result dict
    with `ok` set; raises only for catastrophic failures (missing
    required field, invalid action)."""
    action = decision.get("action")

    if action == "click_label":
        query = decision.get("query")
        if not query:
            return {"ok": False, "error": "click_label missing 'query'"}
        return await chart.click_label(
            query,
            area=decision.get("area", "full"),
            bypass_overlap=decision.get("bypass_overlap", False),
        )

    if action == "click_at":
        try:
            x = int(decision["x"])
            y = int(decision["y"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "click_at requires int 'x' and 'y'"}
        return await chart.click_at(
            x, y,
            button=decision.get("button", "left"),
            double=decision.get("double", False),
            bypass_overlap=decision.get("bypass_overlap", False),
        )

    if action == "type":
        text = decision.get("text")
        if text is None:
            return {"ok": False, "error": "type missing 'text'"}
        return await _type_text(text)

    if action == "press":
        key = decision.get("key")
        if not key:
            return {"ok": False, "error": "press missing 'key'"}
        return await _press_key(key)

    if action == "describe_only":
        return {"ok": True, "describe_only": True}

    return {"ok": False, "error": f"unknown action: {action!r}"}


def _build_llm_caller(provider: str, model: str, base_url: str | None):
    """Construct the async call function for the selected provider.
    Returns a coroutine: `async call(*, system, text, image_path) -> (text, usage, cost)`."""
    from functools import partial

    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to tradingview/.env "
                "(see .env.example) or export it in your shell."
            )
        client = AsyncAnthropic(api_key=api_key)
        return partial(_call_anthropic, client, model=model)

    # ollama / mlx — OpenAI-compatible path.
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        base_url=base_url or _PROVIDER_DEFAULTS[provider]["base_url"],
        # OpenAI SDK requires SOMETHING for api_key; local endpoints ignore it.
        api_key=os.environ.get("OPENAI_API_KEY", "sk-local"),
    )
    return partial(_call_openai_compat, client, model=model)


async def act(
    goal: str,
    *,
    max_steps: int = _MAX_STEPS_DEFAULT,
    max_cost_usd: float = _MAX_COST_DEFAULT,
    provider: str = _DEFAULT_PROVIDER,
    model: str | None = None,
    base_url: str | None = None,
    text_only: bool = False,
    vision: bool = False,
    read_only: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run the vision-loop driver until `done`, `fail`, or a budget cap.

    `provider` picks the LLM backend: anthropic / ollama / mlx.
    `model` defaults to the provider's default. `base_url` overrides
    the default endpoint for ollama/mlx. `text_only` skips the
    screenshot entirely; `vision` forces it on (wins over provider
    default). Anthropic defaults to vision-on; local providers default
    to text-only."""
    if provider not in _PROVIDER_DEFAULTS:
        raise ValueError(
            f"unknown provider {provider!r}; known: {sorted(_PROVIDER_DEFAULTS)}"
        )
    pdef = _PROVIDER_DEFAULTS[provider]
    model = _resolve_model(model or pdef["default_model"] or "")
    if not model:
        raise ValueError(
            f"provider {provider!r} has no default model — pass --model"
        )
    if provider == "anthropic" and model not in _PRICING:
        # Unknown Anthropic model: cost math falls back to Sonnet rates,
        # which is a safe overestimate. Warn via audit; don't reject.
        audit.log("act.unknown_model_cost_fallback", model=model)

    # Resolve vision setting: explicit flag wins; else provider default.
    # text_only forces off; vision forces on.
    if text_only and vision:
        raise ValueError("--text-only and --vision are mutually exclusive")
    send_image = pdef["vision_default"]
    if text_only:
        send_image = False
    if vision:
        send_image = True

    call = _build_llm_caller(provider, model, base_url)

    req_id = audit.current_request_id.get() or audit.new_request_id()
    transcript_dir = _TRANSCRIPT_DIR / req_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    (transcript_dir / "goal.txt").write_text(goal)

    audit.log("act.start",
              goal=goal, provider=provider, model=model,
              base_url=base_url, send_image=send_image,
              max_steps=max_steps, max_cost_usd=max_cost_usd,
              read_only=read_only, dry_run=dry_run,
              transcript_dir=str(transcript_dir))

    history: list[dict] = []
    total_cost_usd = 0.0
    steps = 0

    while True:
        steps += 1
        if steps > max_steps:
            audit.log("act.budget_exceeded",
                      reason="max_steps", steps=steps - 1,
                      total_cost_usd=total_cost_usd)
            raise LoopBudgetExceededError(
                reason="max_steps", steps=steps - 1,
                cost_usd=total_cost_usd,
                max_steps=max_steps, max_cost_usd=max_cost_usd,
            )

        # 1. Observe.
        snap = await chart.describe_screen(area="full")

        # 2. Decide.
        inventory = _compact_inventory(_prune_inventory(snap["elements"], goal))
        text_payload = _build_payload(goal, snap, inventory, history)
        image_path = snap["screenshot"]["path"] if send_image else None

        # PRE-flight budget — refuse to fire the next call if its
        # worst-case cost would push us past the cap. Zero reserve for
        # local providers (cost always 0); small for Haiku, medium for
        # Sonnet, larger for Opus.
        reserve = _PER_CALL_RESERVE_USD.get(model, 0.0) if provider == "anthropic" else 0.0
        if total_cost_usd + reserve > max_cost_usd:
            audit.log("act.budget_preflight",
                      reason="preflight_reserve_would_exceed",
                      steps=steps, total_cost_usd=total_cost_usd,
                      reserve=reserve, max_cost_usd=max_cost_usd)
            raise LoopBudgetExceededError(
                reason="max_cost_usd_preflight", steps=steps - 1,
                cost_usd=total_cost_usd,
                max_steps=max_steps, max_cost_usd=max_cost_usd,
            )

        with audit.timed("act.llm_call",
                         step=steps, provider=provider, model=model,
                         send_image=send_image) as ctx:
            decision_text, usage, cost = await call(
                system=_SYSTEM_PROMPT,
                text=text_payload,
                image_path=image_path,
            )
            total_cost_usd += cost
            ctx["cost_usd"] = cost
            ctx["total_cost_usd"] = total_cost_usd

        # Post-call guard — catches providers whose call exceeded our
        # reserve (rare; keeps the hard cap honest).
        if total_cost_usd > max_cost_usd:
            audit.log("act.budget_exceeded",
                      reason="max_cost_usd", steps=steps,
                      total_cost_usd=total_cost_usd)
            raise LoopBudgetExceededError(
                reason="max_cost_usd", steps=steps,
                cost_usd=total_cost_usd,
                max_steps=max_steps, max_cost_usd=max_cost_usd,
            )

        decision = _parse_decision(decision_text)
        action = decision.get("action")

        # Persist this step BEFORE acting — even if the action crashes
        # we want the decision on disk for debugging.
        step_record: dict[str, Any] = {
            "step": steps,
            "screenshot": snap["screenshot"]["path"],
            "screenshot_sent_to_model": send_image,
            "inventory_count_sent": len(inventory),
            "inventory_count_total": snap.get("element_count"),
            "decision": decision,
            "decision_text": decision_text,
            "cost_usd": round(cost, 6),
            "total_cost_usd": round(total_cost_usd, 6),
            "usage": usage,
        }
        (transcript_dir / f"step_{steps:02d}_decision.json").write_text(
            json.dumps(step_record, indent=2, default=str)
        )
        audit.log("act.decision",
                  step=steps, action=action,
                  reason=decision.get("reason"),
                  cost_usd=cost, total_cost_usd=total_cost_usd)

        # 3. Terminal actions.
        if action == "done":
            audit.log("act.done", steps=steps, total_cost_usd=total_cost_usd,
                      result=decision.get("result"))
            history.append(step_record)
            return {
                "ok": True,
                "steps": steps,
                "total_cost_usd": round(total_cost_usd, 6),
                "result": decision.get("result"),
                "transcript_dir": str(transcript_dir),
                "history": history,
            }

        if action == "fail":
            audit.log("act.fail", steps=steps,
                      total_cost_usd=total_cost_usd,
                      reason=decision.get("reason"))
            history.append(step_record)
            raise GoalUnachievableError(
                decision.get("reason", "(no reason given)"),
                steps=steps,
            )

        # 4. Safety: read-only refuses mutating actions.
        if read_only and _is_mutating(decision):
            audit.log("act.read_only_refused",
                      step=steps, action=action,
                      query=decision.get("query"))
            raise GoalUnachievableError(
                f"--read-only refused mutating action: {action} "
                f"{decision.get('query') or decision.get('text') or decision.get('key')!r}",
                steps=steps,
            )

        # 5. Act (or skip, if dry-run).
        if dry_run:
            step_record["action_result"] = {"ok": True, "dry_run": True}
        else:
            try:
                result = await _execute(decision)
            except Exception as e:
                result = {
                    "ok": False,
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
            step_record["action_result"] = result

        (transcript_dir / f"step_{steps:02d}_result.json").write_text(
            json.dumps(step_record["action_result"], indent=2, default=str)
        )
        history.append(step_record)
        # Loop — next observe happens at top.


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(
        prog="tv_automation.act",
        description="LLM-in-loop vision driver for TradingView.",
    )
    p.add_argument("goal", help="Natural-language objective (quote the string)")
    p.add_argument("--provider", choices=sorted(_PROVIDER_DEFAULTS),
                   default=_DEFAULT_PROVIDER,
                   help=f"LLM backend (default: {_DEFAULT_PROVIDER}). "
                        f"ollama/mlx use the OpenAI-compat path.")
    p.add_argument("--model", default=None,
                   help="Model name. Default depends on provider: "
                        "anthropic=claude-sonnet-4-6, ollama=qwen3.5:27b, "
                        "mlx=(required). Anthropic aliases: "
                        f"{', '.join(sorted(_MODEL_ALIASES))}")
    p.add_argument("--base-url", default=None,
                   help="Override provider base URL (ollama/mlx). "
                        "Defaults: ollama=http://localhost:11434/v1, "
                        "mlx=http://localhost:8080/v1")
    p.add_argument("--text-only", action="store_true",
                   help="Skip the screenshot entirely — send only the "
                        "inventory + history. Default on for local providers.")
    p.add_argument("--vision", action="store_true",
                   help="Force-include the screenshot (use when a local "
                        "VL model is loaded, e.g. qwen2.5vl:7b). Mutually "
                        "exclusive with --text-only.")
    p.add_argument("--max-steps", type=int, default=_MAX_STEPS_DEFAULT,
                   help=f"Abort after this many steps (default: {_MAX_STEPS_DEFAULT})")
    p.add_argument("--max-cost-usd", type=float, default=_MAX_COST_DEFAULT,
                   help=f"Abort when estimated cost exceeds this "
                        f"(default: ${_MAX_COST_DEFAULT:.2f}; no-op for local providers)")
    p.add_argument("--read-only", action="store_true",
                   help="Refuse mutating actions (buy/sell/place/submit/etc.)")
    p.add_argument("--dry-run", action="store_true",
                   help="Let the model decide but do not execute actions")

    args = p.parse_args()
    run(lambda: act(
        args.goal,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        text_only=args.text_only,
        vision=args.vision,
        max_steps=args.max_steps,
        max_cost_usd=args.max_cost_usd,
        read_only=args.read_only,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    _main()
