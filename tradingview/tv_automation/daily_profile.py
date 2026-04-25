"""Replay Analysis Daily Profile Workflow — profile a completed RTH
session and write it to the reference-day DB.

Pipeline (per day):
    1. Enter Bar Replay (Start new)
    2. select_start_date(target 17:00 ET) — TV picker drifts ~1h earlier,
       so 17:00 lands near 16:00 close
    3. Frame full RTH view
    4. Pre-profile gate (verify_full_session). On `morning_cut` /
       `close_cut`, reframe + retry BEFORE paying for the Thinking call.
    5. ChatGPT Thinking — profile prompt with Money Print semantics,
       asks for narrative sections AND a fenced JSON block with the
       structured fields the UI consumes.
    6. Split response → save profiles/{SYMBOL}_{YYYY-MM-DD}.md + .json

CLI:
    python -m tv_automation.daily_profile 2026-04-06
    python -m tv_automation.daily_profile 2026-04-06 --through 2026-04-10
    python -m tv_automation.daily_profile 2026-04-06 --resume
    python -m tv_automation.daily_profile 2026-04-06 --symbol MNQ1

Requires a TV tab at the Money Print layout (or equivalent — see memory
`project_money_print_layout.md`). `chatgpt_web` needs a signed-in
chatgpt.com in the attached Chrome.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import Page

from . import bar_reader, replay, replay_api
from .chatgpt_web import analyze_via_chatgpt_web
from .lib import audit
from .lib.capture_invariants import (
    CaptureExpect, CaptureInvariantError, assert_capture_ready,
)
from .lib.context import chart_session
from .profile_gate import verify_full_session, GateResult


_PROFILES_ROOT = (Path(__file__).parent.parent / "profiles").resolve()
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView").resolve()
_PARSE_FAIL_ROOT = (Path(__file__).parent.parent / "pine" / "parse_failures").resolve()


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROFILE_SYSTEM = """You are a day-trading session profiler for MNQ1! (Micro E-mini Nasdaq-100 futures, CME). You are given a completed RTH trading day in TradingView Bar Replay mode, cursor at session close. Profile the day's narrative, pivots, labels, and time-marker behavior so it can serve as a REFERENCE DAY compared against future sessions.

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
Session RECTANGLE: GREEN = bullish close, RED = bearish close.

Read prices from the y-axis. Times from the x-axis. The blue "BarDate" label shows the cursor's exact date/time.

IMPORTANT: The chart may show bars from the PREVIOUS trading day at the left edge (and globex/overnight bars to the right of the 16:00 RTH close). PROFILE ONLY the RTH session (09:30–16:00 ET) of the cursor's day. If the cursor is past 16:00 (e.g., at 17:00 or 18:00), the bars between 16:00 and the cursor are post-close globex — ignore them. Previous-day bars to the left are context only — ignore them. All prices/times in your output must be from the cursor's RTH session.

REQUIRED OUTPUT — produce the narrative sections below EXACTLY in order, then a fenced JSON block at the very end.

## DAY SUMMARY
- **Symbol / Date:** MNQ1! / {DATE} ({DOW})
- **Session color:** GREEN|RED / bullish|bearish
- **Open:** ... · **Close:** ...
- **HOD:** ... · **LOD:** ...
- **Net range:** +/-NNpt (+/-NN%); intraday span NNpt
- **Shape:** one-sentence shape summary

## PATH & PIVOTS
Two to four sentences narrating the session arc (open → morning → lunch → afternoon → close). Then a pivot table:

| Time (ET) | Type | Price |
|-----------|------|-------|
| 09:30 | Open | ... |
| ... | ... | ... |
| 16:00 | Close | ... |

## LABEL OBSERVATIONS
- **GOAT ⭐:** when/where + direction
- **Red circles:** pattern of behavior
- **Green circles:** pattern of behavior
- **Orange banks (supply):** price zones + whether broken/respected
- **Blue banks (demand):** price zones + whether broken/respected

## TIME-MARKER BEHAVIOR
- **10:00 (blue):** state/price action at that marker
- **12:00 (red):** ...
- **14:00 (green):** ...
- **16:00 (yellow):** ...

## DAILY PROFILE TAGS
- `direction: up|down|flat`
- `structure: <short_snake_case_phrase>`
- `open_type: gap_up_drive|gap_down_drive|flat_open|rotational_open|...`
- `lunch_behavior: <phrase>`
- `afternoon_drive: <phrase>`
- `goat_time: HH:MM`
- `goat_direction: up|down`
- `banks_respected: <phrase>`
- `banks_broken: <phrase>`
- `session_completion: full|partial`
- `late_reversal_attempt: yes|no`
- `close_near_extreme: yes_closer_to_HOD|yes_closer_to_LOD|no`

