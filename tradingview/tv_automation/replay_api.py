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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from playwright.async_api import Page

from .lib import audit


_CHART_API = "window.TradingViewApi._activeChartWidgetWV.value()"
_REPLAY_API = "window.TradingViewApi._replayApi"


# TV's autoplay accepts only this discrete set of delay values. Calling
# `_replayApi.changeAutoplayDelay(N)` with any other value **persists a
# corrupt delay into TV cloud account state** that survives page reload
# — flagged by tradesdontlie/tradingview-mcp's `replay.js:6`. Guard every
# `changeAutoplayDelay` call with `if delay not in VALID_AUTOPLAY_DELAYS:
# raise ValueError(...)` *before* the eval reaches CDP.
VALID_AUTOPLAY_DELAYS: tuple[int, ...] = (
    100, 143, 200, 300, 1000, 2000, 3000, 5000, 10000,
)


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


def bar_seconds_from_resolution(resolution: str) -> int:
    """Convert TV's internal resolution token ('1', '60', 'D', '1W') to
    bar duration in seconds. Falls back to 60s for unrecognized inputs.

    Used by `do_step()` to validate the magnitude of a Replay advance —
    `bars * bar_seconds` is the expected `(after - before).total_seconds()`."""
    s = str(resolution).strip()
    if s.isdigit():
        return int(s) * 60
    return {"D": 86400, "1D": 86400, "W": 604800, "1W": 604800,
            "M": 2592000, "1M": 2592000}.get(s, 60)


async def is_replay_available(page: Page) -> bool:
    """True when `_replayApi.isReplayAvailable()` reports the current
    symbol/TF supports Bar Replay. False on missing API.

    `isReplayAvailable()` returns a TV WatchedValue, not a primitive —
    `.value()` unwraps it. Without the unwrap, callers see a truthy
    object and incorrectly skip the gate (verified during PR #1
    end-to-end verification, 2026-04-26)."""
    try:
        return bool(await _eval(
            page, f"{_REPLAY_API}.isReplayAvailable().value()",
        ))
    except Exception:
        return False


async def is_replay_started(page: Page) -> bool:
    """True when Replay is engaged AND has a seeded cursor.

    `_replayApi.isReplayStarted()` returns a TV WatchedValue object,
    not a primitive — `.value()` unwraps it. Without the unwrap, the
    Python side sees a truthy object and reports True even when Replay
    is in the half-mounted shell state with no cursor."""
    try:
        return bool(await _eval(
            page, f"{_REPLAY_API}.isReplayStarted().value()",
        ))
    except Exception:
        return False


async def current_replay_date(page: Page) -> datetime | None:
    """Replay cursor as a UTC datetime, or None if no cursor is seeded
    or the API is missing.

    Two TV-API surface details that bit us hard:
    1. `currentDate()` returns a **WatchedValue object**, not a number;
       `.value()` unwraps it to the actual ts (or null).
    2. The unwrapped ts is in **epoch SECONDS**, not milliseconds —
       asymmetric with `selectDate(epoch_ms)` which takes milliseconds.
       (TV's API isn't internally consistent about units; we accept that.)"""
    try:
        ts_s = await _eval(page, f"{_REPLAY_API}.currentDate().value()")
        if ts_s is None:
            return None
        return datetime.fromtimestamp(ts_s, tz=timezone.utc)
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
    # Timeout guards against TV never settling the promise (observed
    # for current-day dates where the replay controller treats the
    # session as still "live").
    try:
        await asyncio.wait_for(
            _eval(page, f"{_REPLAY_API}.selectDate({target_ms})",
                  await_promise=True),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"selectDate({target_ms}) promise did not settle within 10s "
            f"— TV may not support replay for this date yet"
        )

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


