"""Pre-Session Forecast — runs before RTH open (~09:00 ET) to predict the
day ahead based on recent completed-day profiles and accumulated lessons.

Output shape matches the manually-produced `_pre_session.json` files
already in `forecasts/` — same fields (regime_read, predictions,
time_window_expectations, probable_goat, tactical_bias, prediction_tags).
Consumed by the Forecasts UI tab and, eventually, the reconcile step.

Captures a screenshot of the pre-market chart (globex/overnight) for
context — overnight range and where we're opening relative to prior
day matters for the morning call.

CLI:
    python -m tv_automation.pre_session_forecast
    python -m tv_automation.pre_session_forecast --date 2026-04-22
    python -m tv_automation.pre_session_forecast --symbol MNQ1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import Page

from . import lessons as lessons_mod
from .chatgpt_web import analyze_via_chatgpt_web
from .lib import audit
from .lib.context import chart_session


_FORECASTS_ROOT = (Path(__file__).parent.parent / "forecasts").resolve()
_PROFILES_ROOT = (Path(__file__).parent.parent / "profiles").resolve()
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView").resolve()
_PARSE_FAIL_ROOT = (Path(__file__).parent.parent / "pine" / "parse_failures").resolve()

# How many recent completed days to include as priors, plus same-DOW lookback.
RECENT_PRIORS_N = 5
SAME_DOW_LOOKBACK_DAYS = 30
SAME_DOW_N = 3


_PRE_SESSION_SYSTEM = """You are a day-trading pre-session forecaster for MNQ1! (Micro E-mini Nasdaq-100 futures, CME). Given (a) a pre-market chart screenshot showing overnight/globex action, (b) the last few completed-day profiles as priors, and (c) same-day-of-week reference days, forecast how TODAY's RTH session (09:30–16:00 ET) will unfold BEFORE it opens.

You are making the FIRST forecast of the day — the one the subsequent 10:00/12:00/14:00 forecasts will refine or contradict. Set the initial bias and name concrete invalidation conditions for later stages to check.

Key inputs you should weigh:
- Overnight range (from the screenshot) — where are futures trading relative to prior-day value?
- Recent regime (from the last-N priors) — trending up/down, or chopping?
- Same-day-of-week priors — Tuesdays often behave similarly; use sparingly but note divergences.
- ACCUMULATED LESSONS (below) — apply these before defaulting to naive continuation.

REQUIRED OUTPUT — narrative sections first, then a fenced JSON block.

## REGIME READ
One paragraph naming the current regime (trending up/down, balancing, rotational) and whether today's forecast should lean with or against the recent pattern. Cite the priors you're leaning on.

## SAME-DOW REFERENCES
List the 2–3 same-DOW comparables you're using, 1 sentence each on what they suggest for today.

## PREDICTIONS
- Direction (up/down/flat) with confidence (low/med/high)
- Open type (gap_up_drive/gap_down_drive/flat_open/rotational_open/open_dip_then_reclaim/...)
- Structure (snake_case phrase — e.g., trend_up_with_midday_pause)
- Expected move size (small/med/large)
- Net pct range (low–high) — e.g. +0.25% to +0.85%
- Intraday span range (pts) — low–high

## TIME WINDOW EXPECTATIONS
- 10:00: one-line expectation
- 12:00: one-line expectation
- 14:00: one-line expectation
- 16:00 (close): one-line expectation

## PROBABLE GOAT
- Direction (long/short)
- Time window (opening/morning/midday/afternoon/late)
- Rationale (one sentence)

## TACTICAL BIAS
- Primary bias (short phrase): e.g. buy_dips_on_reclaim
- Invalidation conditions — name 2–3 specific things that would invalidate the direction, phrased so the 10:00 live forecaster can check them

## PREDICTION TAGS
- `direction: up|down|flat`
- `structure: <snake_case>`
- `open_type: <snake_case>`
- `lunch_behavior: <snake_case>`
- `afternoon_drive: <snake_case>`
- `goat_direction: up|down`
- `close_near_extreme: yes_closer_to_HOD|yes_closer_to_LOD|no_mid_upper_range|no_mid_lower_range`