## REFERENCE-DAY TAKEAWAY
One or two sentences stating what KIND of day this was, framed so it reads as a comparable — e.g. "Bullish trend day with late reclaim, defended demand after early-PM flush".

## STRUCTURED JSON
```json
{
  "summary": {
    "direction": "up|down|flat",
    "box_color": "green|red",
    "structure": "<snake_case_phrase>",
    "open_approx": 0.0,
    "close_approx": 0.0,
    "hod_approx": 0.0,
    "lod_approx": 0.0,
    "net_range_pts_open_to_close": 0,
    "net_range_pct_open_to_close": 0.0,
    "intraday_span_pts": 0,
    "shape_sentence": "..."
  },
  "pivots": [
    {"time_et": "09:30", "price_approx": 0.0, "type": "open"}
  ],
  "labels": {
    "goat": {"in_rth": true, "time_et": "HH:MM", "direction": "up|down", "note": "..."},
    "red_circles": {"behavior": "..."},
    "green_circles": {"behavior": "..."},
    "orange_banks_supply": {"behavior": "..."},
    "blue_banks_demand": {"behavior": "..."}
  },
  "time_markers": {
    "10am_blue": "...",
    "12pm_red": "...",
    "2pm_green": "...",
    "4pm_yellow": "..."
  },
  "tags": {
    "direction": "up|down|flat",
    "structure": "...",
    "open_type": "...",
    "lunch_behavior": "...",
    "afternoon_drive": "...",
    "goat_time": "HH:MM",
    "goat_direction": "up|down",
    "peak_hour": 0,
    "late_reversal_attempt": true,
    "session_completion": "full|partial",
    "close_near_extreme": "yes_closer_to_HOD|yes_closer_to_LOD|no",
    "banks_respected": "...",
    "banks_broken": "..."
  },
  "takeaway": "..."
}
```

