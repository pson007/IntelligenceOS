"""Replay Forecast Workflow — predict the rest of an RTH session from a
partial-day cursor, then grade the prediction against the completed day.

Pipeline (per day):
    1. Navigate replay to 10:00 AM ET (compensated pick + step adjust)
    2. F1 @ 10:00 — frame → screenshot → ChatGPT → save .md+.json
    3. Step forward 120 bars → 12:00
    4. F2 @ 12:00 — same
    5. Step forward 120 bars → 14:00
    6. F3 @ 14:00 — same
    7. Step forward 120 bars → 16:00
    8. Reconciliation — screenshot the completed day, load F1/F2/F3 + the
       matching completed-day profile if available, grade each forecast,
       save reconciliation.md+.json

Output (in `tradingview/forecasts/`):
    {SYMBOL}_{YYYY-MM-DD}_{HHMM}.{md,json}         — for F1/F2/F3
    {SYMBOL}_{YYYY-MM-DD}_reconciliation.{md,json} — grading summary

CLI:
    python -m tv_automation.daily_forecast 2026-03-18
    python -m tv_automation.daily_forecast 2026-03-18 --resume  # skip existing
    python -m tv_automation.daily_forecast 2026-03-18 --symbol MNQ1

Requires a TV tab at the Money Print layout (or similar with the same
label semantics — see memory `project_money_print_layout.md`). The
`chatgpt_web` driver requires a signed-in chatgpt.com in the attached Chrome.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

from playwright.async_api import Page

from . import replay, replay_api
from . import lessons as lessons_mod
from .chatgpt_web import analyze_via_chatgpt_web
from .lib import audit
from .lib.capture_invariants import (
    CaptureExpect, CaptureInvariantError, assert_capture_ready,
)
from .lib.context import chart_session
from .profile_gate import verify_full_session


_FORECASTS_ROOT = (Path(__file__).parent.parent / "forecasts").resolve()
_PROFILES_ROOT = (Path(__file__).parent.parent / "profiles").resolve()
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView").resolve()

# Forecast stages — label, cursor target time, bars to step from F1.
STAGES: list[tuple[str, dtime, int]] = [
    ("F1", dtime(10, 0), 0),
    ("F2", dtime(12, 0), 120),
    ("F3", dtime(14, 0), 120),
]
# Step from F3 to session close for the reconciliation screenshot.
BARS_TO_CLOSE_FROM_F3 = 120


def _symbol_for_api(symbol: str) -> str:
    return symbol if "!" in symbol or ":" in symbol else f"{symbol}!"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_FORECAST_SYSTEM = """You are a day-trading forecast analyst for MNQ1! (Micro E-mini Nasdaq-100 futures, CME). Given a chart in Bar Replay mode with the cursor at a specific mid-session time, forecast how the REMAINDER of the trading day will unfold.

VISUAL REFERENCE (labels on the chart):
- ⭐ GOAT: standout move of the day
- Red circle: bearish pivot / short signal
- Green circle: bullish pivot / long signal
- ORANGE bank/castle icons: supply/resistance ("stored orders" above)
- BLUE bank/castle icons: demand/support ("stored orders" below)

TIME MARKERS (vertical colored lines):
- BLUE = 10:00 AM ET
- RED = 12:00 PM ET
- GREEN = 2:00 PM ET
- YELLOW = 4:00 PM ET
Session RECTANGLE: GREEN = bullish day so far, RED = bearish day so far.

CRITICAL: The blue "BarDate" label shows the cursor's exact date/time. You MAY use bars BEFORE the cursor as evidence. You MUST NOT use bars AFTER the cursor — those are un-replayed future bars (shaded/masked). If you reference a bar time, explicitly state whether it's before or after the cursor.

The chart may also show the PREVIOUS trading day on the left for context — that's historical and fully usable.

On TREND days specifically: if you see persistent lower-highs / higher-lows that refuse to reclaim value, WIDEN your close and LOD/HOD ranges aggressively. Trend days often extend further than midday action suggests.

REQUIRED OUTPUT (use exact headings):

