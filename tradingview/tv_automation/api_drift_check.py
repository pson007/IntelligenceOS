"""Detect drift in TradingView's internal JS API surface.

Every JS path in `replay_api`, `bar_reader`, and `overlay_reader` is
undocumented. TV ships builds that occasionally rename internals (e.g.
`_chartWidget` could become `__chartWidget`, or `dataWindowView` could
disappear). The DOM-side `selectors_healer` catches selector drift;
this module catches API drift — same purpose, different surface.

Probes every known accessor and reports `{path, kind, ok, error}` per
entry. Workflows that depend on the API can call `assert_no_drift()`
as a pre-flight; failures suggest patching `replay_api` rather than
trusting the soft-fail fallbacks.

Run from CLI for a one-shot health report:
    cd tradingview && .venv/bin/python -m tv_automation.api_drift_check
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from playwright.async_api import Page

from .lib import audit


# Known JS-API surface — adopted from tradesdontlie/tradingview-mcp's
# `KNOWN_PATHS` plus the additions we discovered live (lastValueData
# fallback, find_bar_index, etc.). `kind` annotates what we expect:
#   - "object": path resolves to a non-null value
#   - "function": path resolves to a callable
#   - "method_on": path's last segment is a method we expect to exist
#                  on the parent object (handles cases where the parent
#                  has a value but the method is missing)
_PROBES: list[dict[str, str]] = [
    {"name": "chart_widget",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value()",
     "kind": "object"},
    {"name": "chart_widget_collection",
     "expr": "window.TradingViewApi._chartWidgetCollection",
     "kind": "object"},
    {"name": "replay_api",
     "expr": "window.TradingViewApi._replayApi",
     "kind": "object"},
    {"name": "main_series_bars",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value()._chartWidget"
             ".model().mainSeries().bars()",
     "kind": "object"},
    {"name": "data_sources",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value()._chartWidget"
             ".model().model().dataSources()",
     "kind": "object"},
    {"name": "time_scale",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value()._chartWidget"
             ".model().timeScale()",
     "kind": "object"},
    # Methods on chart widget
    {"name": "chart.symbol",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value().symbol",
     "kind": "function"},
    {"name": "chart.resolution",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value().resolution",
     "kind": "function"},
    {"name": "chart.symbolExt",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value().symbolExt",
     "kind": "function"},
    {"name": "chart.setSymbol",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value().setSymbol",
     "kind": "function"},
    {"name": "chart.setResolution",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value().setResolution",
     "kind": "function"},
    {"name": "chart.getAllStudies",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value().getAllStudies",
     "kind": "function"},
    # Methods on replay API
    {"name": "replay.isReplayStarted",
     "expr": "window.TradingViewApi._replayApi.isReplayStarted",
     "kind": "function"},
    {"name": "replay.currentDate",
     "expr": "window.TradingViewApi._replayApi.currentDate",
     "kind": "function"},
    {"name": "replay.selectDate",
     "expr": "window.TradingViewApi._replayApi.selectDate",
     "kind": "function"},
    # Methods on time scale
    {"name": "time_scale.zoomToBarsRange",
     "expr": "window.TradingViewApi._activeChartWidgetWV.value()._chartWidget"
             ".model().timeScale().zoomToBarsRange",
     "kind": "function"},
]


_PROBE_JS = r"""
(probes) => {
  const out = [];
  for (const p of probes) {
    let ok = false, err = null, kind_seen = null;
    try {
      const v = eval(p.expr);
      if (v === undefined) { err = 'undefined'; }
      else if (v === null) { err = 'null'; }
      else if (p.kind === 'function') {
        ok = (typeof v === 'function');
        kind_seen = typeof v;
        if (!ok) err = `expected function, got ${typeof v}`;
      }
      else { ok = true; kind_seen = typeof v; }
    } catch (e) {
      err = (e && e.message) || String(e);
    }
    out.push({name: p.name, expr: p.expr, expected: p.kind,
              ok: ok, kind_seen: kind_seen, error: err});
  }
  return out;
}
"""


async def probe_all(page: Page) -> list[dict[str, Any]]:
    """Run every probe and return per-path status."""
    return await page.evaluate(_PROBE_JS, _PROBES)


async def drift_report(page: Page) -> dict[str, Any]:
    """Convenience wrapper: returns `{ok, total, passed, failed, items}`."""
    items = await probe_all(page)
    failed = [i for i in items if not i["ok"]]
    summary = {
        "ok": len(failed) == 0,
        "total": len(items),
        "passed": len(items) - len(failed),
        "failed": len(failed),
        "failed_paths": [i["name"] for i in failed],
        "items": items,
    }
    audit.log("api_drift.scan", **{k: v for k, v in summary.items()
                                    if k != "items"})
    return summary


class ApiDriftError(RuntimeError):
    """One or more known JS-API paths no longer resolve."""

    def __init__(self, failed: list[dict[str, Any]]) -> None:
        self.failed = failed
        names = ", ".join(i["name"] for i in failed)
        super().__init__(f"api_drift: {len(failed)} path(s) failed: {names}")


async def assert_no_drift(page: Page) -> dict[str, Any]:
    """Raise `ApiDriftError` if any probe fails. Otherwise return the
    summary dict so the caller can also use it for logging."""
    summary = await drift_report(page)
    if not summary["ok"]:
        raise ApiDriftError(
            [i for i in summary["items"] if not i["ok"]]
        )
    return summary


async def _cli_main() -> None:
    from .lib.context import chart_session
    async with chart_session() as (_ctx, page):
        summary = await drift_report(page)
        # Trim items in CLI output — the per-probe status list is verbose.
        out = {k: v for k, v in summary.items() if k != "items"}
        print(json.dumps(out, indent=2))
        if not summary["ok"]:
            print("\nFailed paths:", flush=True)
            for i in summary["items"]:
                if not i["ok"]:
                    print(f"  {i['name']}: {i['error']}", flush=True)


if __name__ == "__main__":
    asyncio.run(_cli_main())
