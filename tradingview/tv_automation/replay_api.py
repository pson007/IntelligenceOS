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
import json
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Page

from .lib import audit


_CHART_API = "window.TradingViewApi._activeChartWidgetWV.value()"
_REPLAY_API = "window.TradingViewApi._replayApi"


def js_str(s: str) -> str:
    """JSON-encode a string for safe embedding in eval'd JS expressions.
    Mirrors tradesdontlie/tradingview-mcp's `safeString()` — defensive
    against accidental injection if a caller-supplied value ever flows
    in (e.g. an untrusted symbol like `MNQ1!"); chart.alert("xss")//`)."""
    return json.dumps(s)


async def _eval(page: Page, expr: str, *, await_promise: bool = False) -> Any:
    """Evaluate a JS expression in the page and return its value.

    `await_promise=True` wraps the expression in `await (...)` so a
    promise-returning API (e.g. `replayApi.selectDate`) settles before
    we move on. Without it, `evaluate` returns the unsettled Promise
    object and the caller polls into a known race window."""
    if await_promise:
        return await page.evaluate(
            f"async () => {{ const v = await ({expr}); return v; }}"
        )
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

    Naive datetimes are treated as **chart session time (America/New_York
    for CME index futures)** to match the existing convention that
    `daily_profile._navigate_to_session_close` and friends already use.
    Pass tz-aware datetimes for unambiguous semantics."""
    if when.tzinfo is None:
        from zoneinfo import ZoneInfo
        when = when.replace(tzinfo=ZoneInfo("America/New_York"))
    target_ms = int(when.timestamp() * 1000)

    # Await the promise selectDate may return — without this we race
    # the polling loop against TV's still-loading chart state and
    # occasionally see stale `currentDate()` until the next tick.
    await _eval(page, f"{_REPLAY_API}.selectDate({target_ms})",
                await_promise=True)

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


async def set_symbol_in_place(
    page: Page, symbol: str | None = None, interval: str | None = None,
    *, poll_ms: int = 200, max_polls: int = 25,
) -> dict[str, Any] | None:
    """Switch chart symbol/timeframe via TV's JS API — no page reload.

    Replaces a `page.goto(chart_url)` round-trip (~2.5s + Bar Replay
    state loss + indicator re-mount) with `chart.setSymbol/setResolution`
    (~50ms, in-place). Polls `chart.symbol()`/`chart.resolution()`
    until the change confirms; returns the post-state dict.

    Returns None when the API isn't reachable so callers can fall back
    to URL navigation cleanly."""
    if not symbol and not interval:
        return await chart_state(page)
    if not await api_available(page):
        return None

    parts = []
    if symbol:
        parts.append(f"c.setSymbol({js_str(symbol)}, {{}})")
    if interval:
        parts.append(f"c.setResolution({js_str(interval)}, {{}})")
    expr = f"""(() => {{
        const c = {_CHART_API};
        if (!c) return false;
        {';'.join(parts)};
        return true;
    }})()"""
    try:
        # Some TV builds return promises from setSymbol/setResolution
        # (the new bars stream over the network). Await the IIFE so we
        # don't poll into a half-applied state.
        await _eval(page, expr, await_promise=True)
    except Exception as e:
        audit.log("replay_api.set_symbol_in_place.fail", err=str(e))
        return None

    # Confirm — TV mutates synchronously but the new bars stream in
    # over the next tick, so poll until both target fields read back.
    for _ in range(max_polls):
        st = await chart_state(page)
        if st is None:
            await asyncio.sleep(poll_ms / 1000)
            continue
        sym_ok = (not symbol) or (
            st["symbol"] == symbol or st["symbol"].endswith(":" + symbol)
            or st["symbol"].split(":")[-1] == symbol
        )
        res_ok = (not interval) or (st["resolution"] == interval)
        if sym_ok and res_ok:
            # Hydration buffer — `chart.symbol()` flips before the new
            # bar buffer fills. Wait briefly so a screenshot taken
            # right after this call doesn't capture mid-transition.
            # Mirrors the 800ms used after `select_replay_date`.
            await asyncio.sleep(0.8)
            audit.log("replay_api.set_symbol_in_place",
                      symbol=symbol, interval=interval, landed=st)
            return st
        await asyncio.sleep(poll_ms / 1000)
    audit.log("replay_api.set_symbol_in_place.timeout",
              symbol=symbol, interval=interval)
    return None


async def chart_symbol_ext(page: Page) -> dict | None:
    """Rich symbol metadata from `chart.symbolExt()` — exchange, ticker,
    type, etc. Use instead of regex-parsing `page.title()` when you
    need anything beyond the bare symbol.

    Field shape varies across TV builds — current build (2026-04) exposes:
    `symbol`, `full_name`, `pro_name`, `exchange`, `type`, `description`,
    `typespecs`, `delay`. We derive a `ticker` field by stripping the
    exchange prefix from `full_name` since the build doesn't expose one
    directly."""
    try:
        return await _eval(page, f"""(() => {{
            const c = {_CHART_API};
            if (!c || typeof c.symbolExt !== 'function') return null;
            try {{
                const ext = c.symbolExt();
                if (!ext) return null;
                const full = ext.full_name || ext.fullName
                             || ext.pro_name || null;
                const ticker = full && full.indexOf(':') >= 0
                    ? full.split(':').slice(1).join(':')
                    : (ext.symbol || full);
                return {{
                    symbol: ext.symbol || null,
                    full_name: full,
                    pro_name: ext.pro_name || null,
                    ticker: ticker,
                    exchange: ext.exchange || ext.listed_exchange || null,
                    type: ext.type || null,
                    description: ext.description || null,
                    typespecs: ext.typespecs || null,
                    delay: ext.delay !== undefined ? ext.delay : null,
                }};
            }} catch (e) {{ return null; }}
        }})()""")
    except Exception:
        return None


async def read_indicator_values(page: Page) -> list[dict] | None:
    """Snapshot every indicator's current numerical output.

    Tries `dataWindowView().items()` first (when present) then falls
    back to walking `dataSources()` and reading each source's
    `lastValueData()` — same data backing the chart's legend numbers.

    Returns `[{title, values: [{name, value}, ...]}, ...]`; empty list
    if no studies have readable values; None when neither path works.

    **Bar Replay caveat**: when Replay is active, `lastValueData()`
    returns `{noData: true}` because TV defines "last" relative to the
    Replay cursor's "live" position which doesn't have a steady
    last-bar concept. So Replay-driven workflows (daily_profile,
    live_forecast stages) get an empty list here — the win materializes
    in non-Replay analyze paths (single-TF analyze, deep analyze on a
    live chart)."""
    try:
        return await _eval(page, f"""(() => {{
            try {{
                const c = {_CHART_API};
                if (!c) return null;

                // Path 1: dataWindowView (newer TV builds)
                if (typeof c.dataWindowView === 'function') {{
                    const dwv = c.dataWindowView();
                    if (dwv && typeof dwv.items === 'function') {{
                        const items = dwv.items();
                        if (Array.isArray(items) && items.length > 0) {{
                            return items.map(g => ({{
                                title: g.title || g.name || null,
                                values: (g.values || []).map(v => ({{
                                    name: v.name || v.id || null,
                                    value: (v.value && v.value.value !== undefined)
                                            ? v.value.value : v.value,
                                    format: v.format || null,
                                }})),
                            }}));
                        }}
                    }}
                }}

                // Path 2: walk dataSources() and read lastValueData
                const sources = c._chartWidget && c._chartWidget.model
                    ? c._chartWidget.model().model().dataSources()
                    : null;
                if (!sources) return null;
                const out = [];
                for (const s of sources) {{
                    if (!s || !s.metaInfo || !s.lastValueData) continue;
                    let mi; try {{ mi = s.metaInfo(); }} catch (e) {{ continue; }}
                    const title = mi.description || mi.shortDescription
                                  || mi.id || null;
                    let lvd; try {{ lvd = s.lastValueData(); }} catch (e) {{ continue; }}
                    if (!lvd || lvd.noData) continue;
                    const plots = lvd.plotValues || lvd.values || [];
                    const values = (Array.isArray(plots) ? plots : [])
                        .map(p => ({{
                            name: p.title || p.name || p.id || null,
                            value: (p.value && p.value.value !== undefined)
                                    ? p.value.value
                                    : (p.value !== undefined ? p.value : null),
                            format: p.format || null,
                        }}))
                        .filter(v => v.value !== null && v.value !== undefined);
                    if (values.length > 0) out.push({{title, values}});
                }}
                return out;
            }} catch (e) {{ return null; }}
        }})()""")
    except Exception:
        return None


async def zoom_to_bar_range(
    page: Page, from_idx: int, to_idx: int,
) -> bool:
    """Frame the chart to bars `[from_idx, to_idx]` via TV's TimeScale
    API — deterministic alternative to wheel-scrolling the time axis.

    Indices are clamped to `[firstIndex, lastIndex]` inside the JS so
    a caller padding past the buffer bounds (e.g. `open_idx - 60` when
    open_idx is already near firstIndex) doesn't silently zoom to
    garbage or throw inside TV's internals.

    Returns True on success."""
    try:
        return bool(await _eval(page, f"""(() => {{
            try {{
                const c = {_CHART_API};
                if (!c) return false;
                const cw = c._chartWidget;
                const ts = (cw && cw.model)
                    ? cw.model().timeScale()
                    : (typeof c.getTimeScale === 'function' ? c.getTimeScale() : null);
                if (!ts || typeof ts.zoomToBarsRange !== 'function') return false;
                let lo = {from_idx};
                let hi = {to_idx};
                try {{
                    const b = c._chartWidget.model().mainSeries().bars();
                    if (b) {{
                        const fi = b.firstIndex();
                        const li = b.lastIndex();
                        if (typeof fi === 'number') lo = Math.max(lo, fi);
                        if (typeof li === 'number') hi = Math.min(hi, li);
                    }}
                }} catch (e) {{}}
                if (hi <= lo) return false;
                ts.zoomToBarsRange(lo, hi);
                return true;
            }} catch (e) {{ return false; }}
        }})()"""))
    except Exception:
        return False


async def find_bar_index_for_time(
    page: Page, target_epoch_s: int,
) -> int | None:
    """Return the bar index whose timestamp is closest to (and not
    after) `target_epoch_s`. Useful for translating session_open /
    session_close datetimes into the bar indices `zoom_to_bar_range`
    expects."""
    try:
        return await _eval(page, f"""(() => {{
            try {{
                const b = {_CHART_API}._chartWidget.model().mainSeries().bars();
                if (!b) return null;
                const lo = b.firstIndex();
                const hi = b.lastIndex();
                let best = null;
                let bestDelta = Infinity;
                for (let i = lo; i <= hi; i++) {{
                    const v = b.valueAt(i);
                    if (!v) continue;
                    const delta = Math.abs(v[0] - {target_epoch_s});
                    if (delta < bestDelta) {{
                        bestDelta = delta;
                        best = i;
                    }}
                }}
                return best;
            }} catch (e) {{ return null; }}
        }})()""")
    except Exception:
        return None
