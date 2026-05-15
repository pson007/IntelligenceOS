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

from . import lessons as lessons_mod, replay, replay_api
from .chart import ensure_auto_scale
from .chatgpt_web import analyze_via_chatgpt_web
from .forecast_capture import hide_widget_panel
from .lib import audit
from .lib.capture_invariants import CaptureExpect, assert_capture_ready
from .lib.context import chart_session


_FORECASTS_ROOT = (Path(__file__).parent.parent / "forecasts").resolve()
_PROFILES_ROOT = (Path(__file__).parent.parent / "profiles").resolve()
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView").resolve()
_PARSE_FAIL_ROOT = (Path(__file__).parent.parent / "pine" / "parse_failures").resolve()

# How many recent completed days to include as priors, plus same-DOW lookback.
RECENT_PRIORS_N = 5
SAME_DOW_LOOKBACK_DAYS = 30
SAME_DOW_N = 3


def _symbol_for_api(symbol: str) -> str:
    return symbol if "!" in symbol or ":" in symbol else f"{symbol}!"


_CANARY_TIME_RX = re.compile(r"^(\d{1,2}):(\d{2})$")


def _resolve_canary_evaluate_at(hhmm: str | None, date_str: str) -> str | None:
    """LLM emits `evaluate_at: "HH:MM"` (ET). Resolve to absolute ISO
    with TODAY's date and ET offset so canary.py's `datetime.fromisoformat`
    parses without ambiguity. Returns None if the input doesn't match
    HH:MM — caller writes the original through anyway so a malformed
    timestamp is visible in the artifact rather than silently dropped."""
    if not hhmm or not isinstance(hhmm, str):
        return None
    m = _CANARY_TIME_RX.match(hhmm.strip())
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    dt = datetime(d.year, d.month, d.day, hh, mm, 0, tzinfo=et)
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _write_canary_artifact(
    canary_block: dict, symbol: str, date_str: str, dow: str,
) -> Path:
    """Persist the canary thesis as its own JSON file. Resolves each
    check's `evaluate_at: HH:MM` to an absolute ISO `evaluate_after`
    (and a 1-minute window via `evaluate_before` to keep the eval
    window tight). Idempotent — overwrites if re-run."""
    checks_in = canary_block.get("checks") or []
    checks_out = []
    for c in checks_in:
        if not isinstance(c, dict):
            continue
        hhmm = c.get("evaluate_at")
        eval_after = _resolve_canary_evaluate_at(hhmm, date_str)
        # `evaluate_before` is `evaluate_after + 5 min`. Keeps a finite
        # window so a long-deferred eval doesn't act on stale data.
        eval_before = None
        if eval_after:
            try:
                d = datetime.fromisoformat(eval_after)
                eval_before = (d + timedelta(minutes=5)).strftime(
                    "%Y-%m-%dT%H:%M:%S%z",
                )
            except ValueError:
                pass
        checks_out.append({
            "id": c.get("id"),
            "label": c.get("label"),
            "rationale": c.get("rationale"),
            "check_type": c.get("check_type"),
            "evaluate_at": hhmm,
            "evaluate_after": eval_after,
            "evaluate_before": eval_before,
            "params": c.get("params") or {},
            "weight": int(c.get("weight") or 1),
        })

    artifact = {
        "symbol": f"{symbol}!",
        "date": date_str,
        "dow": dow,
        "made_at": datetime.now().isoformat(timespec="seconds"),
        "thesis_summary": canary_block.get("thesis_summary"),
        "default_action_if_passing":
            canary_block.get("default_action_if_passing"),
        "default_action_if_partial":
            canary_block.get("default_action_if_partial"),
        "default_action_if_failing":
            canary_block.get("default_action_if_failing"),
        "auto_pause_if_failing":
            bool(canary_block.get("auto_pause_if_failing", True)),
        "checks": checks_out,
    }
    path = _FORECASTS_ROOT / f"{symbol}_{date_str}_canary.json"
    path.write_text(json.dumps(artifact, indent=2))
    audit.log("canary.written",
              symbol=symbol, date=date_str,
              n_checks=len(checks_out), path=str(path))
    return path


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