async def do_step(
    page: Page, bars: int = 1, *,
    poll_ms: int = 250, max_polls: int = 12,
    expected_bar_seconds: int | None = None,
    drift_tolerance: float = 2.0,
) -> datetime | None:
    """Advance the Replay cursor by `bars` bars via `_replayApi.doStep()`.

    Replaces the `Shift+ArrowRight` keystroke primitive used by
    `replay.step_forward` — JS-API calls have no chart-focus dependency,
    so a chart that lost focus mid-batch (the documented keyboard
    failure mode in `project_replay_step_forward.md`) advances reliably.

    All `bars` calls dispatch in a single CDP roundtrip via a JS `for`
    loop; we then poll `currentDate()` for change vs. before.

    `expected_bar_seconds` (optional) enables drift detection: when set,
    the advance is rejected if `(landed - before).total_seconds()` is
    less than (1/drift_tolerance)× or more than drift_tolerance× the
    expected `bars × expected_bar_seconds`. Calibrated against the
    2026-04-26 verification where a freshly-seeded replay landed
    `do_step(1)` 4321 bars away from where it should have — the existing
    drift-blind do_step would have silently returned success.

    Returns the landed cursor datetime on confirmed in-tolerance advance,
    or None on any of:
      * `before` was unknown (replay half-mounted; stale `cur` would
        otherwise be accepted as success — blind spot #6 from PR #1 review)
      * `doStep` is missing or threw
      * confirmation timeout (poll exhaustion → `do_step.timeout` audit)
      * drift outside tolerance (TV jumped through a gap →
        `do_step.drift` audit)
    Each failure mode emits a distinct audit event; `step_forward`
    falls through to the keyboard primitive on any None.

    Backward stepping is not exposed by TV's public `_replayApi`; keep
    using `Shift+ArrowLeft` in `replay.step_backward`."""
    if bars < 0:
        raise ValueError("bars must be non-negative")
    if bars == 0:
        return await current_replay_date(page)

    before = await current_replay_date(page)
    if before is None:
        audit.log("replay_api.do_step.no_before", bars=bars)
        return None

    try:
        ok = await _eval(page, f"""(() => {{
            const rp = {_REPLAY_API};
            if (!rp || typeof rp.doStep !== 'function') return false;
            for (let i = 0; i < {bars}; i++) rp.doStep();
            return true;
        }})()""")
    except Exception as e:
        audit.log("replay_api.do_step.fail", bars=bars, err=str(e))
        return None
    if not ok:
        audit.log("replay_api.do_step.no_function", bars=bars)
        return None

    # `doStep()` is async internally — `currentDate()` reflects the
    # advance ~250-500ms later even though the call returns immediately.
    for _ in range(max_polls):
        cur = await current_replay_date(page)
        if cur is not None and cur > before:
            if expected_bar_seconds is not None:
                actual_s = (cur - before).total_seconds()
                expected_s = bars * expected_bar_seconds
                ratio = actual_s / expected_s if expected_s else 0
                if not (1 / drift_tolerance) <= ratio <= drift_tolerance:
                    audit.log("replay_api.do_step.drift",
                              bars=bars, expected_s=expected_s,
                              actual_s=int(actual_s), ratio=round(ratio, 2),
                              before=before.isoformat(),
                              landed=cur.isoformat())
                    return None
            return cur
        await asyncio.sleep(poll_ms / 1000)

    audit.log("replay_api.do_step.timeout",
              bars=bars, poll_ms=poll_ms, max_polls=max_polls,
              before=before.isoformat())
    return None


async def stop_replay(page: Page) -> bool:
    """Disengage Bar Replay via `_replayApi.stopReplay()`.

    JS-API path: no DOM clicks, no strip-disappearance polling, no
    selector dependency. Returns True when replay was active and is now
    stopped, False if replay wasn't active OR the API isn't reachable
    (caller should escalate to `replay.exit_replay` for the DOM
    fallback). Idempotent — safe to call when not in replay."""
    if not await api_available(page):
        return False
    if not await is_replay_started(page):
        return True
    try:
        await _eval(page, f"{_REPLAY_API}.stopReplay()")
    except Exception as e:
        audit.log("replay_api.stop_replay.fail", err=str(e))
        return False
    # Confirm — stopReplay flips isReplayStarted within ~250ms.
    for _ in range(8):
        if not await is_replay_started(page):
            audit.log("replay_api.stop_replay.confirmed")
            return True
        await asyncio.sleep(0.25)
    audit.log("replay_api.stop_replay.no_confirmation")
    return False


@asynccontextmanager
async def replay_session(page: Page) -> AsyncIterator[None]:
    """Engage-and-cleanup context manager for any caller that needs
    Bar Replay active for the duration of a block.

    Records whether replay was already engaged on entry. On exit:
      * If we engaged it: stop it cleanly (preferred: JS-API; fallback:
        DOM via `replay.exit_replay`).
      * If it was already on: leave it as we found it — caller's outer
        scope is responsible.
    Cleanup runs on both normal exit AND exceptions. Use this wrapping
    a workflow block whenever you can; for legacy callers that engage
    replay deeper in the call stack, use `try / finally:
    await replay.exit_replay(page)` at the workflow boundary instead."""
    was_engaged_on_entry = await is_replay_started(page)
    try:
        yield
    finally:
        if was_engaged_on_entry:
            audit.log("replay_api.replay_session.preserve",
                      reason="was_engaged_on_entry")
            return
        # We took on the engagement OR replay got started inside the
        # block — clean up either way.
        if not await is_replay_started(page):
            return
        if await stop_replay(page):
            return
        # API path failed → DOM fallback. Lazy import to avoid
        # circularity (replay imports replay_api).
        try:
            from . import replay as _replay
            await _replay.exit_replay(page)
        except Exception as e:
            audit.log("replay_api.replay_session.cleanup_fail", err=str(e))


