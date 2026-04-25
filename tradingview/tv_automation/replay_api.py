"""TradingView internal-API access — bypass DOM selectors for replay
state and chart introspection.

DOM-based primitives in `replay.py` break when TV's markup changes —
the most recent hit was 2026-04-24, when the Select-date dialog refused
to re-mount from an already-active Replay state. TV's own JS API,
exposed at `window.TradingViewApi`, sidesteps that entirely: direct
function calls return the same data the UI displays, and the API
surface stays consistent across recent builds.

Discovered paths (prior art: tradesdontlie/tradingview-mcp):
  - `window.TradingViewApi._activeChartWidgetWV.value()` — chart widget.
    `.symbol()`, `.resolution()`, `.chartType()`, `.getAllStudies()`.
  - `window.TradingViewApi._replayApi` — replay controller.
    `.isReplayStarted()`, `.currentDate()` (epoch ms),
    `.selectDate(epoch_ms)`, `.position()`, `.realizedPL()`.

Every function returns None / False on missing API rather than raising,
so callers can probe `api_available()` once and gate accordingly.
`select_replay_date` is the exception — it polls and raises on timeout
so that callers can fall back to DOM cleanly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Page

from .lib import audit


_CHART_API = "window.TradingViewApi._activeChartWidgetWV.value()"
_REPLAY_API = "window.TradingViewApi._replayApi"


async def _eval(page: Page, expr: str) -> Any:
    """Evaluate a JS expression in the page and return its value.
    Wraps in an IIFE so callers can pass multi-statement bodies."""
    return await page.evaluate(f"() => ({expr})")


async def api_available(page: Page) -> bool:
    """True when both chart and replay APIs resolve. Cheap one-shot
    pre-flight — call once per workflow and gate API paths on it."""
    try:
        return bool(await _eval(
            page,
            f"typeof {_CHART_API} !== 'undefined' && {_CHART_API} !== null "
            f"&& typeof {_REPLAY_API} !== 'undefined' && {_REPLAY_API} !== null",
        ))
    except Exception:
        return False


async def chart_state(page: Page) -> dict | None:
    """Read symbol, resolution, chartType, studies from the chart API.
    Resolution returns TV's internal token ("1", "60", "D"); same as
    URL params, so `_TIMEFRAME_MAP` callers don't need translation."""
    try:
        return await _eval(page, f"""(() => {{
            const c = {_CHART_API};
            if (!c) return null;
            let studies = [];
            try {{
                studies = c.getAllStudies().map(s => ({{
                    id: s.id, name: s.name || s.title || 'unknown'
                }}));
            }} catch (e) {{}}
            return {{
                symbol: c.symbol(),
                resolution: c.resolution(),
                chart_type: c.chartType(),
                studies,
            }};
        }})()""")
    except Exception:
        return None


async def is_replay_started(page: Page) -> bool:
    try:
        return bool(await _eval(page, f"{_REPLAY_API}.isReplayStarted()"))
    except Exception:
        return False


async def current_replay_date(page: Page) -> datetime | None:
    """Replay cursor as a UTC datetime, or None if Replay's not active
    or the API is missing. Source: `replayApi.currentDate()` (epoch ms)."""
    try:
        ts_ms = await _eval(page, f"{_REPLAY_API}.currentDate()")
        if ts_ms is None:
            return None
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    except Exception:
        return None


async def select_replay_date(
    page: Page, when: datetime, *,
    poll_ms: int = 250, max_polls: int = 30,
) -> datetime:
    """Move the replay cursor to `when` via the JS API — no dialog,
    no typing, no dropdown drift. Polls `currentDate()` until the
    change confirms; raises RuntimeError on timeout (~7.5s default).

    Naive datetimes are treated as UTC."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    target_ms = int(when.timestamp() * 1000)

    await _eval(page, f"{_REPLAY_API}.selectDate({target_ms})")

    for _ in range(max_polls):
        cur = await current_replay_date(page)
        if await is_replay_started(page) and cur is not None:
            audit.log("replay_api.select_date.confirmed",
                      requested=when.isoformat(),
                      landed=cur.isoformat(),
                      drift_min=int((cur - when).total_seconds() // 60))
            return cur
        await asyncio.sleep(poll_ms / 1000)

    raise RuntimeError(
        f"replayApi.selectDate timeout after {max_polls * poll_ms}ms — "
        f"target {when.isoformat()} did not confirm via currentDate()."
    )
