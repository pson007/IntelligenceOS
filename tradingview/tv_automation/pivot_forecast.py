"""Pivot Forecast — intraday re-forecast fired when the pre-session's
invalidation condition breaks.

Called the moment the original thesis is dead. Takes the original
pre-session forecast + current chart + break context as input, asks
for a revised read: is the regime REVERSED, FLAT, or is this a
SHAKEOUT that will reclaim?

Output shape matches other forecast JSONs so the lessons + calibration
feedback loops pick it up automatically. Stage is `invalidation_HHMM`
where HHMM is the wall-clock time of the pivot call in ET.

CLI:
    python -m tv_automation.pivot_forecast
    python -m tv_automation.pivot_forecast --reason "broke 26964 on 8.3x volume"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import Page

from . import lessons as lessons_mod, replay, replay_api
from .chatgpt_web import analyze_via_chatgpt_web
from .lib import audit
from .lib.capture_invariants import CaptureExpect, assert_capture_ready
from .lib.context import chart_session


_ET = ZoneInfo("America/New_York")
_FORECASTS_ROOT = (Path(__file__).parent.parent / "forecasts").resolve()
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView").resolve()
_PARSE_FAIL_ROOT = (Path(__file__).parent.parent / "pine" / "parse_failures").resolve()


def _symbol_for_api(symbol: str) -> str:
    return symbol if "!" in symbol or ":" in symbol else f"{symbol}!"


_PIVOT_SYSTEM = """You are a day-trading pivot analyst for MNQ1! (Micro E-mini Nasdaq-100 futures, CME). The pre-session forecast set a directional bias today, and that bias has now been INVALIDATED by price action. You are being called AT THE MOMENT OF INVALIDATION to reassess whether this is (A) a real regime flip, (B) an unclear spot to stand aside, or (C) a stop-hunt that will be reclaimed.

Your role is narrow: name what JUST happened, decide which of the three cases this is, and give concrete action criteria. Do NOT re-state the entire pre-session thesis — it failed, your job is what's next.

You are given:
- The original pre-session forecast (bias + invalidation triggers + predictions)
- A current chart screenshot showing the invalidation event
- Optional operator note on what tripped the invalidation (e.g. "broke 26964 on 8.3x volume at 13:02")
- ACCUMULATED LESSONS from prior pivot reconciliations — apply them before defaulting to naive continuation

REQUIRED OUTPUT — narrative sections first, then a fenced JSON block.

## BREAK CONTEXT
One paragraph: what level broke, what was the volume/acceptance signature, how does price look NOW relative to VWAP and prior-day value? Use evidence from the screenshot — don't repeat the operator note verbatim.

## PIVOT CLASSIFICATION
Pick exactly ONE of:
- REVERSAL — the regime has flipped. Original long bias becomes short thesis (or vice versa). State the new entry trigger, stop, and first target.
- FLAT — the regime is unclear. No trade until a new structure forms. Name 2 specific conditions you'd want to see before re-engaging (e.g. "VWAP reclaim + higher-low above 26970" or "20m acceptance below prior-day low").
- SHAKEOUT — this is a stop-hunt; price will reclaim. Name the specific reclaim threshold and the time window to see it by (e.g. "back above 26985 by 13:20 ET").

## REVISED TACTICAL BIAS
- new_bias (snake_case): fade_reversal | stand_aside | buy_reclaim | sell_failure | ...
- new_invalidation: 1–2 sentences naming what would invalidate THIS pivot read (the meta-invalidation)

## CONFIDENCE
- pivot_confidence: low | med | high
- What's the main risk that this pivot call is wrong?

## STRUCTURED JSON
```json
{
  "break_context": "...",
  "pivot_classification": "REVERSAL|FLAT|SHAKEOUT",
  "reversal": {
    "direction": "long|short|null",
    "entry_trigger": "...",
    "stop": 0,
    "first_target": 0
  },
  "flat_conditions": ["...", "..."],
  "shakeout_reclaim": {
    "threshold": 0,
    "deadline_et": "HH:MM"
  },
  "revised_tactical_bias": {
    "bias": "...",
    "invalidation": "..."
  },
  "pivot_confidence": "low|med|high",
  "confidence_notes": "..."
}
```

