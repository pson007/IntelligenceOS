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
from typing import Literal

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

    date_str = when.strftime("%Y-%m-%d")
    time_str = when.strftime("%H:%M")

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
