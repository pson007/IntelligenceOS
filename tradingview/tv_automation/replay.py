"""TradingView Bar Replay primitives.

Drives the chart's Bar Replay feature so a caller can:
  * Activate / deactivate Replay mode
  * Pick a starting date (T₀)
  * Step forward/backward a bar at a time via keyboard shortcuts
  * Change playback speed / replay TF
  * Read the current replay cursor (best-effort)

Replay selectors were captured by `probes/probe_replay.py` on
2026-04-19 against TradingView's current build. Every control in the
playback strip has two or more DOM copies for responsive layout, so
every lookup goes through `lib.visible_locator.pick_visible` — Playwright's
`.first` silently picks the hidden duplicate otherwise.

Known-working surface:
  * Activate/deactivate via `button[aria-label="Bar replay"]`
  * Strip container `div[data-name="replay-bottom-toolbar"]` (Replay-active marker)
  * `Select date` / `Replay speed` / `Update interval` / `Jump to real-time chart`
    / `Exit Bar Replay` buttons inside the strip
  * Keyboard `Shift+→` / `Shift+←` steps one bar

Known-unknown (see REPLAY_BENCH_PLAN.md):
  * Date picker modal — input format not yet catalogued
    (probed by `probes/probe_replay_datepicker.py`)
  * `Select date` button text after a date is picked — parsed
    best-effort by `current_replay_ts`; falls back to returning the
    raw text for client-side bookkeeping
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from playwright.async_api import Page

from .lib import audit
from .lib.errors import SelectorDriftError
from .lib.visible_locator import any_visible, pick_visible, wait_visible

# ---------------------------------------------------------------------------
# Selectors — stable anchors from the probe snapshot. Kept as module
# constants so the next probe pass updates one line.
# ---------------------------------------------------------------------------

_TOGGLE = 'button[aria-label="Bar replay"]'
_STRIP = 'div[data-name="replay-bottom-toolbar"]'

# After clicking the toolbar Replay button, TV shows a modal IF it has
# saved state from a prior replay ("Continue your last replay?"). The
# Start new button is the workflow that jumps chart view to the picked
# date — Continue resumes at the old cursor, which for our bench is
# always the wrong place. So we always click Start new.
_MODAL_START_NEW = 'button[data-qa-id="start_new-btn"]'
_MODAL_CONTINUE = 'button[data-qa-id="ok-btn"]'

# Class prefix `selectDateBar__button` is stable; the `title` attribute
# is dropped when TV's Replay Trading panel is open, so title-based
# selectors break in that state.
_SELECT_DATE = ('div[data-role="button"][class*="selectDateBar__button"], '
                'div[data-role="button"][title="Select date"]')
_START_MODE = 'div[data-role="button"][data-qa-id="select-date-bar-mode-menu"]'
_SPEED = 'div[data-role="button"][title="Replay speed"]'
_INTERVAL = 'div[data-role="button"][title="Update interval"]'
_JUMP_LIVE = 'div[data-role="button"][title="Jump to real-time chart"]'
_EXIT = 'div[data-role="button"][title="Exit Bar Replay"]'
_PLAY = 'div[data-role="button"][title="Play"]'
# Forward loses its `title` when TV's Replay Trading panel is open.
# Located via DOM walk from Play (which keeps its title) rather than
# a CSS selector. See `_click_forward_via_js`.

# TV's speed options in the menu. Text label → click target.
SpeedLabel = Literal["0.1x", "0.3x", "0.5x", "1x", "3x", "10x"]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


async def is_active(page: Page) -> bool:
    """True when Replay mode is currently engaged (strip is rendered)."""
    return await any_visible(page, _STRIP)


# ---------------------------------------------------------------------------
# Activation / exit
# ---------------------------------------------------------------------------


async def enter_replay(page: Page) -> None:
    """Activate Bar Replay via the full user workflow: toolbar toggle →
    handle 'Continue your last replay?' modal by clicking Start new →
    wait for strip.

    Start new (vs Continue) is what makes TV auto-scroll the chart VIEW
    to the picked date during `select_start_date`. Continue resumes the
    prior cursor position and leaves the view at live-time, which breaks
    the analyze screenshot (LLM sees current prices, not historical).
    """
    if await is_active(page):
        audit.log("replay.enter.skip", reason="already_active")
        return
    toggle = await pick_visible(page, _TOGGLE)
    if toggle is None:
        raise SelectorDriftError("toggle", "replay", [_TOGGLE])
    await toggle.click()

    # Modal appears within ~1s if TV has saved replay state. When no
    # state exists (fresh profile), Replay activates directly with no
    # modal. Poll briefly for either outcome.
    start_new = await wait_visible(page, _MODAL_START_NEW, timeout_ms=1500)
    if start_new is not None:
        await start_new.click()
        audit.log("replay.enter.start_new")

    strip = await wait_visible(page, _STRIP, timeout_ms=5000)
    if strip is None:
        raise SelectorDriftError("strip", "replay", [_STRIP])
    # Let the strip's inner controls hydrate before callers hit them.
    await page.wait_for_timeout(400)
    audit.log("replay.enter")


async def exit_replay(page: Page) -> None:
    """Exit Bar Replay. No-op if not active. Prefers the strip's dedicated
    Exit button (leaves the chart in its Replay-entry state) and falls
    back to clicking the toolbar toggle."""
    if not await is_active(page):
        audit.log("replay.exit.skip", reason="not_active")
        return
    exit_btn = await pick_visible(page, _EXIT)
    used = "exit_button"
    if exit_btn is not None:
        await exit_btn.click()
    else:
        # Fall back to toolbar toggle — still a Replay toggle.
        toggle = await pick_visible(page, _TOGGLE)
        if toggle is None:
            raise SelectorDriftError("exit", "replay", [_EXIT, _TOGGLE])
        await toggle.click()
        used = "toolbar_toggle"
    # Wait for the strip to disappear. TV can take a while after a
    # select-date jump (it's re-rendering the chart at the new cursor).
    # 8s covers observed worst-case; still far under the UI's patience.
    for _ in range(40):
        if not await is_active(page):
            audit.log("replay.exit", via=used)
            return
        await page.wait_for_timeout(200)
    raise SelectorDriftError("strip_still_visible", "replay", [_STRIP])


# ---------------------------------------------------------------------------
# Self-healing navigation
# ---------------------------------------------------------------------------


_BARDATE_RX = re.compile(
    r"BarDate\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)"
)


_STRIP_DATE_RX = re.compile(
    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2,4})"
    r"(?:\s+(\d{1,2}):(\d{2})\s*(AM|PM)?)?",
    re.IGNORECASE,
)
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_strip_date(text: str) -> datetime | None:
    """Parse TV's Select-date button text (e.g. `Mon 20 Apr 26 12:00 PM`)
    into a tz-aware ET datetime. The button shows whatever cursor
    Replay is parked at, or 'Select date' when none is set."""
    if not text or text.lower().strip() == "select date":
        return None
    m = _STRIP_DATE_RX.search(text)
    if not m:
        return None
    try:
        day = int(m.group(1))
        month = _MONTH_MAP.get(m.group(2).lower())
        year = int(m.group(3))
        if year < 100:
            year += 2000
        hour = int(m.group(4)) if m.group(4) else 0
        minute = int(m.group(5)) if m.group(5) else 0
        ampm = (m.group(6) or "").upper()
        if ampm == "PM" and hour < 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        from zoneinfo import ZoneInfo
        from datetime import timezone
        et = ZoneInfo("America/New_York")
        naive = datetime(year, month, day, hour, minute)
        return naive.replace(tzinfo=et).astimezone(timezone.utc)
    except (ValueError, TypeError, KeyError):
        return None


async def _read_strip_date(page: Page) -> str | None:
    """Return the Select-date button's current text, or None."""
    try:
        return await page.evaluate(r"""() => {
            const strip = document.querySelector(
                'div[data-name="replay-bottom-toolbar"]'
            );
            if (!strip) return null;
            const btn = strip.querySelector(
                'div[data-role="button"][class*="selectDateBar__button"], '
              + 'div[data-role="button"][title="Select date"]'
            );
            return btn ? (btn.innerText || '').trim() : null;
        }""")
    except Exception:
        return None