## CURSOR CONTEXT
- Cursor date/time (from BarDate label)
- Bars observed so far this session (count, time range)
- What has happened so far in 1 sentence

## RANKED SIMILAR ARCHETYPES
3 ranked archetypes describing what KIND of session this most resembles — each with a 1-sentence rationale.

## PROJECTED PATH
- Between cursor and next time marker: expectation
- Between next marker and 14:00: expectation
- Between 14:00 and 16:00 (close): expectation
- Projected close price (range): ...
- Rest-of-day HOD (range): ...
- Rest-of-day LOD (range): ...

## TACTICAL BIAS
- Primary bias (long/short/neutral) with confidence %
- Key level to invalidate the bias
- Preferred entry zone
- R:R logic

## KEY LEVELS
- Overhead supply: ...
- Underlying demand: ...
- Pivot-to-watch: ...

## PREDICTION TAGS
Each tag on its own line with confidence %:
direction, structure, lunch_behavior, afternoon_drive, goat_direction, close_near_extreme.

{ACCUMULATED_LESSONS}"""


_RECONCILE_SYSTEM = """You are a forecast-accuracy adjudicator for day-trading predictions on MNQ1!. You will be given:
- 3 forecasts made at 10:00, 12:00, and 14:00 ET (F1, F2, F3) as structured JSON
- The actual full-day outcome (OHLC, pivots, structure tags) as structured JSON if available
- A screenshot of the completed session

Grade each forecast on:
1. **Direction** (hit/miss)
2. **Close price** — did actual close fall within the predicted range? If not, how far outside?
3. **HOD** — did predicted rest-of-day HOD capture actual HOD?
4. **LOD** — did predicted rest-of-day LOD capture actual LOD?
5. **Structure tags** — how well did predicted tags match actual?
6. **Tactical bias** — would the predicted bias (short/long) have been profitable?

Output format (use exact headings):

## ACTUAL OUTCOME
Open / Close / HOD / LOD / Shape (1 sentence)

## F1 GRADE (made at 10:00)
- Direction: ✓/✗
- Close range hit: ✓/✗ (actual vs predicted, miss in pts)
- HOD captured: ✓/✗ (miss in pts)
- LOD captured: ✓/✗ (miss in pts)
- Tags correct: list
- Tags wrong: list
- Bias profitable if traded: ✓/✗
- Overall score: X/6
- Biggest miss: one sentence

## F2 GRADE (made at 12:00)
[same structure]

## F3 GRADE (made at 14:00)
[same structure]

## FORECAST EVOLUTION
Did the forecasts improve/narrow as the day progressed? Where did each catch/miss the key signal?

## LESSONS
What would make forecasts better next time? Specific, actionable.

{ACCUMULATED_LESSONS}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_lessons_block() -> str:
    """Build the `## ACCUMULATED LESSONS` section for prompt injection.

    Reads top-N lessons from disk via `lessons` module. Returns the section
    header + bullet list, or empty string when no reconciliations exist
    yet — the empty case keeps prompts clean for first-time runs."""
    body = lessons_mod.format_for_prompt(n=10)
    if not body:
        return ""
    return (
        "## ACCUMULATED LESSONS (from prior reconciliations — apply these)\n"
        + body
    )


def _bardate_to_datetime(legend_text: str | None) -> datetime | None:
    """Parse the BarDate plot-values string like 'BarDate2,026.003.0018.0010.000.00'
    into a datetime. Returns None if unparseable. Known to drift in current TV
    build — use as a hint, not ground truth."""
    if not legend_text:
        return None
    m = re.match(r"BarDate\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)", legend_text)
    if not m:
        return None
    try:
        vals = [int(float(g.replace(",", ""))) for g in m.groups()]
        return datetime(vals[0], vals[1], vals[2], vals[3], vals[4])
    except (ValueError, TypeError):
        return None


async def _read_cursor(page: Page) -> datetime | None:
    """Best-effort read of the cursor time from the BarDate plot in the legend."""
    text = await page.evaluate(
        r"""() => {
            const items = Array.from(document.querySelectorAll('[data-qa-id="legend-source-item"]'));
            const bar = items.find(i => (i.innerText||'').trim().startsWith('BarDate'));
            return bar ? (bar.innerText||'').trim() : null;
        }"""
    )
    return _bardate_to_datetime(text)