Populate ONLY the subfield matching the pivot_classification you picked. The other two subfield objects should be null.

{ACCUMULATED_LESSONS}

Return ONLY the narrative sections followed by the fenced JSON block. No preamble."""


_STRUCTURED_HEADER_RX = re.compile(r"^#{1,3}\s*STRUCTURED\s+JSON\s*$", re.MULTILINE)


def _extract_balanced_json(text: str, start: int) -> dict | None:
    i = text.find("{", start)
    if i < 0:
        return None
    depth, in_str, escape = 0, False, False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i : j + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _split_response(text: str) -> tuple[str, dict | None]:
    header = _STRUCTURED_HEADER_RX.search(text)
    narrative_end = header.start() if header else len(text)
    search_start = header.end() if header else 0
    structured = _extract_balanced_json(text, search_start)
    return text[:narrative_end].strip(), structured


def _render_lessons_block() -> str:
    body = lessons_mod.format_for_prompt(n=10)
    if not body:
        return ""
    return "## ACCUMULATED LESSONS (from prior reconciliations — apply these)\n" + body


def _compact_pre_session(p: dict) -> dict:
    """Trim a pre-session forecast down to the context the pivot needs:
    original bias, invalidation triggers, predictions. Don't re-send the
    regime paragraph — the LLM doesn't need to re-read what JUST failed."""
    return {
        "date": p.get("date"),
        "dow": p.get("dow"),
        "predictions": p.get("predictions"),
        "tactical_bias": p.get("tactical_bias"),
        "probable_goat": p.get("probable_goat"),
        "prediction_tags": p.get("prediction_tags"),
    }


async def _capture_current(
    page: Page, symbol: str, *, expect: CaptureExpect | None = None,
) -> Path:
    """Screenshot the live chart at the moment the pivot is called."""
    _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    await page.bring_to_front()
    await page.keyboard.press("End")
    await page.wait_for_timeout(400)
    if expect is not None:
        await assert_capture_ready(page, expect)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _SCREENSHOT_ROOT / f"{symbol}_pivot_{ts}.png"
    await page.screenshot(path=str(path))
    return path


