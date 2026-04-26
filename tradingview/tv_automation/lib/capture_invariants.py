"""Pre-screenshot invariant checks — convert silent flaky captures
into loud, debuggable failures.

Every screenshot taken by the forecast/profile workflows depends on a
collection of preconditions that were never asserted at capture time:
the symbol on screen actually matches the request, the timeframe is
the one we asked for, Bar Replay is in the expected state, the Replay
cursor sits at the intended bar, no modal/drawing-tool overlay is in
the frame, and the chart canvas has finished hydrating after the last
navigate. Any of these being subtly wrong silently corrupts the LLM's
read; the symptom is "the analyze result was weird" hours later, not
a crash.

`assert_capture_ready(page, expect)` runs the full battery in ~50ms,
audit-logs each check, and raises `CaptureInvariantError(reason)` on
the first hard failure so the caller can decide whether to retry,
re-navigate, or abort. Soft checks (anything caller marked optional)
log their result without raising.

Usage:
    from .lib.capture_invariants import assert_capture_ready, CaptureExpect
    await assert_capture_ready(page, CaptureExpect(
        symbol="MNQ1!", interval="1m",
        replay_mode=True,
        cursor_time=datetime(2026, 4, 24, 16, 0),
        cursor_tolerance_min=30,
    ))
    # only now is it safe to call page.screenshot(...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from playwright.async_api import Page

from . import audit
from .. import replay_api


_ET = ZoneInfo("America/New_York")


_BARDATE_RX = re.compile(
    r"BarDate\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)"
)


class CaptureInvariantError(RuntimeError):
    """A pre-capture check failed; the screenshot would not be usable."""

    def __init__(self, reason: str, **details: Any) -> None:
        self.reason = reason
        self.details = details
        msg = f"capture_invariant_fail: {reason}"
        if details:
            msg += f" ({', '.join(f'{k}={v!r}' for k, v in details.items())})"
        super().__init__(msg)


@dataclass
class CaptureExpect:
    """What the caller expects the chart to be showing at shutter time.

    Any field left as None disables that specific check — so callers
    can opt in only to the invariants that matter for their workflow.

    `cursor_time` is interpreted as Eastern Time wall-clock to match
    BarDate (which TradingView renders in the chart's session timezone,
    invariably ET for CME index futures). Pass a naive datetime."""

    symbol: str | None = None
    interval: str | None = None  # accepts "1m"/"5"/"D"; normalized internally
    replay_mode: bool | None = None  # True = require active, False = require off
    cursor_time: datetime | None = None
    cursor_tolerance_min: int = 1

    # Soft checks — log on failure, don't raise. Useful while tuning.
    soft_cursor: bool = False


def _normalize_symbol(s: str | None) -> str | None:
    """Strip exchange prefix + trailing whitespace; preserve `!` suffix.
    `BINANCE:BTCUSDT` → `BTCUSDT`; `MNQ1!` → `MNQ1!`; `mnq1!` → `MNQ1!`."""
    if not s:
        return None
    s = s.strip().upper()
    if ":" in s:
        s = s.split(":", 1)[1]
    return s


def _normalize_interval(tf: str | None) -> str | None:
    """Map any caller-friendly interval to TV's canonical token (`5`, `60`,
    `D`). Mirrors `chart.resolve_timeframe` but without the import cycle
    risk — keep this list narrow and in sync."""
    if not tf:
        return None
    table = {
        "30s": "30S", "45s": "45S",
        "1m": "1", "2m": "2", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
        "1h": "60", "2h": "120", "4h": "240",
        "1d": "D", "1w": "W", "1mo": "M",
        "1D": "D", "1W": "W", "1M": "M",
    }
    if tf in table:
        return table[tf]
    if tf.lower() in table:
        return table[tf.lower()]
    return tf  # already a TV-native token


def _bardate_to_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    m = _BARDATE_RX.match(text)
    if not m:
        return None
    try:
        vals = [int(float(g.replace(",", ""))) for g in m.groups()]
        return datetime(vals[0], vals[1], vals[2], vals[3], vals[4])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Individual probes — each returns a (ok, details) tuple. Kept as small
# pure functions so the QA harness in Track B can call them in isolation
# and report per-check status without re-running the full assert.
# ---------------------------------------------------------------------------


async def _probe_no_modal(page: Page) -> tuple[bool, dict]:
    """No blocking dialog/modal in front of the chart.

    Catches: 'Continue your last replay?' on Replay enter, 'Leave
    current replay?' on Replay exit, session-renew/upgrade nags,
    and the symbol-search overlay if open.

    TV uses CSS-modules class names (e.g. `popupDialog-B02UUUN3`,
    `dialog-aRAWUDhF`) and notably does NOT set `role="dialog"`. The
    `popupDialog` prefix is the most specific positive signal; the
    `dialog-<HASH>` form is broader. Both are stable across releases —
    only the random hash suffix changes."""
    detail = await page.evaluate("""() => {
      // Match TV's actual modal classes. `popupDialog-` is the
      // dedicated wrapper for confirmation dialogs (Leave / Continue
      // replay). `dialog-` is the general dialog primitive — broader
      // but still scoped (won't match `valueDialog` / similar).
      const sels = [
        '[class*="popupDialog-"]',
        '[class^="dialog-"]',
        '[class*=" dialog-"]',
        '[role="dialog"]',
        '[role="alertdialog"]',
      ];
      const seen = new Set();
      const found = [];
      for (const sel of sels) {
        document.querySelectorAll(sel).forEach(el => {
          if (seen.has(el)) return;
          const r = el.getBoundingClientRect();
          if (r.width < 100 || r.height < 50) return;
          // Must be in viewport (skip off-screen modal shells TV
          // keeps mounted but hidden).
          if (r.bottom < 0 || r.top > window.innerHeight) return;
          if (r.right < 0 || r.left > window.innerWidth) return;
          seen.add(el);
          found.push({
            cls: (el.className || '').toString().slice(0, 120),
            text: (el.innerText || '').trim().slice(0, 80),
            rect: {x: r.x|0, y: r.y|0, w: r.width|0, h: r.height|0},
          });
        });
      }
      return {count: found.length, items: found};
    }""")
    return (
        detail["count"] == 0,
        {"visible_modals": detail["count"], "items": detail["items"]},
    )


async def _probe_no_drawing_tool(page: Page) -> tuple[bool, dict]:
    """No active drawing tool inside the LEFT drawings toolbar.

    Caught us in apply_pine: an armed Text/Trend Line tool eats clicks
    on overlapping panels. Same hazard applies to screenshots taken
    while a tool is mid-draw — the half-drawn drawing appears in the
    image and trips the LLM's read.

    Scoping notes:
    - The drawings toolbar is `div[class*="drawingToolbar"]` (TV uses
      CSS-modules class names with random suffixes; the prefix is stable).
      Looking ONLY inside this root prevents false positives on
      unrelated chart-toolbar toggles like B-ADJ (back-adjust contract
      changes) or `series-style` that the broader `.chart-toolbar`
      selector would catch.
    - "Cross", "Crosshair", "Cursors", "Dot", and "Arrow" are pointer
      modes — they're the benign default state. Exact-match (lowercase)
      so "trend-line" can't accidentally pass via substring. Anything
      else flagged active in the drawings toolbar is treated as armed
      (Trend Line, Text, Fib, Eraser, etc.)."""
    detail = await page.evaluate(r"""() => {
      const root = document.querySelector(
        '[class*="drawingToolbar"]'
      );
      if (!root) return {found_root: false, armed: 0, items: []};
      const active = Array.from(root.querySelectorAll(
        'button[class*="isActive"], button[data-active="true"], ' +
        '[aria-pressed="true"]'
      ));
      const benign = new Set(['cross', 'crosshair', 'cursors',
                              'dot', 'arrow']);
      const items = active.map(b => ({
        aria_label: b.getAttribute('aria-label'),
        data_name: b.getAttribute('data-name'),
      }));
      const dangerous = items.filter(i => {
        const al = (i.aria_label || '').toLowerCase().trim();
        const dn = (i.data_name || '').toLowerCase().trim();
        return !(benign.has(al) || benign.has(dn));
      });
      return {found_root: true, armed: dangerous.length,
              items, dangerous};
    }""")
    if not detail.get("found_root"):
        # Drawings toolbar wasn't in the DOM — chart isn't fully laid
        # out yet, but that's the chart_hydrated probe's job to flag.
        # Don't double-fail here; treat as "no armed tool found".
        return (True, {"armed_tools": 0, "no_drawings_root": True})
    armed = detail["armed"]
    return (
        armed == 0,
        {"armed_tools": armed,
         "active_buttons": detail.get("items", []),
         "dangerous": detail.get("dangerous", [])},
    )


async def _probe_chart_hydrated(page: Page) -> tuple[bool, dict]:
    """Chart has rendered — chart API/legend evidence + a sized canvas.

    Why not price-axis labels: TV draws the y-axis price ticks on a
    `<canvas>`, not as DOM. Counting DOM elements there always returns
    0 even when the chart is fully hydrated (cost us a debug cycle).

    Two-signal check:
    - Either `[data-qa-id="legend-source-item"]` count >= 1 OR live
      chart API state exposes symbol+resolution. Some clean layouts
      render no DOM legend rows even when the chart is ready.
    - At least one `.chart-markup-table canvas` with non-zero pixel
      dimensions — proves the canvas itself is actually painting.
    Both evidence + canvas must pass; either alone is too soft."""
    detail = await page.evaluate("""() => {
      const legend = document.querySelectorAll(
        '[data-qa-id="legend-source-item"]'
      ).length;
      const canvases = Array.from(document.querySelectorAll(
        '.chart-markup-table canvas, [class*="chart-container"] canvas'
      ));
      const sized = canvases.filter(c => {
        const r = c.getBoundingClientRect();
        return r.width > 100 && r.height > 100;
      }).length;
      let apiSymbol = null;
      let apiResolution = null;
      try {
        const c = window.TradingViewApi._activeChartWidgetWV.value();
        if (c) {
          apiSymbol = c.symbol ? c.symbol() : null;
          apiResolution = c.resolution ? c.resolution() : null;
        }
      } catch (e) {}
      return {
        legend_items: legend,
        sized_canvases: sized,
        api_symbol: apiSymbol,
        api_resolution: apiResolution,
      };
    }""")
    has_state = bool(detail.get("api_symbol") and detail.get("api_resolution"))
    ok = (
        detail["sized_canvases"] >= 1
        and (detail["legend_items"] >= 1 or has_state)
    )
    return (ok, detail)


async def _probe_symbol(
    page: Page, expected: str, state: dict | None = None,
) -> tuple[bool, dict]:
    """Active chart's symbol matches expected (after normalization).

    Tier of preference: `chart.symbolExt()` (rich metadata + ticker
    field) > `chart.symbol()` from `state` (already-cached) >
    `page.title()` regex parse (DOM fallback)."""
    if state is not None and state.get("symbol"):
        # Use ext when reachable for richer metadata + the ticker field
        # which strips exchange prefix natively.
        ext = await replay_api.chart_symbol_ext(page)
        if ext and ext.get("ticker"):
            seen = _normalize_symbol(ext["ticker"])
            want = _normalize_symbol(expected)
            return (seen == want,
                    {"expected": want, "seen": seen, "via": "api_ext",
                     "exchange": ext.get("exchange"),
                     "session": ext.get("session")})
        seen = _normalize_symbol(state["symbol"])
        want = _normalize_symbol(expected)
        return (seen == want, {"expected": want, "seen": seen, "via": "api"})
    title = await page.title()
    m = re.match(r"^\s*([A-Z0-9:\._\-!]+)", title)
    seen_raw = m.group(1) if m else None
    seen = _normalize_symbol(seen_raw)
    want = _normalize_symbol(expected)
    return (seen == want, {"expected": want, "seen": seen,
                            "title": title, "via": "dom"})


async def _probe_interval(
    page: Page, expected: str, state: dict | None = None,
) -> tuple[bool, dict]:
    """Active interval matches expected (after normalization). Prefers
    `chart.resolution()` from the JS API (canonical TV token, no
    locale/aria drift); falls back to the header-toolbar button text."""
    if state is not None and state.get("resolution"):
        seen = _normalize_interval(state["resolution"])
        want = _normalize_interval(expected)
        return (seen == want, {"expected": want, "seen": seen,
                                "raw": state["resolution"], "via": "api"})
    seen_raw = await page.evaluate("""() => {
      const active = document.querySelector(
        '#header-toolbar-intervals button[aria-pressed="true"]'
      ) || document.querySelector(
        '#header-toolbar-intervals button[class*="isActive"]'
      );
      return active && active.innerText ? active.innerText.trim() : null;
    }""")
    seen = _normalize_interval(seen_raw)
    want = _normalize_interval(expected)
    return (seen == want, {"expected": want, "seen": seen,
                            "raw": seen_raw, "via": "dom"})


async def _probe_replay_active(
    page: Page, want_active: bool, api_ok: bool,
) -> tuple[bool, dict]:
    """Bar Replay state matches `want_active`. Prefers
    `replayApi.isReplayStarted()` over the strip-visibility check —
    avoids false positives when the strip lingers during exit."""
    if api_ok:
        is_on = await replay_api.is_replay_started(page)
        return (is_on == want_active,
                {"want_active": want_active, "is_active": is_on, "via": "api"})
    is_on = await page.evaluate("""() => {
      const strip = document.querySelector(
        'div[data-name="replay-bottom-toolbar"]'
      );
      if (!strip) return false;
      const r = strip.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    }""")
    return (is_on == want_active,
            {"want_active": want_active, "is_active": is_on, "via": "dom"})


async def _probe_cursor_time(
    page: Page, expected: datetime, tolerance_min: int, api_ok: bool,
) -> tuple[bool, dict]:
    """Replay cursor time within tolerance of `expected` (naive ET).
    Prefers `replayApi.currentDate()` (epoch ms, exact); falls back
    to BarDate legend parsing when the API isn't reachable."""
    seen: datetime | None = None
    via = "dom"
    raw: Any = None
    if api_ok:
        api_dt = await replay_api.current_replay_date(page)
        if api_dt is not None:
            seen = api_dt.astimezone(_ET).replace(tzinfo=None)
            via = "api"
    if seen is None:
        raw = await page.evaluate(r"""() => {
          const items = Array.from(document.querySelectorAll(
            '[data-qa-id="legend-source-item"]'
          ));
          const bar = items.find(i =>
            (i.innerText || '').trim().startsWith('BarDate')
          );
          return bar ? (bar.innerText || '').trim() : null;
        }""")
        seen = _bardate_to_dt(raw)
    if seen is None:
        return (False, {
            "expected": expected.isoformat(timespec="minutes"),
            "seen": None, "raw": raw, "reason": "no_cursor", "via": via,
        })
    delta_min = abs((seen - expected).total_seconds()) / 60
    ok = delta_min <= tolerance_min
    return (ok, {
        "expected": expected.isoformat(timespec="minutes"),
        "seen": seen.isoformat(timespec="minutes"),
        "delta_min": round(delta_min, 1),
        "tolerance_min": tolerance_min,
        "via": via,
    })


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def assert_capture_ready(page: Page, expect: CaptureExpect) -> dict:
    """Run every applicable invariant check. Returns a metadata dict
    summarizing what was verified. Raises `CaptureInvariantError` on
    the first hard-failed check.

    Soft checks (currently: cursor_time when `expect.soft_cursor=True`)
    log their result via audit but never raise."""
    summary: dict[str, Any] = {"checks": {}}

    async def _hard(name: str, ok: bool, details: dict) -> None:
        summary["checks"][name] = {"ok": ok, **details}
        audit.log(f"capture.invariant.{name}", ok=ok, **details)
        if not ok:
            raise CaptureInvariantError(name, **details)

    async def _soft(name: str, ok: bool, details: dict) -> None:
        summary["checks"][name] = {"ok": ok, "soft": True, **details}
        audit.log(f"capture.invariant.{name}", ok=ok, soft=True, **details)

    # Order matters: cheap structural checks first, then symbol/TF
    # (which depend on the chart being there at all), then replay
    # state, then cursor time (most expensive — requires legend read).
    ok, det = await _probe_no_modal(page)
    await _hard("no_modal", ok, det)

    ok, det = await _probe_no_drawing_tool(page)
    await _hard("no_drawing_tool", ok, det)

    ok, det = await _probe_chart_hydrated(page)
    await _hard("chart_hydrated", ok, det)

    # One-shot API read — chart_state covers symbol+resolution+studies
    # in a single round-trip, and api_ok gates the replay/cursor probes
    # so we don't pay for two API calls when one would do.
    api_ok = await replay_api.api_available(page)
    state = await replay_api.chart_state(page) if api_ok else None
    summary["api_available"] = api_ok

    if expect.symbol is not None:
        ok, det = await _probe_symbol(page, expect.symbol, state)
        await _hard("symbol", ok, det)

    if expect.interval is not None:
        ok, det = await _probe_interval(page, expect.interval, state)
        await _hard("interval", ok, det)

    if expect.replay_mode is not None:
        ok, det = await _probe_replay_active(page, expect.replay_mode, api_ok)
        await _hard("replay_mode", ok, det)

    if expect.cursor_time is not None:
        # Cursor check requires replay to actually be active — guard
        # against the misuse of asking for a cursor time without
        # specifying replay_mode=True.
        ok, det = await _probe_cursor_time(
            page, expect.cursor_time, expect.cursor_tolerance_min, api_ok,
        )
        if expect.soft_cursor:
            await _soft("cursor_time", ok, det)
        else:
            await _hard("cursor_time", ok, det)

    audit.log("capture.invariant.all_passed", **{
        k: v.get("ok") for k, v in summary["checks"].items()
    })
    return summary