async def _frame_session_view(page: Page) -> None:
    """Frame the chart so roughly one full RTH session is visible, with the
    cursor's day dominant in the view.

    Reused from the Replay Analysis Daily Profile Workflow. The recipe is
    pixel-position-dependent — tuned for a ~1728x996 viewport. Re-tune the
    mouse.move coordinates if running on a different screen size."""
    await page.bring_to_front()
    # Zoom out anchored left so more of the session's morning bars come in
    await page.mouse.move(200, 852)
    await page.wait_for_timeout(150)
    for _ in range(2):
        await page.mouse.wheel(0, 120)
        await page.wait_for_timeout(100)
    # Slight zoom in at center to hide previous-day sliver
    await page.mouse.move(828, 852)
    await page.mouse.wheel(0, -120)
    await page.wait_for_timeout(200)
    await page.keyboard.press("End")
    await page.wait_for_timeout(400)


async def _frame_with_cursor_right(page: Page) -> None:
    """Frame variant for forecast stages — zooms in on the right portion
    so the cursor's partial day dominates the view and pushes prior-day
    bars off the left edge."""
    await page.bring_to_front()
    await page.mouse.move(1300, 852)
    await page.wait_for_timeout(150)
    for _ in range(5):
        await page.mouse.wheel(0, -120)
        await page.wait_for_timeout(80)
    await page.keyboard.press("End")
    await page.wait_for_timeout(400)


async def _capture(
    page: Page, symbol: str, stage_label: str,
    *, expect: CaptureExpect | None = None,
) -> Path:
    """Screenshot the chart, return the path."""
    if expect is not None:
        await assert_capture_ready(page, expect)
    _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _SCREENSHOT_ROOT / f"{symbol}_forecast_{stage_label}_{ts}.png"
    await page.screenshot(path=str(path))
    return path


async def _navigate_to_10am(page: Page, date: datetime) -> datetime | None:
    """Navigate replay to 10:00 AM ET on `date` via the self-healing
    `replay.navigate_to` primitive. Returns the landed cursor (UTC).

    The previous picker-overshoots-by-~1h workaround + read-BarDate +
    step-forward dance was needed only for the DOM dialog path.
    `replay_api.selectDate()` lands the cursor exactly, so we ask for
    10:00 directly and use a tight tolerance — the recovery ladder
    handles broken Replay states automatically."""
    ten_am = date.replace(hour=10, minute=0, second=0, microsecond=0)
    landed = await replay.navigate_to(page, ten_am, tolerance_min=5)
    audit.log("daily_forecast.navigated",
              requested=str(ten_am), landed=landed.isoformat())
    return landed


async def _step_forward_bars(page: Page, bars: int) -> None:
    """Thin wrapper around replay.step_forward for consistency."""
    await replay.step_forward(page, bars)


def _forecast_file_paths(symbol: str, date_str: str, stage_label: str) -> tuple[Path, Path]:
    """Return (md_path, json_path) for a forecast stage."""
    _FORECASTS_ROOT.mkdir(parents=True, exist_ok=True)
    base = _FORECASTS_ROOT / f"{symbol}_{date_str}_{stage_label}"
    return base.with_suffix(".md"), base.with_suffix(".json")


def _reconciliation_file_paths(symbol: str, date_str: str) -> tuple[Path, Path]:
    _FORECASTS_ROOT.mkdir(parents=True, exist_ok=True)
    base = _FORECASTS_ROOT / f"{symbol}_{date_str}_reconciliation"
    return base.with_suffix(".md"), base.with_suffix(".json")


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------