async def confirm_cursor(page: Page) -> datetime | None:
    """Read the current Replay cursor — tries API first, falls back to
    BarDate legend, then to the Replay strip's Select-date button text.

    The API path (`replayApi.currentDate()`) returns None when TV is
    in a half-mounted Replay state. The BarDate legend item is the
    next-best signal but isn't always present (chart's data window may
    not include it). The strip-date button is always rendered when
    Replay is active and shows the active cursor (or 'Select date'
    when none is set).

    Returns a UTC-aware datetime when readable, None when no source
    confirms a cursor."""
    from . import replay_api
    cur = await replay_api.current_replay_date(page)
    if cur is not None:
        return cur

    text = await page.evaluate(
        r"""() => {
            const items = Array.from(document.querySelectorAll(
                '[data-qa-id="legend-source-item"]'
            ));
            const bar = items.find(i =>
                (i.innerText || '').trim().startsWith('BarDate')
            );
            return bar ? (bar.innerText || '').trim() : null;
        }"""
    )
    if text:
        m = _BARDATE_RX.match(text)
        if m:
            try:
                from zoneinfo import ZoneInfo
                from datetime import timezone
                et = ZoneInfo("America/New_York")
                vals = [int(float(g.replace(",", ""))) for g in m.groups()]
                naive = datetime(vals[0], vals[1], vals[2], vals[3], vals[4])
                return naive.replace(tzinfo=et).astimezone(timezone.utc)
            except (ValueError, TypeError):
                pass

    strip_text = await _read_strip_date(page)
    return _parse_strip_date(strip_text) if strip_text else None