Return ONLY the narrative sections followed by the fenced JSON block. No preamble, no trailing commentary."""


# ---------------------------------------------------------------------------
# Framing + gate
# ---------------------------------------------------------------------------

async def _frame_session_view(page: Page, variant: int = 0) -> None:
    """Frame chart so one full RTH session dominates, cursor's day visible.

    Locates the time-axis strip dynamically via
    `div.chart-markup-table.time-axis` — wheel-scrolling inside the strip
    is how TradingView exposes horizontal zoom. Hardcoded pixel positions
    silently miss the 28px strip when the viewport shifts (watchlist
    sidebar open, dev tools, etc.); the selector-based approach doesn't.

    `variant` controls aggressiveness for gate retries. Calibrated on
    2026-04-21 against a 1728x996 viewport with the watchlist sidebar
    open; the base recipe is aggressive enough to include 09:30 on the
    first try, so a passing gate is common on attempt 0.
      0 — 8 wheel-downs left (baseline; shows ~03:00–18:00, small prev-day sliver)
      1 — 10 wheel-downs left (more aggressive; larger prev-day sliver)
      2 — 6 wheel-downs left + center zoom-in (less aggressive; hides prev-day)
    """
    await page.bring_to_front()
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(150)

    strip = page.locator("div.chart-markup-table.time-axis").first
    box = await strip.bounding_box()
    if box is None:
        raise RuntimeError("time-axis strip not visible — chart may not be ready")
    y = box["y"] + box["height"] / 2
    x_left = box["x"] + 150
    x_center = box["x"] + box["width"] / 2

    await page.mouse.move(x_left, y)
    await page.wait_for_timeout(150)
    loops = {0: 8, 1: 10, 2: 6}.get(variant, 8)
    for _ in range(loops):
        await page.mouse.wheel(0, 120)
        await page.wait_for_timeout(100)
    if variant == 2:
        await page.mouse.move(x_center, y)
        await page.mouse.wheel(0, -120)
        await page.wait_for_timeout(200)
    await page.keyboard.press("End")
    await page.wait_for_timeout(400)


async def _capture(
    page: Page, symbol: str, tag: str, *, expect: CaptureExpect | None = None,
) -> Path:
    """Screenshot the chart, return the path.

    When `expect` is given, runs `assert_capture_ready` first — silent
    flaky captures (wrong symbol, wrong TF, modal in frame, drawing
    tool armed, replay off, cursor at wrong bar) become loud
    `CaptureInvariantError`s instead of useless PNGs that the LLM
    misreads hours later."""
    if expect is not None:
        await assert_capture_ready(page, expect)
    _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _SCREENSHOT_ROOT / f"{symbol}_profile_{tag}_{ts}.png"
    await page.screenshot(path=str(path))
    return path


async def _frame_and_gate(
    page: Page, symbol: str, *, close_target: datetime | None = None,
) -> tuple[Path, GateResult]:
    """Frame → gate, with up to 2 retries on morning_cut / close_cut.

    Returns (final_screenshot_path, final_gate_result). Profiling proceeds
    even if the final gate fails — the gate failure is recorded in the
    artifact so it's visible when comparing reference days.

    `close_target` (when provided) seeds the capture-invariant check
    so the screenshot is gated on Replay being active and the cursor
    sitting near the requested close time. Cursor check is soft on
    this wire-up — fires audit events but doesn't break workflows
    while we baseline real cursor drift."""
    expect = CaptureExpect(
        symbol=symbol if "!" in symbol else f"{symbol}!",
        interval="1m",
        replay_mode=True,
        cursor_time=close_target,
        cursor_tolerance_min=30,
        soft_cursor=True,
    ) if close_target is not None else None

    last_screenshot: Path | None = None
    last_gate: GateResult | None = None
    for attempt in range(3):
        await _frame_session_view(page, variant=attempt)
        last_screenshot = await _capture(page, symbol, f"frame{attempt}", expect=expect)
        last_gate = await verify_full_session(str(last_screenshot))
        audit.log("daily_profile.gate",
                  attempt=attempt, ok=last_gate.ok, reason=last_gate.reason)
        if last_gate.ok:
            break
        if last_gate.reason and "morning_cut" not in last_gate.reason and "close_cut" not in last_gate.reason:
            # Unreadable labels or parse failure — a reframe is unlikely
            # to help. Bail and profile anyway with the gate-fail noted.
            break
    assert last_screenshot is not None and last_gate is not None
    return last_screenshot, last_gate


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

_BARDATE_RX = re.compile(
    r"BarDate\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)"
)


def _bardate_to_datetime(legend_text: str | None) -> datetime | None:
    if not legend_text:
        return None
    m = _BARDATE_RX.match(legend_text)
    if not m:
        return None
    try:
        vals = [int(float(g.replace(",", ""))) for g in m.groups()]
        return datetime(vals[0], vals[1], vals[2], vals[3], vals[4])
    except (ValueError, TypeError):
        return None


_ET = ZoneInfo("America/New_York")


async def _read_cursor(page: Page) -> datetime | None:
    """Replay cursor time as naive ET. Prefers TV's JS API
    (`replayApi.currentDate()`, exact epoch ms) and falls back to
    parsing the BarDate legend when the API isn't reachable."""
    api_dt = await replay_api.current_replay_date(page)
    if api_dt is not None:
        return api_dt.astimezone(_ET).replace(tzinfo=None)

    text = await page.evaluate(
        r"""() => {
            const items = Array.from(document.querySelectorAll('[data-qa-id="legend-source-item"]'));
            const bar = items.find(i => (i.innerText||'').trim().startsWith('BarDate'));
            return bar ? (bar.innerText||'').trim() : null;
        }"""
    )
    return _bardate_to_datetime(text)


