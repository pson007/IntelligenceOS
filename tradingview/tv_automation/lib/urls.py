"""URL construction helpers — primary job is *preserving saved layouts*.

TradingView chart URLs come in two shapes:
    https://www.tradingview.com/chart/?symbol=AAPL
    https://www.tradingview.com/chart/<layout-id>/?symbol=AAPL

The second form says "load SAVED layout `<layout-id>` — drawings, indicators,
pane arrangement, everything — and set symbol to AAPL." Losing the layout
segment blows away the user's saved setup silently. Naively doing
`page.goto("https://www.tradingview.com/chart/?symbol=X")` is destructive
when the user was viewing a saved layout.

`chart_url_for()` inspects the current page URL, extracts the layout
segment (if any), and builds a new URL that keeps it.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

_CHART_LAYOUT_RE = re.compile(r"^/chart/(?P<layout>[A-Za-z0-9_-]+)/?$|^/chart/?$")


def chart_url_for(
    current_url: str | None,
    symbol: str | None = None,
    interval: str | None = None,
) -> str:
    """Build a TradingView chart URL, preserving any layout ID present
    in `current_url`.

    Examples:
        chart_url_for("https://www.tradingview.com/chart/", "AAPL")
          → "https://www.tradingview.com/chart/?symbol=AAPL"

        chart_url_for("https://www.tradingview.com/chart/wqVfOr3Z/?symbol=OLD",
                      "AAPL", "D")
          → "https://www.tradingview.com/chart/wqVfOr3Z/?symbol=AAPL&interval=D"

        chart_url_for("chrome://newtab/", "AAPL")
          → "https://www.tradingview.com/chart/?symbol=AAPL"
    """
    layout_id = _extract_layout_id(current_url)
    path = f"/chart/{layout_id}/" if layout_id else "/chart/"

    params = {}
    if symbol:
        params["symbol"] = symbol
    if interval:
        params["interval"] = interval

    query = urlencode(params) if params else ""
    return f"https://www.tradingview.com{path}" + (f"?{query}" if query else "")


def _extract_layout_id(url: str | None) -> str | None:
    """Return the saved-layout segment from a TV chart URL, or None if
    the URL isn't a TV chart URL or uses the default /chart/ path."""
    if not url:
        return None
    # Quick bail-out for non-TV URLs (chrome://newtab/, about:blank, etc.)
    if "tradingview.com" not in url:
        return None
    # Parse the path segment — we don't need full urlparse for this.
    m = re.search(r"tradingview\.com(/chart(?:/[A-Za-z0-9_-]+)?/?)(?:\?|$)", url)
    if not m:
        return None
    path = m.group(1).rstrip("/")
    # /chart → no layout; /chart/abc123 → layout abc123
    parts = [p for p in path.split("/") if p]
    if len(parts) == 2 and parts[0] == "chart":
        return parts[1]
    return None