async def _ensure_history_loaded(
    page: Page, target_epoch_s: int, *,
    max_batches: int = 12, bars_per_batch: int = 200,
) -> bool:
    """Scroll the chart's time axis backward until `target_epoch_s` is
    in the bar buffer. TV silently rejects Replay dates outside the
    loaded buffer — `select_start_date` looks like it succeeds but the
    cursor never seeds.

    Strategy: use TV's `timeScale.scrollChartByBar(-N)` to walk history
    backward. After each batch, check if any bar's time <= target.
    Returns True when target is reachable, False if max_batches hit.

    For RTH equity index futures, ~390 1-min bars per session × ~5 days
    = 2000 bars to reach last week, easily within max_batches × bars_per_batch."""
    from . import replay_api

    for batch in range(max_batches):
        # Check buffer extent first — early-exit when target is loaded.
        first_ts = await page.evaluate("""() => {
            try {
                const b = window.TradingViewApi._activeChartWidgetWV.value()
                    ._chartWidget.model().mainSeries().bars();
                if (!b) return null;
                const fi = b.firstIndex();
                if (fi === undefined) return null;
                const v = b.valueAt(fi);
                return v ? v[0] : null;
            } catch (e) { return null; }
        }""")
        if first_ts is not None and first_ts <= target_epoch_s:
            audit.log("replay.history_loaded", batches=batch,
                      first_ts=first_ts, target_ts=target_epoch_s)
            return True

        # Scroll back by N bars. `scrollChartByBar(N)` accepts negative
        # to scroll history left. TV loads more bars asynchronously
        # when the scroll reaches the buffer's left edge.
        try:
            await page.evaluate(f"""() => {{
                try {{
                    const cw = window.TradingViewApi._activeChartWidgetWV.value()._chartWidget;
                    if (typeof cw.scrollChartByBar === 'function') {{
                        cw.scrollChartByBar(-{bars_per_batch});
                    }} else {{
                        const ts = cw.model().timeScale();
                        if (typeof ts.scrollToBar === 'function') {{
                            ts.scrollToBar(ts.logicalRange()._left - {bars_per_batch});
                        }}
                    }}
                    return true;
                }} catch (e) {{ return false; }}
            }}""")
        except Exception as e:
            audit.log("replay.history_scroll.fail", batch=batch, err=str(e))
            break
        # Wait for TV to fetch + render the newly-needed bars.
        await page.wait_for_timeout(800)

    audit.log("replay.history_load.exhausted",
              max_batches=max_batches, target_ts=target_epoch_s)
    return False


async def _force_exit_replay(page: Page, *, settle_ms: int = 1500) -> bool:
    """Best-effort exit — tries Escape (drops armed tool / dialog),
    Exit button, toolbar toggle, then waits briefly. Doesn't raise on
    failure — returns True if `is_active` is False after the attempt,
    False otherwise (caller can escalate to page reload)."""
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
    except Exception:
        pass

    # Try the dedicated exit button first.
    try:
        exit_btn = await pick_visible(page, _EXIT)
        if exit_btn is not None:
            await exit_btn.click()
            await page.wait_for_timeout(settle_ms)
            if not await is_active(page):
                audit.log("replay.force_exit.via_exit_btn")
                return True
    except Exception:
        pass

    # Toolbar toggle.
    try:
        toggle = await pick_visible(page, _TOGGLE)
        if toggle is not None:
            await toggle.click()
            await page.wait_for_timeout(settle_ms)
            if not await is_active(page):
                audit.log("replay.force_exit.via_toggle")
                return True
    except Exception:
        pass

    audit.log("replay.force_exit.failed", still_active=True)
    return False


