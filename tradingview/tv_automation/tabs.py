"""CDP-target-level chart tab discovery and activation.

`Playwright.context.pages` works well when there's exactly one chart
tab; with multiple charts open (saved layouts, comparison windows),
identifying "the right one" by URL substring is fragile. CDP's own
`/json/list` endpoint gives every page target with stable IDs and the
chart_id parsed out of the URL — same pattern tradesdontlie's MCP
uses for multi-tab scenarios.

`/json/activate/{id}` brings a target to foreground without
`page.bring_to_front()` quirks (which can fail silently when the
window is on another macOS Space).

CDP_URL is sourced from `session.CDP_URL` so this respects the
existing `.env` config; the host extraction is a small parser since
we only need host/port for the JSON endpoints.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from session import CDP_URL


# Short-TTL cache so a workflow that calls `chart_targets()` from
# multiple helpers doesn't re-hit the CDP `/json/list` endpoint each
# time. 1s is short enough that tab open/close events are still
# observable and long enough to swallow a rapid sequence inside one
# request handler.
_CACHE: dict[str, Any] = {"at": 0.0, "value": None}
_CACHE_TTL_S = 1.0


def _cdp_base() -> str | None:
    """Return `http://host:port` from `CDP_URL` (or None if not set)."""
    if not CDP_URL:
        return None
    p = urlparse(CDP_URL)
    if not p.scheme or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}"


_CHART_RX = re.compile(r"tradingview\.com/chart", re.IGNORECASE)
_CHART_ID_RX = re.compile(r"/chart/([^/?#]+)")


async def chart_targets(*, fresh: bool = False) -> list[dict[str, Any]]:
    """Return every TradingView chart tab CDP knows about.

    Each entry: `{id, chart_id, url, title, type}`. Empty list when
    CDP isn't configured or unreachable.

    Cached for 1s so a request handler can call this from multiple
    helpers without re-hitting `/json/list`. Pass `fresh=True` to bust
    the cache (e.g. after deliberately opening a new tab)."""
    now = time.monotonic()
    if not fresh and _CACHE["value"] is not None \
       and (now - _CACHE["at"]) < _CACHE_TTL_S:
        return _CACHE["value"]

    base = _cdp_base()
    if base is None:
        return []
    try:
        async with httpx.AsyncClient(timeout=2.0) as http:
            r = await http.get(f"{base}/json/list")
            r.raise_for_status()
            targets = r.json()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for t in targets:
        if t.get("type") != "page":
            continue
        url = t.get("url", "")
        if not _CHART_RX.search(url):
            continue
        m = _CHART_ID_RX.search(url)
        out.append({
            "id": t.get("id"),
            "chart_id": m.group(1) if m else None,
            "url": url,
            "title": t.get("title", ""),
            "type": "page",
        })
    _CACHE["at"] = now
    _CACHE["value"] = out
    return out


async def activate_chart(target_id: str) -> bool:
    """Bring the chart tab with `target_id` to the foreground."""
    base = _cdp_base()
    if base is None or not target_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as http:
            r = await http.get(f"{base}/json/activate/{target_id}")
            return r.status_code == 200
    except Exception:
        return False


async def first_chart_target() -> dict[str, Any] | None:
    """Convenience: first chart tab the CDP knows about, or None."""
    targets = await chart_targets()
    return targets[0] if targets else None


async def preferred_chart_target(
    *, prefer_chart_id: str | None = None,
) -> dict[str, Any] | None:
    """Pick the best chart tab when multiple are open.

    Selection priority:
      1. Tab whose `chart_id` matches `prefer_chart_id` (caller's saved
         layout id, when known).
      2. First tab — keeps current behavior when no preference is
         specified."""
    targets = await chart_targets()
    if not targets:
        return None
    if prefer_chart_id:
        for t in targets:
            if t.get("chart_id") == prefer_chart_id:
                return t
    return targets[0]
