"""Chart-readiness probe — verify TradingView's JS API is exposed before
a workflow tries to use it.

`preflight.ensure_automation_chromium()` covers the OS layer (Chrome
running, CDP reachable, TV signed in). It does NOT cover whether the
attached page is a chart tab with `window.TradingViewApi` populated —
a freshly-opened tab, a redirect to /chart/ that's still loading, or a
TV maintenance page all pass preflight but fail every JS-API call
downstream.

Pattern lifted from tradesdontlie/tradingview-mcp's `health.healthCheck`:
single round-trip that returns symbol/resolution/chart_type plus
`api_available`. Workflows that need the chart API call
`assert_chart_ready(page)` right after attaching; everything else
treats this as optional metadata.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from . import replay_api
from .lib import audit


class ChartNotReadyError(RuntimeError):
    """The chart's JS API isn't reachable — workflow should not proceed."""

    def __init__(self, reason: str, **details: Any) -> None:
        self.reason = reason
        self.details = details
        msg = f"chart_not_ready: {reason}"
        if details:
            msg += f" ({', '.join(f'{k}={v!r}' for k, v in details.items())})"
        super().__init__(msg)


async def chart_ready(page: Page) -> dict[str, Any]:
    """Return readiness metadata. Never raises.

    Shape: `{api_available, symbol, resolution, chart_type, url}`. A
    workflow can decide what 'ready enough' means for its purposes
    (e.g., a watchlist-only flow might not require resolution)."""
    info: dict[str, Any] = {
        "url": page.url,
        "api_available": False,
        "symbol": None,
        "resolution": None,
        "chart_type": None,
    }
    if not await replay_api.api_available(page):
        return info
    state = await replay_api.chart_state(page)
    info["api_available"] = True
    if state:
        info["symbol"] = state.get("symbol")
        info["resolution"] = state.get("resolution")
        info["chart_type"] = state.get("chart_type")
    return info


async def assert_chart_ready(page: Page) -> dict[str, Any]:
    """Raise `ChartNotReadyError` if the chart API isn't reachable or
    the symbol/resolution can't be read. Otherwise return the readiness
    metadata so the caller can also use it for logging."""
    info = await chart_ready(page)
    audit.log("health.chart_ready", **info)
    if not info["api_available"]:
        raise ChartNotReadyError("api_unavailable", url=info["url"])
    if not info["symbol"]:
        raise ChartNotReadyError("no_symbol", url=info["url"])
    if not info["resolution"]:
        raise ChartNotReadyError("no_resolution",
                                 symbol=info["symbol"], url=info["url"])
    return info