async def toggle_autoplay(page: Page) -> bool | None:
    """Toggle replay autoplay via `_replayApi.toggleAutoplay()`.

    Returns the resulting `isAutoplayStarted()` state, or None if the
    API isn't reachable. Safe to call repeatedly — TV serializes the
    toggle internally."""
    if not await api_available(page):
        return None
    try:
        await _eval(page, f"{_REPLAY_API}.toggleAutoplay()")
    except Exception as e:
        audit.log("replay_api.toggle_autoplay.fail", err=str(e))
        return None
    try:
        return bool(await _eval(
            page, f"{_REPLAY_API}.isAutoplayStarted().value()",
        ))
    except Exception:
        return None


async def set_autoplay_delay(page: Page, delay_ms: int) -> bool:
    """Set autoplay delay via `_replayApi.changeAutoplayDelay(ms)`.

    **Hard-validates** `delay_ms` against `VALID_AUTOPLAY_DELAYS` before
    the call reaches CDP. Off-whitelist values persist a corrupt delay
    into TV cloud account state that survives reload — flagged by
    tradesdontlie/tradingview-mcp `replay.js:6`. Raises ValueError on
    any value outside the whitelist; the static check is the whole
    point of routing through this wrapper instead of inlining the eval.

    Returns True on success, False if the API isn't reachable."""
    if delay_ms not in VALID_AUTOPLAY_DELAYS:
        raise ValueError(
            f"delay_ms={delay_ms} not in VALID_AUTOPLAY_DELAYS "
            f"{VALID_AUTOPLAY_DELAYS} — would corrupt TV cloud state."
        )
    if not await api_available(page):
        return False
    try:
        await _eval(page, f"{_REPLAY_API}.changeAutoplayDelay({delay_ms})")
        return True
    except Exception as e:
        audit.log("replay_api.set_autoplay_delay.fail",
                  delay_ms=delay_ms, err=str(e))
        return False


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


async def wait_for_bars_to_load(
    page: Page, *,
    earliest_epoch_s: int | None = None,
    latest_epoch_s: int | None = None,
    timeout_ms: int = 5000,
    poll_ms: int = 200,
) -> bool:
    """Poll the bar buffer until it covers the requested time range.

    Returns True when both `earliest_epoch_s` (if given) and
    `latest_epoch_s` (if given) fall inside [firstBar.timestamp,
    lastBar.timestamp]. Useful before `find_bar_index_for_time` /
    `zoom_to_bar_range` after navigating across dates in the same chart
    session — TV may have evicted older history, leaving stale indices
    that map to whichever bars happen to be loaded (2026-05-13 backfill
    diagnostic: `find_bar_index_for_time(09:30 ET 05-07)` returned the
    bar at 09:45, off by hours from cursor at 14:00, because the 05-07
    buffer was evicted after intermediate navigation through 05-08 and
    05-13).

    Returns False on timeout. Caller should treat a False return the
    same as a stale-buffer hit — either retry or accept degraded
    framing. Does not itself force-load bars; callers needing that
    should drive a `replay.navigate_to` or chart-scroll first."""
    import asyncio
    deadline_s = timeout_ms / 1000.0
    poll_s = poll_ms / 1000.0
    elapsed = 0.0
    while True:
        try:
            info = await _eval(page, """(() => {
                try {
                    const b = window.TradingViewApi
                        ._activeChartWidgetWV.value()
                        ._chartWidget.model().mainSeries().bars();
                    if (!b) return null;
                    const fi = b.firstIndex();
                    const li = b.lastIndex();
                    if (typeof fi !== 'number' || typeof li !== 'number')
                        return null;
                    const fv = b.valueAt(fi);
                    const lv = b.valueAt(li);
                    if (!fv || !lv) return null;
                    return {first_ts: fv[0], last_ts: lv[0]};
                } catch (e) { return null; }
            })()""")
        except Exception:
            info = None
        if info is not None:
            first_ts = info.get("first_ts")
            last_ts = info.get("last_ts")
            ok_first = (earliest_epoch_s is None
                        or (first_ts is not None and first_ts <= earliest_epoch_s))
            ok_last = (latest_epoch_s is None
                       or (last_ts is not None and last_ts >= latest_epoch_s))
            if ok_first and ok_last:
                audit.log("replay_api.wait_for_bars.ok",
                          first_ts=first_ts, last_ts=last_ts,
                          earliest=earliest_epoch_s, latest=latest_epoch_s,
                          waited_s=round(elapsed, 2))
                return True
        if elapsed >= deadline_s:
            audit.log("replay_api.wait_for_bars.timeout",
                      first_ts=(info or {}).get("first_ts"),
                      last_ts=(info or {}).get("last_ts"),
                      earliest=earliest_epoch_s, latest=latest_epoch_s,
                      waited_s=round(elapsed, 2))
            return False
        await asyncio.sleep(poll_s)
        elapsed += poll_s


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