async def run_pivot(
    *, symbol: str = "MNQ1", reason: str | None = None,
    date_str: str | None = None,
) -> dict:
    """Run a pivot re-forecast for the current trading day.

    `reason` is an optional free-text note the operator provides when
    invoking — e.g. "broke 26964 on 8.3x volume at 13:02". Gets woven
    into the user prompt so the LLM grounds its break-context narrative.

    Saves `forecasts/{SYMBOL}_{YYYY-MM-DD}_invalidation_HHMM.{md,json}`
    where HHMM is the wall-clock time in ET at the moment of the call.
    """
    now_et = datetime.now(_ET)
    target = (
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else now_et.date()
    )
    date_s = target.strftime("%Y-%m-%d")
    dow = target.strftime("%a")
    hhmm = now_et.strftime("%H%M")
    stage = f"invalidation_{hhmm}"

    pre_path = _FORECASTS_ROOT / f"{symbol}_{date_s}_pre_session.json"
    if not pre_path.exists():
        raise FileNotFoundError(
            f"No pre-session forecast for {date_s} — pivot needs the original "
            f"thesis as context. Expected: {pre_path.name}"
        )
    try:
        pre = json.loads(pre_path.read_text())
    except Exception as e:
        raise RuntimeError(f"pre-session JSON malformed: {e}") from e

    _FORECASTS_ROOT.mkdir(parents=True, exist_ok=True)
    base = _FORECASTS_ROOT / f"{symbol}_{date_s}_{stage}"
    md_path, json_path = base.with_suffix(".md"), base.with_suffix(".json")

    async with chart_session() as (_ctx, page):
        await replay.exit_replay(page)
        landed = await replay_api.set_symbol_in_place(
            page, symbol=_symbol_for_api(symbol), interval="1",
        )
        if landed is None:
            raise RuntimeError("set_symbol_in_place failed before pivot forecast")
        audit.log("pivot.chart_pinned", landed=landed)
        with audit.timed("pivot.run", date=date_s, stage=stage) as ac:
            screenshot = await _capture_current(
                page, symbol,
                expect=CaptureExpect(
                    symbol=_symbol_for_api(symbol),
                    interval="1m",
                    replay_mode=False,
                ),
            )
            ac["screenshot"] = str(screenshot)

            parts = [
                f"# PIVOT TARGET: {symbol}! {date_s} ({dow}), wall-clock {hhmm} ET", "",
                "## ORIGINAL PRE-SESSION (the thesis that just failed)",
                json.dumps(_compact_pre_session(pre), indent=2),
                "",
            ]
            if reason:
                parts.append("## OPERATOR NOTE ON THE BREAK")
                parts.append(reason.strip())
                parts.append("")
            parts.append(
                "Classify this pivot as REVERSAL, FLAT, or SHAKEOUT per the "
                "system prompt format. The attached screenshot shows the live "
                "chart right now. End with the fenced JSON block exactly."
            )
            user_prompt = "\n".join(parts)

            system_prompt = _PIVOT_SYSTEM.replace(
                "{ACCUMULATED_LESSONS}", _render_lessons_block()
            )
            text, _, _ = await analyze_via_chatgpt_web(
                image_path=str(screenshot),
                system_prompt=system_prompt,
                user_text=user_prompt,
                model="Thinking",
                timeout_s=300,
            )
            ac["response_chars"] = len(text)

            narrative, structured = _split_response(text)
            if structured is None:
                _PARSE_FAIL_ROOT.mkdir(parents=True, exist_ok=True)
                dump = _PARSE_FAIL_ROOT / f"pivot_{symbol}_{date_s}_{hhmm}_{now_et.strftime('%Y%m%d_%H%M%S')}.txt"
                dump.write_text(text)
                audit.log("pivot.parse_fail", dump_path=str(dump))

            fm = "\n".join([
                "---",
                f"symbol: {symbol}",
                f"date: {date_s}",
                f"dow: {dow}",
                f"stage: {stage}",
                f"screenshot: {screenshot}",
                f"operator_reason: {reason or '(none)'}",
                "model: chatgpt_thinking",
                f"made_at: {now_et.isoformat(timespec='seconds')}",
                "---",
                "",
            ])
            md_path.write_text(fm + text.strip() + "\n")

            saved = {
                "symbol": symbol,
                "date": date_s,
                "dow": dow,
                "stage": stage,
                "pivot_called_at_et": now_et.strftime("%H:%M ET"),
                "operator_reason": reason,
                "screenshot_path": str(screenshot),
                "lessons_injected": bool(_render_lessons_block()),
                "model": "chatgpt_thinking",
                "made_at": now_et.isoformat(timespec="seconds"),
                "raw_response": text,
            }
            if structured:
                saved.update(structured)
                saved["parsed_structured"] = True
            else:
                saved["parsed_structured"] = False
            json_path.write_text(json.dumps(saved, indent=2))
            ac["saved_to"] = str(json_path)
            return saved


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.pivot_forecast")
    p.add_argument("--symbol", default="MNQ1")
    p.add_argument("--date", dest="date_str", default=None,
                   help="Trading date (default: today)")
    p.add_argument("--reason", default=None,
                   help="Free-text note on what tripped the invalidation "
                        "(e.g. 'broke 26964 on 8.3x vol at 13:02')")
    args = p.parse_args()
    result = asyncio.run(run_pivot(
        symbol=args.symbol, date_str=args.date_str, reason=args.reason,
    ))
    out = {k: v for k, v in result.items() if k != "raw_response"}
    print(json.dumps(out, indent=2)[:3000])


if __name__ == "__main__":
    _main()