async def _run_forecast_stage(
    page: Page, *, symbol: str, date_str: str,
    stage_label: str, cursor_time: dtime,
) -> dict | None:
    """Frame → gate → screenshot → ChatGPT → save. Returns the saved JSON
    dict, or None if the framing gate rejected the capture — in that case
    we skip the ChatGPT call and do NOT write any files, so bad-frame
    artifacts don't pollute the forecast store or confuse --resume."""
    with audit.timed("daily_forecast.stage", stage=stage_label, cursor=str(cursor_time)) as ac:
        await _frame_with_cursor_right(page)
        target_dt = datetime.combine(
            datetime.strptime(date_str, "%Y-%m-%d").date(), cursor_time,
        )
        expect = CaptureExpect(
            symbol=_symbol_for_api(symbol),
            interval="1m",
            replay_mode=True,
            cursor_time=target_dt,
            cursor_tolerance_min=10,
        )
        try:
            screenshot = await _capture(
                page, symbol,
                stage_label.lower() + cursor_time.strftime("%H%M"),
                expect=expect,
            )
        except CaptureInvariantError as e:
            audit.log("daily_forecast.stage.capture_invariant_fail",
                      stage=stage_label, invariant=e.reason, **e.details)
            ac["skipped"] = "capture_invariant_fail"
            ac["capture_invariant_reason"] = e.reason
            return None
        ac["screenshot"] = str(screenshot)

        # Gate — for forecast we accept partial frames, but verify minimum
        # morning visibility. A gate failure means the chart state can't be
        # trusted (cursor misaligned, replay not ready, bars missing), so we
        # abort this stage cleanly rather than forecast against a bad frame.
        gate = await verify_full_session(str(screenshot), cursor_time=cursor_time)
        ac["gate_ok"] = gate.ok
        ac["gate_reason"] = gate.reason
        if not gate.ok:
            audit.log("daily_forecast.stage.gate_fail",
                      stage=stage_label, reason=gate.reason)
            ac["skipped"] = "gate_fail"
            return None

        user_prompt = (
            f"Forecast remainder of {symbol}! {date_str} RTH session. "
            f"Cursor at ~{cursor_time.strftime('%H:%M')} ET per the BarDate label. "
            f"Bars before cursor = evidence; bars after = un-replayed future (do not use). "
            f"Use VISUAL REFERENCE and TIME MARKERS from the system prompt."
        )
        system_prompt = _FORECAST_SYSTEM.replace("{ACCUMULATED_LESSONS}", _render_lessons_block())
        text, _, _ = await analyze_via_chatgpt_web(
            image_path=str(screenshot),
            system_prompt=system_prompt,
            user_text=user_prompt,
            model="Thinking",
            timeout_s=300,
        )
        ac["response_chars"] = len(text)

        md_path, json_path = _forecast_file_paths(symbol, date_str, cursor_time.strftime("%H%M"))
        md_body = _build_forecast_md(
            symbol=symbol, date_str=date_str, stage_label=stage_label,
            cursor_time=cursor_time, screenshot=screenshot,
            gate_ok=gate.ok, gate_reason=gate.reason,
            response_text=text,
        )
        md_path.write_text(md_body)
        saved = {
            "symbol": symbol,
            "date": date_str,
            "cursor_time": cursor_time.strftime("%H:%M"),
            "stage": stage_label,
            "screenshot_path": str(screenshot),
            "gate": {"ok": gate.ok, "reason": gate.reason,
                     "session_first": str(gate.session_first) if gate.session_first else None,
                     "session_last": str(gate.session_last) if gate.session_last else None},
            "model": "chatgpt_thinking",
            "made_at": datetime.now().isoformat(timespec="seconds"),
            "raw_response": text,
        }
        json_path.write_text(json.dumps(saved, indent=2))
        ac["saved_to"] = str(json_path)
        return saved


def _build_forecast_md(*, symbol, date_str, stage_label, cursor_time,
                       screenshot, gate_ok, gate_reason, response_text) -> str:
    """Assemble the .md file with frontmatter + raw ChatGPT response."""
    fm = "\n".join([
        "---",
        f"symbol: {symbol}",
        f"date: {date_str}",
        f"cursor_time: {cursor_time.strftime('%H:%M')} ET",
        f"stage: {stage_label}",
        f"screenshot: {screenshot}",
        f"gate_ok: {gate_ok}",
        f"gate_reason: {gate_reason}",
        "model: chatgpt_thinking",
        f"made_at: {datetime.now().isoformat(timespec='seconds')}",
        "---",
        "",
    ])
    return fm + response_text.strip() + "\n"


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