## CONFIDENCE NOTES
Two or three sentences stating what could go wrong, what you're least sure about, and which of the invalidation triggers is most likely to fire.

## STRUCTURED JSON
```json
{
  "regime_read": "...",
  "same_dow_references": ["YYYY-MM-DD: ...", "YYYY-MM-DD: ..."],
  "predictions": {
    "direction": "up|down|flat",
    "direction_confidence": "low|med|high",
    "open_type": "...",
    "structure": "...",
    "expected_move_size": "small|med|large",
    "predicted_net_pct_lo": 0.0,
    "predicted_net_pct_hi": 0.0,
    "predicted_intraday_span_lo_pts": 0,
    "predicted_intraday_span_hi_pts": 0
  },
  "time_window_expectations": {
    "10am": "...",
    "12pm": "...",
    "2pm": "...",
    "4pm": "..."
  },
  "probable_goat": {
    "direction": "long|short",
    "time_window": "...",
    "rationale": "..."
  },
  "tactical_bias": {
    "bias": "...",
    "invalidation": "..."
  },
  "prediction_tags": {
    "direction": "up|down|flat",
    "structure": "...",
    "open_type": "...",
    "lunch_behavior": "...",
    "afternoon_drive": "...",
    "goat_direction": "up|down",
    "close_near_extreme": "..."
  },
  "confidence_notes": "..."
}
```

{ACCUMULATED_LESSONS}