async def _navigate_to_session_close(page: Page, date: datetime) -> None:
    """Navigate replay to ~16:00 ET on `date`.

    TV's picker lands earlier than requested, so we aim at 17:00 for a
    target of 16:00. Drift is usually ~1h but occasionally 2h — on those
    days the landing sits at 15:00, which crops bars past 15:00 in
    Replay and trips the profile gate's close_cut. We read BarDate and
    step forward the remaining minutes to close the gap."""
    # Always enter fresh. A Replay session parked at a prior cursor (e.g.
    # from a live forecast stage) can leave the Select-date dialog refusing
    # to re-mount. Exit-then-enter costs ~1s and makes the picker deterministic.
    if await replay.is_active(page):
        await replay.exit_replay(page)
    await replay.enter_replay(page)
    target = date.replace(hour=17, minute=0, second=0, microsecond=0)
    await replay.select_start_date(page, target)
    await page.wait_for_timeout(800)

    # BarDate legend sometimes takes longer to populate when the cursor
    # lands near session-close boundary — retry up to 3x before giving up.
    cursor = None
    for attempt in range(3):
        cursor = await _read_cursor(page)
        if cursor is not None:
            break
        await page.wait_for_timeout(500)
    close_target = date.replace(hour=16, minute=0, second=0, microsecond=0)
    if cursor is not None:
        delta_min = int((close_target - cursor).total_seconds() // 60)
        audit.log("daily_profile.navigate.initial",
                  requested=str(target), landed=str(cursor), delta_min=delta_min)
        MAX_ADJUST = 240
        if 0 < delta_min <= MAX_ADJUST:
            await replay.step_forward(page, delta_min)
    else:
        audit.log("daily_profile.navigate.no_bardate")

    audit.log("daily_profile.navigated", date=date.strftime("%Y-%m-%d"))


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_STRUCTURED_HEADER_RX = re.compile(r"^#{1,3}\s*STRUCTURED\s+JSON\s*$", re.MULTILINE)


def _extract_balanced_json(text: str, start: int) -> tuple[dict, int] | None:
    """Find the first `{...}` starting at or after `start` with balanced braces
    (string-aware) and return (parsed_dict, end_index). None if not found or
    unparseable."""
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
                    return json.loads(text[i : j + 1]), j + 1
                except json.JSONDecodeError:
                    return None
    return None


def _split_response(text: str) -> tuple[str, dict | None]:
    """Split the Thinking response into (narrative_md, structured_json).

    Accepts the JSON block in three shapes:
      * fenced with ```json … ```
      * unfenced (bare `{...}` at the end of the response)
      * prefixed with a `## STRUCTURED JSON` header with or without fences

    Returns (narrative, None) if no parseable JSON object is found —
    caller saves the narrative anyway for manual inspection."""
    # Prefer content before the STRUCTURED JSON header when it exists.
    header = _STRUCTURED_HEADER_RX.search(text)
    narrative_end = header.start() if header else len(text)

    # Try to extract JSON from the tail (after header if present, else whole text).
    search_start = header.end() if header else 0
    result = _extract_balanced_json(text, search_start)
    if result is None and header is not None:
        # Header exists but JSON after it was unparseable — narrative still
        # stops at the header.
        return text[:narrative_end].rstrip(), None
    if result is None:
        return text.strip(), None
    return text[:narrative_end].rstrip(), result[0]


# ---------------------------------------------------------------------------
# Stage: profile one day
# ---------------------------------------------------------------------------

def _profile_file_paths(symbol: str, date_str: str) -> tuple[Path, Path]:
    _PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
    base = _PROFILES_ROOT / f"{symbol}_{date_str}"
    return base.with_suffix(".md"), base.with_suffix(".json")


def _build_profile_md(*, symbol: str, date_str: str, dow: str,
                      screenshot: Path, gate: GateResult,
                      narrative: str) -> str:
    """Assemble the .md file: frontmatter + narrative from the model."""
    gate_line = (
        f"{'pass' if gate.ok else 'fail'} "
        f"(first={gate.session_first or '?'}, last={gate.session_last or '?'})"
        if gate.reason == "ok" or gate.session_first or gate.session_last
        else f"{'pass' if gate.ok else 'fail'} ({gate.reason})"
    )
    fm = "\n".join([
        "---",
        f"symbol: {symbol}!",
        f"date: {date_str}",
        f"dow: {dow}",
        "timeframe: 1m",
        "session: RTH",
        f"cursor_ts: {date_str} ~16:00",
        "session_complete: true",
        "layout: Money Print",
        "provider: chatgpt_web",
        "model: Thinking",
        f"screenshot: {screenshot}",
        f"gate_result: {gate_line}",
        f"profiled_at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "---",
        "",
    ])
    return fm + narrative.rstrip() + "\n"


async def run_profile_day(date_str: str, *, symbol: str = "MNQ1",
                          resume: bool = False) -> dict:
    """Profile one completed RTH day. Returns artifact summary."""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"date must be YYYY-MM-DD, got {date_str!r}") from e
    dow = target_date.strftime("%a")

    md_path, json_path = _profile_file_paths(symbol, date_str)
    if resume and json_path.exists():
        audit.log("daily_profile.skip_existing", date=date_str)
        return {"symbol": symbol, "date": date_str, "skipped": True,
                "json_path": str(json_path)}

    async with chart_session() as (_ctx, page):
        with audit.timed("daily_profile.run_day", date=date_str, symbol=symbol) as ac:
            await _navigate_to_session_close(page, target_date)
            close_target = target_date.replace(
                hour=16, minute=0, second=0, microsecond=0,
            )
            screenshot, gate = await _frame_and_gate(
                page, symbol, close_target=close_target,
            )
            ac["screenshot"] = str(screenshot)
            ac["gate_ok"] = gate.ok
            ac["gate_reason"] = gate.reason

            # Numerical ground truth — read OHLC from chart memory
            # while the cursor is parked at close. Survives whatever
            # the vision LLM later reports about the same session, and
            # gives the reconcile step a deterministic actual_summary.
            session_open = target_date.replace(
                hour=9, minute=30, second=0, microsecond=0,
            )
            api_ohlc = await bar_reader.read_session_ohlc(
                page, start_et=session_open, end_et=close_target,
            )

            user_prompt = (
                f"Profile the {symbol}! RTH session for {date_str} ({dow}). "
                f"Cursor is at session close (~16:00 ET). Use VISUAL REFERENCE "
                f"and TIME MARKERS from the system prompt. Return narrative "
                f"sections followed by the fenced JSON block."
            )
            text, _, _ = await analyze_via_chatgpt_web(
                image_path=str(screenshot),
                system_prompt=_PROFILE_SYSTEM,
                user_text=user_prompt,
                model="Thinking",
                timeout_s=600,
            )
            ac["response_chars"] = len(text)

            narrative, structured = _split_response(text)
            if structured is None:
                _PARSE_FAIL_ROOT.mkdir(parents=True, exist_ok=True)
                dump = _PARSE_FAIL_ROOT / f"profile_{symbol}_{date_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                dump.write_text(text)
                audit.log("daily_profile.parse_fail", dump=str(dump))
                ac["parse_fail_dump"] = str(dump)

            md_body = _build_profile_md(
                symbol=symbol, date_str=date_str, dow=dow,
                screenshot=screenshot, gate=gate, narrative=narrative,
            )
            md_path.write_text(md_body)

            saved: dict = {
                "symbol": f"{symbol}!",
                "date": date_str,
                "dow": dow,
                "timeframe": "1m",
                "session": "RTH",
                "session_complete": True,
                "cursor_ts_approx": f"{date_str}T16:00:00-04:00",
                "layout": "Money Print",
                "provider": "chatgpt_web",
                "model": "Thinking",
                "screenshot_path": str(screenshot),
                "gate": {
                    "ok": gate.ok,
                    "reason": gate.reason,
                    "first": str(gate.session_first) if gate.session_first else None,
                    "last": str(gate.session_last) if gate.session_last else None,
                },
                "profiled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            if structured is not None:
                saved.update(structured)
            else:
                saved["raw_response"] = text
            if api_ohlc is not None:
                saved["actual_summary_api"] = api_ohlc

            json_path.write_text(json.dumps(saved, indent=2))
            ac["saved_to"] = str(json_path)
            return {
                "symbol": symbol, "date": date_str,
                "md_path": str(md_path), "json_path": str(json_path),
                "gate_ok": gate.ok, "parsed_structured": structured is not None,
            }


# ---------------------------------------------------------------------------
# Week orchestration
# ---------------------------------------------------------------------------

def _weekday_range(start: str, end: str) -> list[str]:
    """Inclusive Mon–Fri date strings between start and end (YYYY-MM-DD).
    Weekends are skipped; US market holidays are NOT skipped — caller's
    responsibility to pick a valid week."""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    if e < s:
        raise ValueError(f"--through {end} is before start {start}")
    out: list[str] = []
    d = s
    while d <= e:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


async def run_profile_range(start: str, end: str | None, *,
                            symbol: str = "MNQ1",
                            resume: bool = False) -> list[dict]:
    """Profile each weekday in [start, end]. Single date if end is None."""
    dates = _weekday_range(start, end or start)
    results: list[dict] = []
    for d in dates:
        with audit.timed("daily_profile.range_day", date=d):
            try:
                r = await run_profile_day(d, symbol=symbol, resume=resume)
                results.append(r)
            except Exception as e:
                audit.log("daily_profile.range_day.error", date=d, err=str(e))
                results.append({"symbol": symbol, "date": d, "error": str(e)})
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.daily_profile")
    p.add_argument("date", help="Start trading date (YYYY-MM-DD)")
    p.add_argument("--through", dest="through", default=None,
                   help="End trading date (YYYY-MM-DD, inclusive). "
                        "Profiles each weekday in the range.")
    p.add_argument("--symbol", default="MNQ1",
                   help="Filename prefix (default MNQ1)")
    p.add_argument("--resume", action="store_true",
                   help="Skip dates whose .json already exists on disk")
    args = p.parse_args()

    results = asyncio.run(run_profile_range(
        args.date, args.through, symbol=args.symbol, resume=args.resume,
    ))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    _main()