async def _run_reconciliation(
    page: Page, *, symbol: str, date_str: str, stages_run: list[dict],
) -> dict:
    """Grade F1/F2/F3 against the actual day outcome."""
    with audit.timed("daily_forecast.reconciliation", date=date_str) as ac:
        await _frame_session_view(page)
        close_target = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=16, minute=0, second=0, microsecond=0,
        )
        screenshot = await _capture(
            page, symbol, "1600_close",
            expect=CaptureExpect(
                symbol=_symbol_for_api(symbol),
                interval="1m",
                replay_mode=True,
                cursor_time=close_target,
                cursor_tolerance_min=10,
            ),
        )
        ac["screenshot"] = str(screenshot)

        # Load completed-day profile if available — stronger ground truth than
        # re-deriving from the screenshot alone.
        profile_path = _PROFILES_ROOT / f"{symbol}_{date_str}.json"
        actual_block: dict = {}
        if profile_path.exists():
            try:
                prof = json.loads(profile_path.read_text())
                actual_block = {
                    "summary": prof.get("summary", {}),
                    "pivots": (prof.get("pivots") or [])[:6],
                    "tags": prof.get("tags", {}),
                }
            except Exception as e:
                audit.log("daily_forecast.reconciliation.profile_load_fail", err=str(e))

        # Compose user prompt — 3 forecasts + actual (if any)
        parts = []
        if actual_block:
            parts.append("## ACTUAL OUTCOME (from completed-day profile)")
            parts.append(json.dumps(actual_block, indent=2))
            parts.append("")
        else:
            parts.append("(No matching completed-day profile in DB — grade from screenshot alone.)")
            parts.append("")
        for s in stages_run:
            parts.append(f"## FORECAST {s['stage']} (made at {s['cursor_time']})")
            parts.append(s.get("raw_response", "(raw response missing)"))
            parts.append("")
        parts.append("Grade each forecast against the actual outcome using the exact format in the system prompt. Be fair and specific.")
        user_prompt = "\n".join(parts)

        system_prompt = _RECONCILE_SYSTEM.replace("{ACCUMULATED_LESSONS}", _render_lessons_block())
        text, _, _ = await analyze_via_chatgpt_web(
            image_path=str(screenshot),
            system_prompt=system_prompt,
            user_text=user_prompt,
            model="Thinking",
            timeout_s=300,
        )
        ac["response_chars"] = len(text)

        md_path, json_path = _reconciliation_file_paths(symbol, date_str)
        fm = "\n".join([
            "---",
            f"symbol: {symbol}",
            f"date: {date_str}",
            "stage: reconciliation",
            f"screenshot: {screenshot}",
            f"forecasts_graded: {[s['stage'] for s in stages_run]}",
            f"ground_truth_profile: {str(profile_path) if profile_path.exists() else 'none'}",
            f"made_at: {datetime.now().isoformat(timespec='seconds')}",
            "---",
            "",
        ])
        md_path.write_text(fm + text.strip() + "\n")
        saved = {
            "symbol": symbol,
            "date": date_str,
            "stage": "reconciliation",
            "screenshot_path": str(screenshot),
            "forecasts_graded": [s["stage"] for s in stages_run],
            "ground_truth_profile": str(profile_path) if profile_path.exists() else None,
            "made_at": datetime.now().isoformat(timespec="seconds"),
            "raw_response": text,
        }
        json_path.write_text(json.dumps(saved, indent=2))
        ac["saved_to"] = str(json_path)
        return saved


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _adhoc_stage_blocked(date_str: str, cursor_time: dtime) -> str | None:
    """Return a reason string if this stage should be skipped for ad-hoc
    reasons — wall-clock hasn't reached the stage's cursor time yet, or the
    target date is in the future. Returns None if the stage is free to run.

    Only compares wall-clock against target cursor time when `date_str` is
    today (ET). Historical replays always run (past data fully available)."""
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    now_et = datetime.now(_ET)
    today_et = now_et.date()
    if target < today_et:
        return None  # historical — always run
    if target > today_et:
        return f"target date {date_str} is in the future"
    # Same day — require wall clock to be at or past cursor time.
    target_dt = datetime.combine(target, cursor_time, tzinfo=_ET)
    if now_et < target_dt:
        return (f"wall clock {now_et.strftime('%H:%M ET')} "
                f"hasn't reached {cursor_time.strftime('%H:%M ET')}")
    return None