Return ONLY the narrative sections followed by the fenced JSON block. No preamble."""


def _render_lessons_block() -> str:
    body = lessons_mod.format_for_prompt(n=10)
    if not body:
        return ""
    return "## ACCUMULATED LESSONS (from prior reconciliations — apply these)\n" + body


def _select_priors(symbol: str, target_date: date) -> tuple[list[dict], list[dict]]:
    """Return (recent_priors, same_dow_refs).

    Recent: up to `RECENT_PRIORS_N` most-recent completed-day profiles before target.
    Same-DOW: up to `SAME_DOW_N` profiles within SAME_DOW_LOOKBACK_DAYS whose DOW matches.
    """
    prefix = f"{symbol}_"
    suffix = ".json"
    all_jsons: list[tuple[date, dict]] = []
    for p in _PROFILES_ROOT.glob(f"{prefix}*{suffix}"):
        stem = p.stem  # MNQ1_2026-04-20
        m = re.match(rf"^{re.escape(symbol)}_(\d{{4}}-\d{{2}}-\d{{2}})$", stem)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d >= target_date:
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        all_jsons.append((d, data))
    all_jsons.sort(key=lambda t: t[0], reverse=True)

    recent = [d for _, d in all_jsons[:RECENT_PRIORS_N]]
    target_dow = target_date.weekday()
    cutoff = target_date - timedelta(days=SAME_DOW_LOOKBACK_DAYS)
    same_dow: list[dict] = []
    for d, data in all_jsons:
        if d < cutoff:
            break
        if d.weekday() == target_dow:
            same_dow.append(data)
            if len(same_dow) >= SAME_DOW_N:
                break
    return recent, same_dow


def _compact_profile(p: dict) -> dict:
    """Trim a profile dict to the bits most useful as prior context."""
    return {
        "date": p.get("date"),
        "dow": p.get("dow"),
        "summary": p.get("summary"),
        "tags": p.get("tags"),
        "takeaway": p.get("takeaway"),
    }


async def _capture_premarket(page: Page, symbol: str) -> Path:
    """Screenshot the current live chart for overnight context."""
    _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    await page.bring_to_front()
    await page.keyboard.press("End")
    await page.wait_for_timeout(400)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _SCREENSHOT_ROOT / f"{symbol}_presession_{ts}.png"
    await page.screenshot(path=str(path))
    return path


_STRUCTURED_HEADER_RX = re.compile(r"^#{1,3}\s*STRUCTURED\s+JSON\s*$", re.MULTILINE)


def _extract_balanced_json(text: str, start: int) -> dict | None:
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    in_str = False
    escape = False
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
    narrative = text[:narrative_end].strip()
    return narrative, structured


async def run_pre_session(
    *, symbol: str = "MNQ1", date_str: str | None = None,
) -> dict:
    target_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    )
    date_str = target_date.strftime("%Y-%m-%d")
    dow = target_date.strftime("%a")

    _FORECASTS_ROOT.mkdir(parents=True, exist_ok=True)
    base = _FORECASTS_ROOT / f"{symbol}_{date_str}_pre_session"
    md_path, json_path = base.with_suffix(".md"), base.with_suffix(".json")
    if json_path.exists():
        audit.log("pre_session.skip_existing", path=str(json_path))
        return {"skipped": True, "path": str(json_path)}

    recent, same_dow = _select_priors(symbol, target_date)
    audit.log("pre_session.priors",
              recent=[p.get("date") for p in recent],
              same_dow=[p.get("date") for p in same_dow])

    async with chart_session() as (_ctx, page):
        with audit.timed("pre_session.run", date=date_str) as ac:
            screenshot = await _capture_premarket(page, symbol)
            ac["screenshot"] = str(screenshot)

            parts = [f"# FORECAST TARGET: {symbol}! {date_str} ({dow})", ""]
            parts.append("## RECENT PRIORS (most recent last-N completed days)")
            parts.append(json.dumps([_compact_profile(p) for p in recent], indent=2))
            parts.append("")
            parts.append(f"## SAME-DOW REFERENCES (last {SAME_DOW_LOOKBACK_DAYS} days, matching {dow})")
            if same_dow:
                parts.append(json.dumps([_compact_profile(p) for p in same_dow], indent=2))
            else:
                parts.append("(none in lookback window)")
            parts.append("")
            parts.append(
                f"Forecast today's RTH session. The attached screenshot shows the live chart "
                f"right now (pre-open or early-session globex). Follow the output format in the "
                f"system prompt exactly, ending with the fenced JSON block."
            )
            user_prompt = "\n".join(parts)

            system_prompt = _PRE_SESSION_SYSTEM.replace(
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
                dump = _PARSE_FAIL_ROOT / f"pre_session_{symbol}_{date_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                dump.write_text(text)
                audit.log("pre_session.parse_fail", dump_path=str(dump))

            fm = "\n".join([
                "---",
                f"symbol: {symbol}",
                f"date: {date_str}",
                f"dow: {dow}",
                "stage: pre_session_forecast",
                "mode: live_prerth",
                f"screenshot: {screenshot}",
                f"based_on_priors: {[p.get('date') for p in recent]}",
                f"same_dow_refs: {[p.get('date') for p in same_dow]}",
                "model: chatgpt_thinking",
                f"made_at: {datetime.now().isoformat(timespec='seconds')}",
                "---",
                "",
            ])
            md_path.write_text(fm + text.strip() + "\n")

            saved = {
                "symbol": f"{symbol}!",
                "date": date_str,
                "dow": dow,
                "stage": "pre_session_forecast",
                "mode": "live_prerth",
                "screenshot_path": str(screenshot),
                "based_on_priors": [p.get("date") for p in recent],
                "same_dow_refs": [p.get("date") for p in same_dow],
                "lessons_injected": bool(_render_lessons_block()),
                "model": "chatgpt_thinking",
                "made_at": datetime.now().isoformat(timespec="seconds"),
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
    p = argparse.ArgumentParser(prog="tv_automation.pre_session_forecast")
    p.add_argument("--symbol", default="MNQ1")
    p.add_argument("--date", dest="date_str", default=None,
                   help="Override trading date (default: today)")
    args = p.parse_args()
    result = asyncio.run(run_pre_session(symbol=args.symbol, date_str=args.date_str))
    print(json.dumps(result, indent=2)[:2000])


if __name__ == "__main__":
    _main()
