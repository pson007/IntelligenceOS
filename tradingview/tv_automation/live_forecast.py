"""Live Forecast Workflow — F1/F2/F3 fired at actual 10:00/12:00/14:00 ET
against the LIVE chart (not Bar Replay).

Counterpart to daily_forecast.py. Same prompt shape, same output shape
(forecasts/{SYMBOL}_{YYYY-MM-DD}_{HHMM}.{md,json}), but no Replay
navigation — the chart is assumed to already be live on `symbol`.

CLI:
    python -m tv_automation.live_forecast F1
    python -m tv_automation.live_forecast F2 --symbol MNQ1
    python -m tv_automation.live_forecast F3 --date 2026-04-21

Stage → cursor-time map:
    F1 → 10:00 ET
    F2 → 12:00 ET
    F3 → 14:00 ET

When called from launchd, the fire time IS the cursor time — we don't
re-compute it. If invoked >30 minutes after the target, the run aborts
with exit 2 (wake-after-sleep stale-trigger guard). Override the abort
with --force if running the stage slightly late by hand is intentional.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, time as dtime
from pathlib import Path

from playwright.async_api import Page

from . import lessons as lessons_mod, replay, replay_api
from .chatgpt_web import analyze_via_chatgpt_web
from .forecast_capture import frame_partial_session, hide_widget_panel
from .lib import audit
from .lib.capture_invariants import CaptureExpect, assert_capture_ready
from .lib.context import chart_session
from .profile_gate import verify_full_session


_FORECASTS_ROOT = (Path(__file__).parent.parent / "forecasts").resolve()
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView").resolve()

STAGE_CURSOR: dict[str, dtime] = {
    "F1": dtime(10, 0),
    "F2": dtime(12, 0),
    "F3": dtime(14, 0),
}

# Maximum staleness: if launchd fires late (e.g. machine woke from sleep
# after the trigger time), abort past this threshold rather than forecast
# at a misleading cursor time.
STALE_MINUTES = 30


def _symbol_for_api(symbol: str) -> str:
    return symbol if "!" in symbol or ":" in symbol else f"{symbol}!"


_LIVE_FORECAST_SYSTEM = """You are a day-trading forecast analyst for MNQ1! (Micro E-mini Nasdaq-100 futures, CME). Given a LIVE chart with the session in progress, forecast how the REMAINDER of the trading day will unfold.

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

CRITICAL: This is a LIVE chart, not Bar Replay. The rightmost bar is the CURRENT bar. There are NO future bars — unlike Replay there is no shaded/masked region. Use ALL bars visible on today's session as evidence. The chart may also show the PREVIOUS trading day on the left for context — that's historical and fully usable.

On TREND days specifically: if you see persistent lower-highs / higher-lows that refuse to reclaim value, WIDEN your close and LOD/HOD ranges aggressively. Trend days often extend further than midday action suggests.

REQUIRED OUTPUT (use exact headings):

## CURSOR CONTEXT
- Cursor date/time (stated by the caller, matches current bar)
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


def _render_lessons_block() -> str:
    body = lessons_mod.format_for_prompt(n=10)
    if not body:
        return ""
    return "## ACCUMULATED LESSONS (from prior reconciliations — apply these)\n" + body


async def _capture(
    page: Page, symbol: str, stage_label: str,
    *, expect: CaptureExpect | None = None,
) -> Path:
    """Hides the right-sidebar widget panel before capture so the chart
    canvas takes the full viewport width."""
    await hide_widget_panel(page)
    if expect is not None:
        await assert_capture_ready(page, expect)
    _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _SCREENSHOT_ROOT / f"{symbol}_live_{stage_label}_{ts}.png"
    await page.screenshot(path=str(path))
    return path


def _forecast_file_paths(symbol: str, date_str: str, stage_label: str) -> tuple[Path, Path]:
    _FORECASTS_ROOT.mkdir(parents=True, exist_ok=True)
    base = _FORECASTS_ROOT / f"{symbol}_{date_str}_{stage_label}"
    return base.with_suffix(".md"), base.with_suffix(".json")


