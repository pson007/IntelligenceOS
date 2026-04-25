"""Read OHLCV bars directly from TradingView's chart memory.

Replaces vision-LLM reads of close/HOD/LOD with exact numerical values
from `mainSeries().bars()` — the same array the chart canvas paints
from. Eliminates the recurring "LOD band too high" reconcile failures
that came from the vision LLM mis-locating the demand sweep on a
busy chart.

Usage:
    ohlc = await read_session_ohlc(
        page, start_et=datetime(2026, 4, 24, 9, 30),
        end_et=datetime(2026, 4, 24, 16, 0),
    )
    # → {open, close, hod, lod, span_pts, bars_count, ...}

Caveats:
- The bars array reflects the chart's CURRENT timeframe, not 1m.
  Pass a TF that gives you the resolution you want (1m for RTH HOD/LOD).
- During Bar Replay, `bars()` only contains bars up to the replay
  cursor. Reading after a `select_replay_date` to ~16:00 ET on the
  target day gives the full session; reading mid-replay gives a
  partial session, which is what you want for live-forecast grading.
- Times come back as epoch SECONDS (TV stores them so), not ms.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from playwright.async_api import Page

from .lib import audit


_BARS_PATH = (
    "window.TradingViewApi._activeChartWidgetWV.value()."
    "_chartWidget.model().mainSeries().bars()"
)
_ET = ZoneInfo("America/New_York")


async def bars_available(page: Page) -> bool:
    """True when the bars accessor resolves on the current chart."""
    try:
        return bool(await page.evaluate(f"""() => {{
            try {{
                const b = {_BARS_PATH};
                return b && typeof b.lastIndex === 'function'
                       && typeof b.valueAt === 'function';
            }} catch (e) {{ return false; }}
        }}"""))
    except Exception:
        return False


async def read_all_bars(page: Page) -> list[list[float]] | None:
    """Return every bar currently in chart memory. Each bar is
    `[epoch_seconds, open, high, low, close, volume]`. Returns None
    if the bars accessor isn't reachable.

    Walks `firstIndex()..lastIndex()` rather than relying on a length
    property — TV's bar buffer is sparse-indexed and a length read
    can over-report by 1."""
    try:
        return await page.evaluate(f"""() => {{
            try {{
                const b = {_BARS_PATH};
                if (!b) return null;
                const lo = b.firstIndex();
                const hi = b.lastIndex();
                const out = [];
                for (let i = lo; i <= hi; i++) {{
                    const v = b.valueAt(i);
                    if (v) out.push(v);
                }}
                return out;
            }} catch (e) {{ return null; }}
        }}""")
    except Exception:
        return None


def _et_naive_to_epoch(dt: datetime) -> int:
    """Naive ET → epoch seconds. Handles DST since ZoneInfo does."""
    return int(dt.replace(tzinfo=_ET).astimezone(timezone.utc).timestamp())


async def read_session_ohlc(
    page: Page, *, start_et: datetime, end_et: datetime,
) -> dict[str, Any] | None:
    """Compute open/close/HOD/LOD over [start_et, end_et] (naive ET).

    `start_et` is matched to the first bar with `time >= start_et`;
    `end_et` to the last bar with `time <= end_et`. Returns None when
    the bars API is unreachable; an empty dict with `bars_count=0`
    when the API works but no bars fall in range (e.g., Replay cursor
    hasn't reached `start_et` yet)."""
    bars = await read_all_bars(page)
    if bars is None:
        return None

    start_s = _et_naive_to_epoch(start_et)
    end_s = _et_naive_to_epoch(end_et)
    in_range = [b for b in bars if start_s <= int(b[0]) <= end_s]

    if not in_range:
        return {
            "bars_count": 0,
            "start_et": start_et.isoformat(timespec="minutes"),
            "end_et": end_et.isoformat(timespec="minutes"),
            "open": None, "close": None, "hod": None, "lod": None,
            "span_pts": None,
        }

    open_px = in_range[0][1]
    close_px = in_range[-1][4]
    hod = max(b[2] for b in in_range)
    lod = min(b[3] for b in in_range)
    span = round(hod - lod, 2)
    net = round(close_px - open_px, 2)
    pct = round((net / open_px) * 100, 4) if open_px else None

    summary = {
        "bars_count": len(in_range),
        "start_et": start_et.isoformat(timespec="minutes"),
        "end_et": end_et.isoformat(timespec="minutes"),
        "open": round(open_px, 2),
        "close": round(close_px, 2),
        "hod": round(hod, 2),
        "lod": round(lod, 2),
        "span_pts": span,
        "net_pts": net,
        "net_pct": pct,
        "first_bar_ts": int(in_range[0][0]),
        "last_bar_ts": int(in_range[-1][0]),
    }
    audit.log("bar_reader.session_ohlc", **summary)
    return summary