async def _reload_to_clear_replay(page: Page) -> bool:
    """Last-resort recovery — reload the chart URL. Kills any stuck
    Replay state in TV's internal state machine. Preserves layout
    because the URL carries the layout id. Returns True when the
    canvas is visible post-reload."""
    audit.log("replay.recover.reload", url=page.url[:120])
    try:
        await page.goto(page.url, wait_until="domcontentloaded")
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        # Hydration buffer — indicators/legend mount after canvas paints.
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        audit.log("replay.recover.reload.fail", err=str(e))
        return False


def _within_tolerance(
    landed: datetime, target: datetime, tolerance_min: int,
) -> bool:
    """Compare two datetimes within `tolerance_min`. Handles
    naive/aware mismatch by treating naive as ET (matches the
    project-wide convention for chart session time)."""
    if target.tzinfo is None:
        from zoneinfo import ZoneInfo
        target = target.replace(tzinfo=ZoneInfo("America/New_York"))
    if landed.tzinfo is None:
        from zoneinfo import ZoneInfo
        landed = landed.replace(tzinfo=ZoneInfo("America/New_York"))
    delta_s = abs((landed - target).total_seconds())
    return delta_s <= tolerance_min * 60


async def navigate_to(
    page: Page, when: datetime, *,
    tolerance_min: int = 240, max_attempts: int = 4,
) -> datetime:
    """Self-healing Replay navigate — escalates through recovery actions
    until the cursor is confirmed within `tolerance_min` of `when`.

    Recovery escalation ladder (each step is tried in order, stopping
    at the first that confirms the cursor):

      Tier 1: `select_start_date` from current state. Cheap; works when
              Replay is healthy.
      Tier 2: Force-exit + re-enter (Start new), then `select_start_date`.
              Resets TV's Replay state machine without losing the chart.
      Tier 3: Page reload (preserves layout via URL), enter Replay fresh,
              then `select_start_date`. Last-resort recovery for cases
              where TV refuses to drop the strip via toolbar.
      Tier 4: Same as Tier 3 but with a longer hydration wait — handles
              slow networks / first-load chart layouts.

    `tolerance_min` defaults to 240 (4 hours) because TV's date picker
    drifts ~1-2h on the DOM path; callers wanting tighter precision
    should follow up with `step_forward`/`step_backward`.

    Returns the actual landed UTC datetime. Raises RuntimeError only
    after every tier exhausts — at which point manual TV intervention
    is the next step."""
    last_err: Exception | None = None

    # Normalize `when` to tz-aware for all downstream comparisons —
    # naive callers (e.g. daily_profile passes `date.replace(hour=16)`)
    # follow the project-wide convention of chart-session time = ET.
    if when.tzinfo is None:
        from zoneinfo import ZoneInfo
        when = when.replace(tzinfo=ZoneInfo("America/New_York"))
    target_epoch_s = int(when.timestamp())

    # Shell-mode pre-check: if Replay is "active" but the strip says
    # "Select date" (no cursor seeded) AND `currentDate()` is null,
    # TV is in a jammed half-state. Tier 1 (calling select_start_date
    # from current state) won't recover; jump straight to Tier 2.
    skip_tier1 = False
    if await is_active(page):
        from . import replay_api
        api_cursor = await replay_api.current_replay_date(page)
        strip_text = await _read_strip_date(page)
        shell_mode = (api_cursor is None
                      and (not strip_text
                           or strip_text.lower().strip() == "select date"))
        if shell_mode:
            audit.log("replay.navigate_to.shell_mode_detected")
            skip_tier1 = True

    for attempt in range(1, max_attempts + 1):
        if attempt == 1 and skip_tier1:
            continue
        try:
            if attempt == 1:
                # Tier 1: try from current state.
                if not await is_active(page):
                    await enter_replay(page)
                # Replay can't seed dates outside the bar buffer; load
                # history before attempting select. Cheap when target
                # is already in buffer (early-exit on first check).
                await _ensure_history_loaded(page, target_epoch_s)
                await select_start_date(page, when)
            elif attempt == 2:
                # Tier 2: force-exit + re-enter.
                await _force_exit_replay(page)
                await page.wait_for_timeout(800)
                await enter_replay(page)
                await _ensure_history_loaded(page, target_epoch_s)
                await select_start_date(page, when)
            elif attempt == 3:
                # Tier 3: page reload, fresh Replay.
                if not await _reload_to_clear_replay(page):
                    raise RuntimeError("page reload failed")
                await enter_replay(page)
                await _ensure_history_loaded(page, target_epoch_s)
                await select_start_date(page, when)
            else:
                # Tier 4+: reload with extended hydration.
                await _reload_to_clear_replay(page)
                await page.wait_for_timeout(3000)
                await enter_replay(page)
                await page.wait_for_timeout(1500)
                await _ensure_history_loaded(
                    page, target_epoch_s, max_batches=20,
                )
                await select_start_date(page, when)
        except Exception as e:
            last_err = e
            audit.log("replay.navigate_to.tier_fail",
                      tier=attempt, err=str(e))
            continue

        # Settle, then confirm via API → BarDate fallback.
        await page.wait_for_timeout(1200)
        landed = await confirm_cursor(page)
        if landed is None:
            audit.log("replay.navigate_to.no_confirmation", tier=attempt)
            continue

        if _within_tolerance(landed, when, tolerance_min):
            drift_min = (landed - when).total_seconds() / 60
            audit.log("replay.navigate_to.confirmed",
                      tier=attempt,
                      target=when.isoformat(),
                      landed=landed.isoformat(),
                      drift_min=round(drift_min, 1))
            return landed

        audit.log("replay.navigate_to.out_of_tolerance",
                  tier=attempt,
                  target=when.isoformat(),
                  landed=landed.isoformat(),
                  drift_min=round((landed - when).total_seconds() / 60, 1))

    # All tiers exhausted — collect diagnostic state so caller knows
    # what to investigate. The most common cause when even Tier 4
    # fails is TV's Replay state being corrupted at the layout level
    # (saved-layout chart URLs restore broken Replay state on reload),
    # which requires opening a fresh chart tab to recover.
    diag: dict[str, Any] = {}
    try:
        from . import replay_api
        diag["is_active"] = await is_active(page)
        diag["is_replay_started"] = await replay_api.is_replay_started(page)
        diag["current_date_api"] = await replay_api.current_replay_date(page)
        diag["strip_text"] = await _read_strip_date(page)
        diag["url"] = page.url
    except Exception:
        pass

    audit.log("replay.navigate_to.exhausted",
              target=when.isoformat(), tiers=max_attempts, **{
                  k: (v.isoformat() if hasattr(v, "isoformat") else v)
                  for k, v in diag.items()
              })

    hint = ""
    if diag.get("strip_text", "").lower().strip() == "select date":
        hint = (" Replay strip shows 'Select date' — TV refused our "
                "date pick. Likely cause: chart's saved-layout URL "
                "is restoring a corrupted Replay state on every reload. "
                "Recover by opening a fresh chart tab "
                "(`https://www.tradingview.com/chart/` without the layout id), "
                "or close + reopen the chart tab manually.")

    raise RuntimeError(
        f"navigate_to exhausted {max_attempts} tiers without "
        f"confirming cursor within {tolerance_min} min of "
        f"{when.isoformat()}. Diagnostic: {diag}. "
        f"Last error: {last_err}.{hint}"
    )


