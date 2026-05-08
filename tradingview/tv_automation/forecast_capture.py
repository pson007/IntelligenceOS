"""Shared screenshot helpers used by all three forecast workflows
(`pre_session_forecast`, `live_forecast`, `daily_forecast`).

Two primitives:
  * `hide_widget_panel` — collapses the right-sidebar widget panel
    (Watchlist / Details / News) so the chart canvas takes the full
    viewport width before screenshot. Without this, ~25–30% of every
    forecast capture is eaten by the watchlist column — what made the
    pre-2026-05-08 captures inconsistent with each other.
  * `frame_partial_session` / `frame_full_session` — viewport-agnostic
    framing using TradingView's time-axis strip selector instead of
    hardcoded mouse coordinates. The legacy pixel-tuned helpers
    (1300, 852) silently broke when the watchlist sidebar shifted the
    canvas; the time-axis selector reflows automatically.
"""

from __future__ import annotations

from playwright.async_api import Page

from .lib import audit


async def hide_widget_panel(page: Page) -> bool:
    """Collapse the right-sidebar widget panel before a screenshot.

    Returns True if a click was issued (panel was open and got hidden),
    False if the panel was already collapsed (no-op). Best-effort —
    failure to close the panel is not fatal; we log and continue so a
    transient selector miss doesn't block the whole forecast run.

    Detection: TV marks the active rail icon with `aria-pressed="true"`
    when its panel is expanded. The widgetbar panel container stays in
    the DOM at width≈1 when collapsed, so probing element visibility
    gives a false positive — only the icon's pressed state is reliable."""
    active_name = await page.evaluate(
        r"""() => {
            const wrap = document.querySelector('[data-name="widgetbar-wrap"]');
            if (!wrap) return null;
            const pressed = wrap.querySelector('[data-name][aria-pressed="true"]');
            return pressed ? pressed.dataset.name : null;
        }"""
    )
    if not active_name:
        return False
    try:
        clicked = await page.evaluate(
            r"""(name) => {
                const btn = document.querySelector(`[data-name="${name}"][aria-pressed="true"]`);
                if (!btn) return false;
                btn.click();
                return true;
            }""",
            active_name,
        )
        if not clicked:
            return False
        await page.wait_for_timeout(250)  # let the canvas reflow
        audit.log("forecast_capture.widget_panel_hidden", was=active_name)
        return True
    except Exception as e:
        audit.log("forecast_capture.widget_panel_hide_fail", err=str(e))
        return False


async def _time_axis_geom(page: Page) -> tuple[float, float, float] | None:
    """Return (x_left, x_right, y_center) of the time-axis strip, or None
    if the strip isn't visible (chart not ready, page navigating, etc.)."""
    strip = page.locator("div.chart-markup-table.time-axis").first
    try:
        box = await strip.bounding_box()
    except Exception:
        return None
    if box is None or box["width"] <= 0:
        return None
    return box["x"] + 150, box["x"] + box["width"] - 150, box["y"] + box["height"] / 2


async def frame_partial_session(page: Page) -> None:
    """Frame for a partial-session view (F1/F2/F3 forecasts) — zoom IN
    anchored at the right edge so the cursor's day dominates and the
    previous day is pushed off the left.

    Replaces `daily_forecast._frame_with_cursor_right` and
    `live_forecast._frame_live_session`. Same semantics, viewport-
    agnostic via the time-axis selector."""
    await page.bring_to_front()
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(150)
    geom = await _time_axis_geom(page)
    if geom is None:
        await page.keyboard.press("End")
        return
    _, x_right, y = geom
    await page.mouse.move(x_right, y)
    await page.wait_for_timeout(150)
    for _ in range(5):
        await page.mouse.wheel(0, -120)  # zoom IN at right
        await page.wait_for_timeout(80)
    await page.keyboard.press("End")
    await page.wait_for_timeout(400)


async def frame_full_session(page: Page) -> None:
    """Frame for a full-session view (reconciliation, profile capture) —
    zoom OUT anchored at the left so the whole RTH session is visible
    end-to-end with a small previous-day sliver for context.

    Replaces `daily_forecast._frame_session_view`. Same semantics,
    viewport-agnostic via the time-axis selector."""
    await page.bring_to_front()
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(150)
    geom = await _time_axis_geom(page)
    if geom is None:
        await page.keyboard.press("End")
        return
    x_left, _, y = geom
    await page.mouse.move(x_left, y)
    await page.wait_for_timeout(150)
    for _ in range(2):
        await page.mouse.wheel(0, 120)  # zoom OUT at left
        await page.wait_for_timeout(100)
    await page.keyboard.press("End")
    await page.wait_for_timeout(400)