def _adhoc_reconciliation_blocked(date_str: str, profile_path: Path) -> str | None:
    """Return a reason string if reconciliation should be skipped. Two
    conditions: (1) no ground-truth profile on disk, (2) target day's RTH
    hasn't closed yet. Either makes a meaningful grading impossible."""
    if not profile_path.exists():
        return f"no profile at {profile_path.name}"
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    now_et = datetime.now(_ET)
    if target >= now_et.date():
        close_dt = datetime.combine(target, dtime(16, 0), tzinfo=_ET)
        if now_et < close_dt:
            return f"RTH not closed yet ({now_et.strftime('%H:%M ET')} < 16:00 ET)"
    return None


async def run_forecast_day(date_str: str, *, symbol: str = "MNQ1",
                           resume: bool = False,
                           adhoc: bool = False) -> dict:
    """Run the full forecast workflow for one trading day.

    Returns a dict summarizing the artifacts produced.

    `resume=True` skips stages whose .json already exists on disk —
    useful if an earlier run crashed partway and you want to pick up
    without re-driving the browser or re-paying for prior stages.

    `adhoc=True` is time-aware: for today's date, stages whose cursor
    time hasn't arrived are skipped (no bars to capture yet), and
    reconciliation is skipped if the completed-day profile doesn't
    exist OR RTH hasn't closed yet. Use this when invoking the
    pipeline intraday — unlike a scheduled eod run, adhoc won't
    produce gate-failed stages or blind reconciliations."""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"date must be YYYY-MM-DD, got {date_str!r}") from e

    skipped_stages: list[dict] = []
    saved_stages: list[dict] = []
    async with chart_session() as (_ctx, page):
        from . import layout_guard
        await layout_guard.ensure_layout(page)
        landed = await replay_api.set_symbol_in_place(
            page, symbol=_symbol_for_api(symbol), interval="1",
        )
        if landed is None:
            raise RuntimeError("set_symbol_in_place failed before daily forecast")
        audit.log("daily_forecast.chart_pinned", landed=landed)
        with audit.timed("daily_forecast.run_day",
                         date=date_str, symbol=symbol, adhoc=adhoc):
            # Navigate to 10:00 (F1 cursor) — soft-fail: log and continue
            # with whatever cursor TV ends up on rather than killing the
            # whole pipeline if any single stage's nav misses.
            try:
                cursor = await _navigate_to_10am(page, target_date)
                audit.log("daily_forecast.navigated", cursor=str(cursor))
            except RuntimeError as e:
                audit.log("daily_forecast.navigated.fail", err=str(e))

            for (label, cursor_time, step_bars) in STAGES:
                # Ad-hoc time gate — bail the remainder of the pipeline once
                # we hit a stage whose wall-clock time hasn't arrived yet.
                # (Later stages can't possibly be past-cursor either, so we
                # break rather than continue.)
                if adhoc:
                    reason = _adhoc_stage_blocked(date_str, cursor_time)
                    if reason:
                        audit.log("daily_forecast.stage.skip_adhoc_time",
                                  stage=label, reason=reason)
                        skipped_stages.append({"stage": label, "reason": reason})
                        break

                # Seek to absolute stage time via navigate_to instead of
                # bar-counting. Each stage has a known wall-clock target
                # (10:00, 12:00, 14:00 ET); navigate_to lands the cursor
                # exactly and self-heals if Replay state breaks. Soft-
                # fails on exhaustion so one bad stage doesn't kill the
                # whole day's pipeline.
                if step_bars > 0:
                    stage_target = datetime.combine(
                        target_date.date(), cursor_time,
                    )
                    try:
                        await replay.navigate_to(page, stage_target,
                                                  tolerance_min=5)
                    except RuntimeError as e:
                        audit.log("daily_forecast.stage.nav_fail",
                                  stage=label, err=str(e))

                _, json_path = _forecast_file_paths(symbol, date_str, cursor_time.strftime("%H%M"))
                if resume and json_path.exists():
                    audit.log("daily_forecast.stage.skip_existing", stage=label)
                    saved_stages.append(json.loads(json_path.read_text()))
                    continue

                saved = await _run_forecast_stage(
                    page, symbol=symbol, date_str=date_str,
                    stage_label=label, cursor_time=cursor_time,
                )
                if saved is None:
                    # Gate-fail — stage skipped, no artifact written.
                    skipped_stages.append({"stage": label, "reason": "gate_fail"})
                    continue
                saved_stages.append(saved)

            # Step to 16:00 for reconciliation screenshot (only if we
            # actually ran forecasts this session — otherwise no stepping
            # needed and no reconcile either).
            profile_path = _PROFILES_ROOT / f"{symbol}_{date_str}.json"
            _, recon_json = _reconciliation_file_paths(symbol, date_str)
            recon_blocked: str | None = None

            if not saved_stages:
                recon_blocked = "no forecast stages produced artifacts"
            elif adhoc:
                recon_blocked = _adhoc_reconciliation_blocked(date_str, profile_path)
            elif not profile_path.exists():
                # Fix #1 — always guard reconciliation behind profile existence,
                # even outside adhoc mode. A reconcile without ground truth is
                # worse than no reconcile (produces a bad file we then have to
                # clean up; also misleads the lessons + calibration feedback
                # loops).
                recon_blocked = f"no profile at {profile_path.name}"

            if recon_blocked:
                audit.log("daily_forecast.reconciliation.skipped",
                          reason=recon_blocked)
                reconciliation = {"skipped": True, "reason": recon_blocked}
            else:
                # Seek to 16:00 ET via navigate_to — same rationale as
                # the inter-stage seeks above.
                close_target = target_date.replace(
                    hour=16, minute=0, second=0, microsecond=0,
                )
                try:
                    await replay.navigate_to(page, close_target,
                                              tolerance_min=5)
                except RuntimeError as e:
                    audit.log("daily_forecast.reconciliation.nav_fail",
                              err=str(e))
                if resume and recon_json.exists():
                    audit.log("daily_forecast.reconciliation.skip_existing")
                    reconciliation = json.loads(recon_json.read_text())
                else:
                    reconciliation = await _run_reconciliation(
                        page, symbol=symbol, date_str=date_str, stages_run=saved_stages,
                    )

    return {
        "symbol": symbol,
        "date": date_str,
        "adhoc": adhoc,
        "stages": [{"stage": s["stage"], "cursor_time": s["cursor_time"]} for s in saved_stages],
        "skipped": skipped_stages,
        "reconciliation_file": str(_reconciliation_file_paths(symbol, date_str)[1]),
        "reconciliation_skipped_reason":
            reconciliation.get("reason") if isinstance(reconciliation, dict) and reconciliation.get("skipped") else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.daily_forecast")
    p.add_argument("date", help="Trading date in YYYY-MM-DD format")
    p.add_argument("--symbol", default="MNQ1", help="Symbol prefix for filenames")
    p.add_argument("--resume", action="store_true",
                   help="Skip stages whose .json already exists on disk")
    p.add_argument("--adhoc", action="store_true",
                   help="Time-aware intraday mode: skip stages whose cursor "
                        "time hasn't arrived yet; skip reconciliation if RTH "
                        "isn't closed or profile is missing. Use this when "
                        "running the pipeline mid-day without leaving gate-"
                        "failed artifacts behind.")
    args = p.parse_args()

    result = asyncio.run(run_forecast_day(
        args.date, symbol=args.symbol, resume=args.resume, adhoc=args.adhoc,
    ))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