async def recover(page: Page) -> bool:
    """Reset Replay to a clean inactive state. Returns True when
    `is_active` is False after the attempt. Useful as a workflow
    pre-flight when prior automation may have left Replay jammed."""
    if not await is_active(page):
        return True
    if await _force_exit_replay(page):
        return True
    return await _reload_to_clear_replay(page) and not await is_active(page)


# ---------------------------------------------------------------------------
# Date picker
# ---------------------------------------------------------------------------


async def open_date_picker(page: Page) -> None:
    """Click the `Select date` button to open the date picker modal.
    Assumes Replay is already active. Uses `wait_visible` because the
    strip container can appear before its inner controls hydrate (TV
    renders a placeholder, then populates)."""
    if not await is_active(page):
        raise SelectorDriftError("not_active", "replay", [_STRIP])
    btn = await wait_visible(page, _SELECT_DATE, timeout_ms=3000)
    if btn is None:
        raise SelectorDriftError("select_date", "replay", [_SELECT_DATE])
    await btn.click()
    audit.log("replay.open_date_picker")


_DATE_DIALOG = 'div[role="dialog"]'
_DATE_INPUT = 'div[role="dialog"] input[placeholder="YYYY-MM-DD"]'
# Time input has no placeholder; it's the second input in the dialog.
_TIME_INPUT = 'div[role="dialog"] input'
_SELECT_BUTTON = 'div[role="dialog"] >> text="Select"'