async def run_live_stage(
    stage: str, *, symbol: str = "MNQ1", date_str: str | None = None,
    force: bool = False,
) -> dict:
    """Run one live forecast stage (F1/F2/F3) against the current live chart."""
    if stage not in STAGE_CURSOR:
        raise ValueError(f"stage must be one of F1/F2/F3, got {stage!r}")
    cursor_time = STAGE_CURSOR[stage]
    date_str = date_str or date.today().strftime("%Y-%m-%d")

    now = datetime.now()
    target = datetime.combine(now.date(), cursor_time)
    drift_min = int((now - target).total_seconds() // 60)
    if not force and (drift_min < -5 or drift_min > STALE_MINUTES):
        audit.log("live_forecast.stale", stage=stage, drift_min=drift_min)
        raise SystemExit(2)

    # Use HHMM filename convention so reconciliation finds these files
    # alongside the Replay-produced ones.
    stage_tag = cursor_time.strftime("%H%M")
    md_path, json_path = _forecast_file_paths(symbol, date_str, stage_tag)
    if json_path.exists():
        audit.log("live_forecast.skip_existing", stage=stage, path=str(json_path))
        return {"skipped": True, "path": str(json_path)}

    async with chart_session() as (_ctx, page):
        await replay.exit_replay(page)
        landed = await replay_api.set_symbol_in_place(
            page, symbol=_symbol_for_api(symbol), interval="1",
        )
        if landed is None:
            raise RuntimeError("set_symbol_in_place failed before live forecast")
        audit.log("live_forecast.chart_pinned", landed=landed)
        with audit.timed("live_forecast.stage", stage=stage, date=date_str) as ac:
            await frame_partial_session(page)
            screenshot = await _capture(
                page, symbol, stage.lower() + stage_tag,
                expect=CaptureExpect(
                    symbol=_symbol_for_api(symbol),
                    interval="1m",
                    replay_mode=False,
                ),
            )
            ac["screenshot"] = str(screenshot)

            gate = await verify_full_session(str(screenshot), cursor_time=cursor_time)
            ac["gate_ok"] = gate.ok
            ac["gate_reason"] = gate.reason

            user_prompt = (
                f"Forecast remainder of {symbol}! {date_str} RTH session. "
                f"LIVE chart at ~{cursor_time.strftime('%H:%M')} ET (fired by scheduler at "
                f"{now.strftime('%H:%M:%S')} local). All visible bars are real — no Replay masking."
            )
            system_prompt = _LIVE_FORECAST_SYSTEM.replace("{ACCUMULATED_LESSONS}", _render_lessons_block())
            text, _, _ = await analyze_via_chatgpt_web(
                image_path=str(screenshot),
                system_prompt=system_prompt,
                user_text=user_prompt,
                model="Thinking",
                timeout_s=300,
            )
            ac["response_chars"] = len(text)

            fm = "\n".join([
                "---",
                f"symbol: {symbol}",
                f"date: {date_str}",
                f"cursor_time: {cursor_time.strftime('%H:%M')} ET",
                f"stage: {stage}",
                "mode: live",
                f"screenshot: {screenshot}",
                f"gate_ok: {gate.ok}",
                f"gate_reason: {gate.reason}",
                "model: chatgpt_thinking",
                f"made_at: {datetime.now().isoformat(timespec='seconds')}",
                "---",
                "",
            ])
            md_path.write_text(fm + text.strip() + "\n")
            saved = {
                "symbol": symbol,
                "date": date_str,
                "cursor_time": cursor_time.strftime("%H:%M"),
                "stage": stage,
                "mode": "live",
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


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.live_forecast")
    p.add_argument("stage", choices=sorted(STAGE_CURSOR.keys()),
                   help="Forecast stage: F1 (10:00), F2 (12:00), F3 (14:00)")
    p.add_argument("--symbol", default="MNQ1")
    p.add_argument("--date", dest="date_str", default=None,
                   help="Override trading date (default: today)")
    p.add_argument("--force", action="store_true",
                   help="Run even if current time is >30 min past the stage cursor")
    args = p.parse_args()

    try:
        result = asyncio.run(run_live_stage(
            args.stage, symbol=args.symbol, date_str=args.date_str, force=args.force,
        ))
        print(json.dumps(result, indent=2))
    except SystemExit as e:
        if e.code == 2:
            print(f"Aborted: current time >{STALE_MINUTES}min past {args.stage} cursor — use --force to override", file=sys.stderr)
        raise


if __name__ == "__main__":
    _main()