## CANARY THESIS
Pick 3–5 falsifiable trip-wires that must be true by mid-morning for your bias to remain actionable. Each is a binary (pass/fail) observation the chart will prove or disprove between 09:00 and 12:00 ET. Less is more — pick the highest-leverage observations, not many weak ones.

For each canary check, return:
- `id` — snake_case identifier (e.g. `overnight_posture`, `open_structure`, `first_30_low`)
- `label` — short human description
- `rationale` — why this check is load-bearing for the bias
- `check_type` — one of `price_level`, `price_level_window`, `open_pattern`, `vwap_relationship`
- `evaluate_at` — HH:MM ET deadline (the system converts to absolute ISO using TODAY'S date)
- `params` — type-specific (see below)
- `weight` — 1 (confirmation) or 2 (thesis-killer)

### Check type: `price_level`
Pass when the latest 1-min bar's close satisfies the inequality at evaluate_at.
- `params: { "price_above": NUMBER }` — pass when close > number
- `params: { "price_below": NUMBER }` — pass when close < number

### Check type: `price_level_window`
Pass when the extreme of a time window respects a threshold.
- `params: { "window": "HH:MM-HH:MM", "low_of_window_above": NUMBER }` — pass when no bar's low in the window dipped below the number
- `params: { "window": "HH:MM-HH:MM", "high_of_window_below": NUMBER }` — pass when no bar's high in the window broke above

### Check type: `open_pattern`
Pass when the 09:30–09:35 5-bar print classifies into a tolerated label.
- `params: { "expected": "dip_then_reclaim|rotational_open|trend_break_up|trend_break_down|gap_and_go|inside_bar_open", "tolerated": [...] }`
- `tolerated` is a superset of `expected` containing classifications you'd accept.

### Check type: `vwap_relationship`
Pass when the latest 1-min close is on the named side of session VWAP. Requires VWAP to be on the active layout.
- `params: { "side": "above" }` | `{ "side": "below" }` | `{ "side": "at" }` (within 2 ticks)

### Pre-committed actions
- `default_action_if_passing` — when 100% of weighted checks pass
- `default_action_if_partial` — when 50–99% pass (or some still pending)
- `default_action_if_failing` — when <50% pass

Allowed action values: `trade_full_size`, `trade_half_size`, `trade_smallest`, `paper_only`, `stand_down`.

- `auto_pause_if_failing` — true engages the workspace kill-switch when failing-state is reached AND there's open exposure. Default: true.

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
  "confidence_notes": "...",
  "canary": {
    "thesis_summary": "one sentence stating the bias and its load-bearing assumption",
    "default_action_if_passing": "trade_full_size|trade_half_size|trade_smallest|paper_only|stand_down",
    "default_action_if_partial":  "trade_full_size|trade_half_size|trade_smallest|paper_only|stand_down",
    "default_action_if_failing":  "trade_full_size|trade_half_size|trade_smallest|paper_only|stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "overnight_posture",
        "label": "Overnight holds above pre-session demand",
        "rationale": "...",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": { "price_above": 26950 },
        "weight": 2
      }
    ]
  }
}
```

{ACCUMULATED_LESSONS}

Return ONLY the narrative sections followed by the fenced JSON block. No preamble."""


def _render_lessons_block() -> str:
    return lessons_mod.format_historical_feedback(n=10, min_occurrences=2)


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


async def _capture_premarket(
    page: Page, symbol: str, *, expect: CaptureExpect | None = None,
) -> Path:
    """Screenshot the current live chart for overnight context.

    Heavy TV chart tabs (Pine strategies + multiple indicators) can OOM
    the renderer mid-flow — Playwright surfaces this as
    `Keyboard.press: Target crashed`. The CDP page object is still
    valid but input goes nowhere. Detect the dead renderer on the
    first input call, reload the page, re-apply symbol/interval from
    `expect`, and retry once.
    """
    _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    await page.bring_to_front()
    try:
        await page.keyboard.press("End")
    except Exception as e:
        if "target crashed" not in str(e).lower():
            raise
        audit.log("pre_session.renderer_crashed", err=str(e))
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(1500)
        if expect is not None:
            relanded = await replay_api.set_symbol_in_place(
                page, symbol=expect.symbol, interval="1",
            )
            if relanded is None:
                raise RuntimeError(
                    "set_symbol_in_place failed after renderer-crash reload"
                )
            audit.log("pre_session.recovered_after_crash", landed=relanded)
        await page.bring_to_front()
        await page.keyboard.press("End")
    await page.wait_for_timeout(400)
    await hide_widget_panel(page)
    if expect is not None:
        await assert_capture_ready(page, expect)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _SCREENSHOT_ROOT / f"{symbol}_presession_{ts}.png"
    await ensure_auto_scale(page)
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
    image_path: str | None = None, force: bool = False,
) -> dict:
    """Run a pre-session forecast for `date_str` (defaults to today).

    `image_path` (optional): bypass automated chart capture and run the
    forecast against a pre-existing PNG. Skips the chart_session/Replay
    setup entirely — useful for backfilling missed mornings or running
    against a screenshot taken on a different layout (e.g. mobile).
    """
    target_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    )
    date_str = target_date.strftime("%Y-%m-%d")
    dow = target_date.strftime("%a")

    _FORECASTS_ROOT.mkdir(parents=True, exist_ok=True)
    base = _FORECASTS_ROOT / f"{symbol}_{date_str}_pre_session"
    md_path, json_path = base.with_suffix(".md"), base.with_suffix(".json")
    if json_path.exists() and not force:
        audit.log("pre_session.skip_existing", path=str(json_path))
        return {"skipped": True, "path": str(json_path)}

    recent, same_dow = _select_priors(symbol, target_date)
    audit.log("pre_session.priors",
              recent=[p.get("date") for p in recent],
              same_dow=[p.get("date") for p in same_dow])

    if image_path:
        # Upload path — skip chart_session entirely. The screenshot is
        # already on disk (FastAPI saved the upload there); we only need
        # to run the LLM call and persist the artifacts.
        audit.log("pre_session.chart_skipped_uploaded", image_path=image_path)
        with audit.timed("pre_session.run", date=date_str, source="upload") as ac:
            screenshot = Path(image_path)
            ac["screenshot"] = str(screenshot)
            return await _pre_session_llm_and_save(
                ac=ac, screenshot=screenshot, symbol=symbol, date_str=date_str,
                dow=dow, recent=recent, same_dow=same_dow,
                md_path=md_path, json_path=json_path,
            )

    async with chart_session() as (_ctx, page):
        await replay.exit_replay(page)
        landed = await replay_api.set_symbol_in_place(
            page, symbol=_symbol_for_api(symbol), interval="1",
        )
        if landed is None:
            raise RuntimeError("set_symbol_in_place failed before pre-session forecast")
        audit.log("pre_session.chart_pinned", landed=landed)
        with audit.timed("pre_session.run", date=date_str) as ac:
            screenshot = await _capture_premarket(
                page, symbol,
                expect=CaptureExpect(
                    symbol=_symbol_for_api(symbol),
                    interval="1m",
                    replay_mode=False,
                ),
            )
            ac["screenshot"] = str(screenshot)
            return await _pre_session_llm_and_save(
                ac=ac, screenshot=screenshot, symbol=symbol, date_str=date_str,
                dow=dow, recent=recent, same_dow=same_dow,
                md_path=md_path, json_path=json_path,
            )


async def _pre_session_llm_and_save(
    *, ac: dict, screenshot: Path, symbol: str, date_str: str, dow: str,
    recent: list[dict], same_dow: list[dict],
    md_path: Path, json_path: Path,
) -> dict:
    """Shared LLM-call + parse + save core, used by both the live-chart
    and uploaded-screenshot paths. `ac` is the audit timed-context dict
    so per-run latency/response-chars/parse-success metrics roll up to
    the same `pre_session.run` event regardless of source."""
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

    # Split the canary block into its own artifact. Lifecycle
    # is different from pre_session — the canary's *status*
    # mutates throughout the morning (status.json updates as
    # checks evaluate), but the canary itself is immutable
    # once written. Resolve `evaluate_at: "HH:MM"` → absolute
    # ISO with today's date in ET so canary.py can compare
    # against datetime.now() without re-doing the date math.
    canary_block = (structured or {}).get("canary") if structured else None
    if canary_block:
        _write_canary_artifact(canary_block, symbol, date_str, dow)
        saved["canary_emitted"] = True
    else:
        saved["canary_emitted"] = False

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