async def select_start_date(page: Page, when: datetime) -> None:
    """Set the replay starting point to `when`. Prefers TV's internal
    JS API (`replayApi.selectDate(epoch_ms)`) — no dialog, no typing,
    immune to the date-picker mount race. Falls back to the DOM dialog
    when the API isn't reachable, so this is safe to leave on always.

    Date picker modal (DOM fallback path), resolved by
    `probes/probe_replay_datepicker.py`:
      * Dialog:   `div[role="dialog"]` with class `wrapper-b8SxMnzX`
      * Date:     `input[placeholder="YYYY-MM-DD"]`
      * Time:     second `input` (no placeholder; e.g. value="00:00")
      * Submit:   button with text `Select`
      * Cancel:   button with text `Cancel`
    """
    from . import replay_api
    if await replay_api.api_available(page):
        try:
            await replay_api.select_replay_date(page, when)
            audit.log("replay.select_start_date",
                      when=when.strftime("%Y-%m-%d %H:%M"), via="api")
            return
        except Exception as e:
            audit.log("replay.select_start_date.api_fallback", err=str(e))

    await open_date_picker(page)
    # Wait for the dialog to mount before targeting inputs.
    dialog = await wait_visible(page, _DATE_DIALOG, timeout_ms=3000)
    if dialog is None:
        raise SelectorDriftError("date_dialog", "replay", [_DATE_DIALOG])

    # Dialog inputs are CHART-LOCAL time (ET for CME futures). Convert
    # tz-aware datetimes; treat naive as already chart-local.
    if when.tzinfo is not None:
        from zoneinfo import ZoneInfo
        local = when.astimezone(ZoneInfo("America/New_York"))
    else:
        local = when
    date_str = local.strftime("%Y-%m-%d")
    time_str = local.strftime("%H:%M")

    # Date input.
    date_inp = await pick_visible(page, _DATE_INPUT)
    if date_inp is None:
        raise SelectorDriftError("date_input", "replay", [_DATE_INPUT])
    await date_inp.click()
    await page.keyboard.press("Meta+A")
    await page.keyboard.type(date_str, delay=10)

    # Time input: second input in the dialog. Use nth(1) on the generic
    # input selector — first is date, second is time.
    time_inp = page.locator(_TIME_INPUT).nth(1)
    await time_inp.click()
    await page.keyboard.press("Meta+A")
    await page.keyboard.type(time_str, delay=10)

    # Submit.
    submit = await pick_visible(page, _SELECT_BUTTON)
    if submit is None:
        raise SelectorDriftError("date_submit", "replay", [_SELECT_BUTTON])
    await submit.click()

    # Wait for the dialog to close — confirms TV accepted the date.
    for _ in range(20):
        if not await any_visible(page, _DATE_DIALOG):
            break
        await page.wait_for_timeout(150)
    else:
        raise SelectorDriftError("date_dialog_lingered", "replay", [_DATE_DIALOG])

    # TV needs a beat to repaint the chart at the new cursor. When
    # Replay was activated via the Start new workflow (see enter_replay),
    # TV auto-scrolls the view to the picked date — no extra nudging
    # needed.
    await page.wait_for_timeout(800)
    audit.log("replay.select_start_date",
              when=f"{date_str} {time_str}", via="dom")


# ---------------------------------------------------------------------------
# Stepping
# ---------------------------------------------------------------------------


async def step_forward(page: Page, bars: int = 1) -> None:
    """Advance the replay cursor by `bars` bars via Shift+ArrowRight. `bars` must be ≥ 0.

    TV's current replay build removed the `title="Play"` / `title="Forward"`
    anchors and left the step-forward button without a stable DOM identifier
    (only an SVG path signature, which rotates between TV releases). The
    keyboard shortcut is the stable surface — verified 2026-04-20: 1 press =
    1 bar, scales linearly up to at least 120 presses.

    When `replayApi` is reachable, captures cursor before + polls after
    so silent stalls (chart focus lost mid-batch) become loud audit
    events instead of bad screenshots downstream."""
    if bars < 0:
        raise ValueError("bars must be non-negative; use step_backward")
    if bars == 0:
        return
    try:
        await page.bring_to_front()
    except Exception:
        pass

    from . import replay_api
    api_ok = await replay_api.api_available(page)
    before = await replay_api.current_replay_date(page) if api_ok else None

    for _ in range(bars):
        await page.keyboard.press("Shift+ArrowRight")
        await page.wait_for_timeout(40)

    confirmed_after = None
    if api_ok and before is not None:
        # Mirrors the MCP's pattern: 12×250ms (~3s) for the cursor to
        # advance. Independent of `bars` since one keystroke flushes
        # the rest — we just need confirmation that ANY motion happened.
        for _ in range(12):
            cur = await replay_api.current_replay_date(page)
            if cur is not None and cur > before:
                confirmed_after = cur
                break
            await page.wait_for_timeout(250)

    audit.log("replay.step_forward", bars=bars,
              before=before.isoformat() if before else None,
              after=confirmed_after.isoformat() if confirmed_after else None,
              confirmed=confirmed_after is not None if api_ok and before else None)


async def step_backward(page: Page, bars: int = 1) -> None:
    """Retreat the replay cursor by `bars` bars via Shift+←. TV has no
    dedicated back button in the strip; the shortcut is our only lever."""
    if bars < 0:
        raise ValueError("bars must be non-negative; use step_forward")
    if bars == 0:
        return
    try:
        await page.bring_to_front()
    except Exception:
        pass
    for _ in range(bars):
        await page.keyboard.press("Shift+ArrowLeft")
        await page.wait_for_timeout(150)
    audit.log("replay.step_backward", bars=bars)


# ---------------------------------------------------------------------------
# Speed / interval
# ---------------------------------------------------------------------------


async def set_speed(page: Page, speed: SpeedLabel) -> None:
    """Change playback speed. Opens the speed menu, clicks the option,
    dismisses."""
    btn = await pick_visible(page, _SPEED)
    if btn is None:
        raise SelectorDriftError("speed", "replay", [_SPEED])
    await btn.click()
    # TV's speed menu is a floating popover — options are visible <div>s
    # / buttons with the speed text as their label.
    option_sel = f'div[role="menuitem"]:has-text("{speed}"), ' \
                 f'[data-role="menuitem"]:has-text("{speed}"), ' \
                 f'span:has-text("{speed}"):visible'
    opt = await wait_visible(page, option_sel, timeout_ms=2000)
    if opt is None:
        # Best-effort: close the menu and raise so caller knows.
        await page.keyboard.press("Escape")
        raise SelectorDriftError(f"speed_option_{speed}", "replay",
                                 [option_sel])
    await opt.click()
    audit.log("replay.set_speed", speed=speed)


# ---------------------------------------------------------------------------
# Current cursor readback (best-effort)
# ---------------------------------------------------------------------------


# Formats TV has been observed to use in the "Select date" button once
# a date is picked. Extend as the probe reveals more.
_TS_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%b %d %Y, %H:%M",
    "%b %d, %Y %H:%M",
    "%d %b %Y %H:%M",
    "%m/%d/%Y %H:%M",
)


async def current_replay_ts(page: Page) -> datetime | str | None:
    """Return the replay cursor's timestamp as a datetime if parseable,
    the raw button text if unparseable but non-default, or None if no
    date has been picked yet.

    UNKNOWN #6 in REPLAY_BENCH_PLAN.md: it's not yet verified whether
    this text updates as `Shift+→` steps the cursor, or only reflects
    the originally picked date. The harness treats this as a best-effort
    source — it falls back to tracking cursor position client-side
    (T₀ + N × bar_seconds).
    """
    btn = await pick_visible(page, _SELECT_DATE)
    if btn is None:
        return None
    try:
        raw = (await btn.inner_text()).strip()
    except Exception:
        return None
    if not raw or raw.lower() == "select date":
        return None
    # TV sometimes packs multiple labels into the control (e.g.
    # "Select date\n10x\n1m" pre-pick). Take the first non-empty line
    # that contains a digit — that's the date, not the speed/TF.
    for line in (ln.strip() for ln in raw.splitlines()):
        if line and re.search(r"\d", line):
            for fmt in _TS_FORMATS:
                try:
                    return datetime.strptime(line, fmt)
                except ValueError:
                    continue
            return line  # unparseable but clearly a date
    return None
