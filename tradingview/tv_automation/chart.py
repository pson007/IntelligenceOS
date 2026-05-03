"""Chart surface — symbol/timeframe control, screenshots, chart metadata.

Pure reads (screenshot, metadata) don't take the lock or assert paper
trading — they can't move money. `set-symbol` navigates the existing
chart tab so any open Pine Editor / Trading Panel follows along.

CLI:
    python -m tv_automation.chart set-symbol NVDA --tf 60
    python -m tv_automation.chart set-symbol AAPL --tf 1D
    python -m tv_automation.chart screenshot AAPL 1D
    python -m tv_automation.chart screenshot AAPL 1D -o /tmp/x.png
    python -m tv_automation.chart metadata         # current chart info
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from preflight import ensure_automation_chromium  # top-level module in tradingview/
from session import tv_context

from .lib import audit
from .lib.cli import run
from .lib.errors import NotLoggedInError
from .lib.guards import assert_logged_in
from .lib.session_modal import click_reconnect_if_present
from .lib.urls import chart_url_for

# Friendly timeframe → TradingView's URL `interval` param.
# TV uses minute counts as strings, plus single letters for D/W/M.
# Lookup is case-insensitive for minute/hour frames ("1h" / "1H" both ok)
# while preserving the canonical casing for D/W/M (TV's URL param is
# uppercase there).
_TIMEFRAME_MAP = {
    "30s": "30S", "45s": "45S",
    "1m": "1", "2m": "2", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240",
    "1d": "D", "1w": "W", "1mo": "M",
    # Also accept the canonical uppercase forms directly.
    "1D": "D", "1W": "W", "1M": "M",
}


def resolve_timeframe(tf: str | None) -> str | None:
    """Map a friendly timeframe to TradingView's interval param.
    Case-insensitive for m/h; accepts 1D/1W/1M in either case. Returns
    None for None input; pass-through if already a TV interval string
    like "60" or "D"."""
    if tf is None:
        return None
    # Try exact first (preserves "1D" vs "1d" if user passed explicitly).
    if tf in _TIMEFRAME_MAP:
        return _TIMEFRAME_MAP[tf]
    # Case-insensitive fallback.
    low = tf.lower()
    if low in _TIMEFRAME_MAP:
        return _TIMEFRAME_MAP[low]
    # Might already be a TV-native interval (e.g. "60", "D"). Pass through.
    return tf


# Back-compat export — some code still references TIMEFRAME_MAP.
TIMEFRAME_MAP = _TIMEFRAME_MAP

CHART_URL = "https://www.tradingview.com/chart/"

_DEFAULT_SCREENSHOT_DIR = Path.home() / "Desktop" / "TradingView"

# Named regions for `screenshot --area <name>`. Each entry maps a
# user-facing area name to a Playwright selector. Special value "full"
# (handled separately below) means "entire viewport, no crop" — the
# right answer when the chart-canvas crop hides the sidebar/Pine
# editor / Account Manager you actually want to see.
_SCREENSHOT_AREAS: dict[str, str] = {
    "chart": ".chart-container, .layout__area--center",
    "sidebar": '[data-name="widgetbar-pages-with-tabs"]',
    "right_toolbar": '[data-name="right-toolbar"]',
    "pine_editor": ".pine-editor-monaco",
    "account_manager": '[class*="bottom-widgetbar-content"]',
}


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

async def _find_or_open_chart(ctx: BrowserContext) -> Page:
    """Reuse an existing TradingView chart tab if one is open; otherwise
    open a new one. Prefers the user's in-progress chart over creating
    parallel tabs that accumulate over time."""
    for p in ctx.pages:
        try:
            if "tradingview.com/chart" in p.url:
                await p.bring_to_front()
                return p
        except Exception:
            continue
    # No chart tab to reuse — we'd open one and goto(CHART_URL). If the
    # user isn't signed in, TV redirects /chart/ → /accounts/signin/ and
    # signin self-redirects (CSRF/next-param), surfacing as a confusing
    # "Page.goto: Navigation interrupted by another navigation" instead
    # of NotLoggedInError. Pre-check the cookie so the failure is clean
    # and we don't leak a stale signin tab on every retry.
    cookies = await ctx.cookies("https://www.tradingview.com/")
    if not any(c["name"] == "sessionid" for c in cookies):
        raise NotLoggedInError(
            "No TradingView sessionid cookie. Sign in to the Chromium-Automation "
            "profile (CDP on :9222), then retry."
        )
    page = await ctx.new_page()
    await page.goto(CHART_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    await page.wait_for_timeout(1500)
    return page


async def _navigate(page: Page, symbol: str | None, interval: str | None) -> None:
    """Navigate the chart to symbol/interval, PRESERVING any saved-layout
    path segment in the current URL (e.g. `/chart/wqVfOr3Z/`). Without
    this, every symbol change wipes the user's saved indicators/drawings.

    Two paths:
      1. **In-place API mutation** via `chart.setSymbol/setResolution`.
         No reload, ~50ms, preserves Bar Replay state and panel focus.
         Used when the page is already on a TV chart with the JS API
         exposed — i.e. the common case during a workflow.
      2. **Page navigation** via `page.goto(target_url)`. Used on
         first-load (chart API not exposed yet) and as a fallback.

    The URL is *not* updated by the API path — anything that reads
    URL params for current state should use `chart.symbol()` /
    `chart.resolution()` (via `replay_api.chart_state`) instead."""
    if not symbol and not interval:
        return
    from . import replay_api
    target = chart_url_for(page.url, symbol, interval)

    # In-place path — only when we're already on a chart with the API
    # exposed. Skips ~2.5s of page reload + canvas hydration. The URL is
    # stale after this path, so use chart_state() for skip checks too.
    api_available = False
    if "tradingview.com/chart" in page.url \
       and await replay_api.api_available(page):
        api_available = True
        state = await replay_api.chart_state(page)
        if _state_matches_target(state, symbol, interval):
            audit.log("chart.navigate.skip",
                      reason="already_on_target_api",
                      current=page.url[:120], target=target[:120],
                      landed=state)
            return
        landed = await replay_api.set_symbol_in_place(
            page, symbol=symbol, interval=interval,
        )
        if landed is not None:
            audit.log("chart.navigate.in_place",
                      symbol=symbol, interval=interval, landed=landed)
            return
        audit.log("chart.navigate.in_place.fallback",
                  symbol=symbol, interval=interval)

    if not api_available and _url_matches_target(page.url, symbol, interval):
        audit.log("chart.navigate.skip",
                  reason="already_on_target_url",
                  current=page.url[:120], target=target[:120])
        return

    await page.goto(target, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    await page.wait_for_timeout(1500)


def _state_matches_target(state: dict | None, symbol: str | None,
                          interval: str | None) -> bool:
    """True when live TradingView chart API state matches the request.

    Unlike URL params, this remains authoritative after in-place
    `setSymbol` / `setResolution` calls, which deliberately do not
    rewrite the browser URL."""
    if state is None:
        return False
    if symbol:
        seen = str(state.get("symbol") or "")
        seen_tail = seen.split(":")[-1]
        want_tail = symbol.split(":")[-1]
        if not (seen == symbol or seen_tail == want_tail):
            return False
    if interval:
        if state.get("resolution") != resolve_timeframe(interval):
            return False
    return True


def _url_matches_target(url: str, symbol: str | None,
                        interval: str | None) -> bool:
    """True if `url` already carries `symbol` and `interval` as query
    params. Case-sensitive for symbol (TV is), interval compared after
    `resolve_timeframe` so "5m" and "5" both count as matches."""
    from urllib.parse import parse_qs, urlparse
    try:
        q = parse_qs(urlparse(url).query)
    except Exception:
        return False
    if symbol:
        if q.get("symbol", [None])[0] != symbol:
            return False
    if interval:
        want = resolve_timeframe(interval)
        got = q.get("interval", [None])[0]
        if got != want:
            return False
    return True


async def _extract_metadata(page: Page) -> dict:
    """Read the active chart's symbol + interval.

    TradingView's URL/title can lag behind in-place API navigation, so
    prefer `chart.symbol()` / `chart.resolution()` and use DOM/URL only
    as fallback."""
    title = await page.title()
    url = page.url
    symbol = interval = None

    try:
        from . import replay_api
        state = await replay_api.chart_state(page)
        if state is not None:
            interval = state.get("resolution") or None
            ext = await replay_api.chart_symbol_ext(page)
            symbol = (
                (ext or {}).get("ticker")
                or state.get("symbol")
                or None
            )
            if symbol and ":" in symbol:
                symbol = symbol.split(":")[-1]
    except Exception:
        pass

    m = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s+([A-Z0-9]+)\s+chart", title)
    if m and not symbol:
        symbol, interval = m.group(1), m.group(2)
    elif not symbol:
        m2 = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s", title)
        if m2:
            symbol = m2.group(1)

    if not interval:
        try:
            interval = await page.evaluate("""() => {
              const active = document.querySelector(
                '#header-toolbar-intervals button[aria-pressed="true"]'
              ) || document.querySelector(
                '#header-toolbar-intervals button[class*="isActive"]'
              );
              if (active && active.innerText) return active.innerText.trim();
              const btn = document.querySelector(
                'button[aria-label^="Change interval"], button[id="header-toolbar-intervals"]'
              );
              return btn && btn.innerText ? btn.innerText.trim() : null;
            }""")
        except Exception:
            interval = None

    if not symbol:
        um = re.search(r"[?&]symbol=([^&]+)", url)
        if um:
            symbol = um.group(1)
    if not interval:
        um = re.search(r"[?&]interval=([^&]+)", url)
        if um:
            interval = um.group(1)

    return {
        "symbol": symbol or "UNKNOWN",
        "interval": interval or "UNKNOWN",
        "url": url,
        "title": title,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def set_symbol(symbol: str, interval: str | None = None) -> dict:
    """Navigate the active chart tab to the given symbol (and optionally
    timeframe). Returns the resulting metadata."""
    tv_interval = resolve_timeframe(interval)
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)
        await _navigate(page, symbol, tv_interval)
        meta = await _extract_metadata(page)
        audit.log("chart.set_symbol", symbol=symbol, interval=interval, resolved=meta)
        return meta


async def screenshot(
    symbol: str | None,
    interval: str | None,
    output: Path | None,
    *,
    area: str = "chart",
    read_indicator_values: bool = False,
) -> dict:
    """Capture a PNG. If symbol/interval given, navigate first.

    `area` selects the region to capture:
      - "chart" (default): the chart canvas only — best for "what does
        the price action look like."
      - "full": the entire browser viewport — captures everything
        on screen including the right sidebar, Pine Editor, and
        Account Manager. Use when you need to verify multi-panel
        state.
      - "sidebar" / "pine_editor" / "right_toolbar" /
        "account_manager": specific named regions. Each maps to a
        Playwright selector in `_SCREENSHOT_AREAS`. Falls back to
        full viewport if the region isn't found (e.g. Pine Editor
        is collapsed).

    `read_indicator_values=True` reads `chart.dataWindowView()` /
    `dataSources().lastValueData()` while the same page is attached,
    populating an `indicator_values` field in the returned dict.
    Saves a second CDP attach when the caller (e.g. analyze_mtf) wants
    both the screenshot and the numerical indicator outputs.
    """
    if area != "full" and area not in _SCREENSHOT_AREAS:
        raise ValueError(
            f"unknown area {area!r}; valid: "
            f"{sorted(list(_SCREENSHOT_AREAS) + ['full'])}"
        )

    tv_interval = resolve_timeframe(interval)
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)
        await _navigate(page, symbol, tv_interval)
        meta = await _extract_metadata(page)

        if output is None:
            _DEFAULT_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", meta["symbol"])
            safe_int = re.sub(r"[^A-Za-z0-9]+", "_", meta["interval"])
            # Tag area in the filename when it's not the default — so
            # captures of different regions don't collide on the same
            # symbol/interval/second.
            area_suffix = "" if area == "chart" else f"_{area}"
            output = _DEFAULT_SCREENSHOT_DIR / f"{safe_sym}_{safe_int}{area_suffix}_{ts}.png"
        else:
            output.parent.mkdir(parents=True, exist_ok=True)

        # Dismiss any open TV dialog / settings panel / dropdown sitting
        # on top of the chart — otherwise a Settings modal (Symbol /
        # Canvas / Trading tabs etc.) ends up in the PNG and the vision
        # LLM reads garbage. Cheap when nothing's open (~5ms).
        from .lib.modal import dismiss_overlays
        overlay_state = await dismiss_overlays(page)
        if overlay_state["passes"] > 0 or overlay_state["modals_left"] > 0:
            audit.log("chart.screenshot.dismissed_overlays",
                      **overlay_state)

        captured_area = area
        fell_back = False
        if area == "full":
            # full_page=False captures the viewport (TV's UI is
            # absolutely-positioned so there's no useful page scroll
            # height — viewport is what the user sees).
            await page.screenshot(path=str(output), full_page=False)
        else:
            region = page.locator(_SCREENSHOT_AREAS[area]).first
            try:
                await region.wait_for(state="visible", timeout=5000)
                await region.screenshot(path=str(output))
            except Exception:
                # Fall back to full viewport so the caller always gets
                # a usable image — better than failing silently.
                await page.screenshot(path=str(output), full_page=False)
                captured_area = "full"
                fell_back = True

        indicator_values = None
        user_drawings_data = None
        if read_indicator_values:
            from . import replay_api, user_drawings as ud
            try:
                indicator_values = await replay_api.read_indicator_values(page)
            except Exception as e:
                audit.log("chart.indicator_values.fail", err=str(e))
            try:
                user_drawings_data = await ud.read_user_drawings(page)
            except Exception as e:
                audit.log("chart.user_drawings.fail", err=str(e))

        audit.log("chart.screenshot",
                  path=str(output), area=captured_area,
                  fell_back=fell_back, **meta)
        result = {
            "path": str(output), "area": captured_area,
            "fell_back": fell_back, **meta,
        }
        if read_indicator_values:
            result["indicator_values"] = indicator_values
            result["user_drawings"] = user_drawings_data
        return result


async def click_at(
    x: int,
    y: int,
    *,
    button: str = "left",
    double: bool = False,
    bypass_overlap: bool = False,
) -> dict:
    """Click at viewport pixel coordinates `(x, y)` — selector-free.

    Combine with `screenshot --area full` for vision-driven control:
    take a screenshot, identify the target visually, issue the click
    by its pixel position. Useful when DOM selectors break (TV ships
    a UI change), when an element has no stable selector, or when the
    target is canvas-rendered.

    `button` is "left" / "right" / "middle". `double` does a
    double-click instead of a single. `bypass_overlap=True` wraps the
    click in `lib.overlays.bypass_overlap_intercept` — set when a
    right-docked Pine Editor's wrapper is intercepting events at the
    target coords (see ROADMAP §7g').

    Returns a result describing what was at `(x, y)` immediately
    before AND after the click, so a vision-driven loop can verify
    the click landed on the intended element AND notice if the click
    triggered a UI change. `element_after` is best-effort — clicks
    that navigate or animate may make the post-read race.
    """
    if button not in ("left", "right", "middle"):
        raise ValueError(f"button must be left/right/middle (got {button!r})")
    # Lazy import to keep chart.py's import surface small.
    from .lib.overlays import bypass_overlap_intercept

    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)

        async def _read_element_at(label: str) -> dict | None:
            # snake_case keys to match describe_screen — so chaining
            # the two (describe → identify → click → verify) doesn't
            # need a key-translation step.
            return await page.evaluate(
                r"""({px, py}) => {
                    const el = document.elementFromPoint(px, py);
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {
                        tag: el.tagName,
                        data_name: el.getAttribute('data-name'),
                        aria_label: el.getAttribute('aria-label'),
                        title: el.getAttribute('title'),
                        text: (el.innerText || '').trim().slice(0, 60),
                        classes: (el.className || '').toString().slice(0, 80),
                        rect: {
                            x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height),
                        },
                    };
                }""",
                {"px": x, "py": y},
            )

        element_before = await _read_element_at("before")

        async def _do_click() -> None:
            if double:
                await page.mouse.dblclick(x, y, button=button)
            else:
                await page.mouse.click(x, y, button=button)

        if bypass_overlap:
            async with bypass_overlap_intercept(page):
                await _do_click()
        else:
            await _do_click()

        # Brief settle for animations / DOM updates triggered by the click.
        await page.wait_for_timeout(200)
        try:
            element_after = await _read_element_at("after")
        except Exception:
            # Page may have navigated mid-click.
            element_after = None

        audit.log("chart.click_at",
                  x=x, y=y, button=button, double=double,
                  bypass_overlap=bypass_overlap,
                  element_before_tag=(element_before or {}).get("tag"),
                  element_before_data_name=(element_before or {}).get("data_name"))
        return {
            "ok": True, "x": x, "y": y,
            "button": button, "double": double,
            "bypass_overlap": bypass_overlap,
            "element_before": element_before,
            "element_after": element_after,
        }


async def describe_screen(
    *,
    area: str = "full",
    include_all: bool = False,
    output: Path | None = None,
) -> dict:
    """Bridge the screenshot ↔ DOM gap in one round-trip: take a
    screenshot AND return the inventory of clickable elements with
    their bounding boxes + identifier hints.

    Pairs with `click_at` for selector-free vision-driven control:
    Read the returned screenshot, find the element you want by sight,
    look up its `center` in the inventory, click those coords. No
    manual DOM querying, no eyeballing pixel positions from a
    downscaled image.

    `area` selects the screenshot region AND scopes the inventory to
    elements within that region. Use "full" for everything (default),
    or "chart" / "sidebar" / "pine_editor" / "right_toolbar" /
    "account_manager" to focus.

    `include_all=True` returns every visible element — buttons,
    links, role=tab/button/menuitem, inputs. Default behavior keeps
    only "addressable" elements (those with data-name OR aria-label
    OR id) since unaddressed elements are rarely useful targets and
    they bloat the inventory. Inventories on the chart page typically
    return 30-100 addressable items vs 500+ when `include_all` is set.

    Returns:
        {
          "ok": True,
          "screenshot": {"path": "...", "area": "...", "fell_back": False},
          "viewport": {"w": 1565, "h": 812},
          "element_count": 47,
          "elements": [
            {
              "tag": "BUTTON",
              "data_name": "alerts",
              "aria_label": "Alerts",
              "id": null,
              "title": null,
              "text": "",
              "rect": {"x": 1520, "y": 89, "w": 44, "h": 30},
              "center": {"x": 1542, "y": 104},
              "selector_hint": "[data-name=\"alerts\"]"
            },
            ...
          ]
        }
    """
    # Screenshot first — also doubles as the "do we have a chart"
    # check via assert_logged_in inside.
    if output is None:
        _DEFAULT_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        output = _DEFAULT_SCREENSHOT_DIR / f"describe_{area}_{ts}.png"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)

    shot = await screenshot(symbol=None, interval=None, output=output, area=area)

    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)

        scope_selector = None if area in ("full", "chart") else _SCREENSHOT_AREAS.get(area)

        inventory = await page.evaluate(
            r"""({scopeSel, includeAll}) => {
                // Determine the root we scan within.
                let root = document.body;
                if (scopeSel) {
                    const candidate = document.querySelector(scopeSel);
                    if (candidate) root = candidate;
                }
                const viewport = {
                    w: window.innerWidth,
                    h: window.innerHeight,
                };
                // What counts as "potentially clickable":
                // - Native interactive: button, a, input, select
                // - ARIA interactive: role=button/tab/menuitem/link/checkbox
                // - Anything with data-name (TV's stable handle)
                // - Anything with aria-label (when paired with onclick-like wiring)
                // We then filter to visible elements within the
                // viewport (negative-x or off-bottom items are TV's
                // overflow tricks — see ROADMAP §7g'/§4f).
                const sels = [
                    'button', 'a[href]', 'input', 'select',
                    '[role="button"]', '[role="tab"]', '[role="menuitem"]',
                    '[role="link"]', '[role="checkbox"]', '[data-name]',
                ];
                const all = new Set();
                sels.forEach(s => {
                    root.querySelectorAll(s).forEach(el => all.add(el));
                });
                const out = [];
                all.forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    // Skip elements outside the viewport — TV's
                    // "translateX(-999999)" overflow trick lives here.
                    if (r.x + r.width < 0 || r.y + r.height < 0) return;
                    if (r.x > viewport.w || r.y > viewport.h) return;
                    const dataName = el.getAttribute('data-name');
                    const ariaLabel = el.getAttribute('aria-label');
                    const id = el.id || null;
                    const title = el.getAttribute('title');
                    const role = el.getAttribute('role');
                    // Addressable filter: at least one stable identifier.
                    if (!includeAll && !(dataName || ariaLabel || id)) return;
                    // Build a best-guess selector (most-specific first).
                    let selectorHint = null;
                    if (dataName) selectorHint = `[data-name="${dataName}"]`;
                    else if (id) selectorHint = `#${id}`;
                    else if (ariaLabel) selectorHint = `[aria-label="${ariaLabel.replace(/"/g, '\\"')}"]`;
                    else if (role) selectorHint = `[role="${role}"]`;
                    out.push({
                        tag: el.tagName,
                        data_name: dataName,
                        aria_label: ariaLabel,
                        id,
                        title,
                        role,
                        text: (el.innerText || '').trim().slice(0, 60).replace(/\s+/g, ' '),
                        rect: {
                            x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height),
                        },
                        center: {
                            x: Math.round(r.x + r.width / 2),
                            y: Math.round(r.y + r.height / 2),
                        },
                        selector_hint: selectorHint,
                    });
                });
                // Stable sort: top-to-bottom, left-to-right (reading order).
                out.sort((a, b) => {
                    if (Math.abs(a.rect.y - b.rect.y) > 8) return a.rect.y - b.rect.y;
                    return a.rect.x - b.rect.x;
                });
                return {viewport, elements: out};
            }""",
            {"scopeSel": scope_selector, "includeAll": include_all},
        )

        audit.log("chart.describe_screen",
                  area=area, include_all=include_all,
                  element_count=len(inventory["elements"]),
                  screenshot_path=shot["path"])
        return {
            "ok": True,
            "screenshot": {
                "path": shot["path"],
                "area": shot.get("area", area),
                "fell_back": shot.get("fell_back", False),
            },
            "viewport": inventory["viewport"],
            "element_count": len(inventory["elements"]),
            "elements": inventory["elements"],
        }


async def click_label(
    query: str,
    *,
    area: str = "full",
    bypass_overlap: bool = False,
    min_score: int = 25,
) -> dict:
    """Click an element by free-text description — no coords, no selectors.

    Wraps the three vision-loop fragments into one call:
      1. Scan DOM for elements matching `query` (data-name OR aria-label
         OR text), score each by fuzzy closeness.
      2. Pick the top candidate. Compute a "safe click point" — the
         rect center, with auto-correction if it lands on a nested
         child element that doesn't propagate clicks (the watchlist-
         button-vs-inner-SPAN gotcha).
      3. Issue `click_at` at the safe point.
      4. Return the matched element + click verification.

    Lower the bar to selector-free use:

        tv chart click-label "Watchlist"      # opens watchlist sidebar / menu
        tv chart click-label "Add symbol"     # clicks the + button
        tv chart click-label "Pine"           # toggles Pine editor

    `area` scopes the search to a region (default: "full"). `min_score`
    rejects matches below the threshold (default 25; lower = more
    permissive). Returns:

        {
          "ok": bool,
          "query": "...",
          "matched": <element from describe-screen inventory> | None,
          "score": int,
          "safe_point": {"x": ..., "y": ...},
          "safe_point_corrected": bool,
          "click_result": <click_at result with element_before/after>,
          "alternates": [<top 3 other candidates for diagnostic>],
        }
    """
    # Lazy imports — keep chart.py's import surface minimal.
    from .lib.selectors_healer import find_candidates

    if not query or not query.strip():
        raise ValueError("query must be non-empty")
    query = query.strip()
    scope_selector = None if area in ("full", "chart") else _SCREENSHOT_AREAS.get(area)

    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)

        # Reuse the healer's scoring — pass the query as all three hint
        # types so data-name / aria-label / text matches all compete.
        # Whichever scores highest wins.
        hints = {
            "data_name": query,
            "aria_label": query,
            "text": query,
        }
        candidates = await find_candidates(
            page, hints, scope_selector=scope_selector,
        )
        candidates = [c for c in candidates if c["score"] >= min_score]
        if not candidates:
            return {
                "ok": False, "query": query,
                "reason": "no_match",
                "min_score": min_score,
            }

        top = candidates[0]
        rect = top["rect"]
        # Default safe point: rect center.
        sx = rect["x"] + rect["w"] // 2
        sy = rect["y"] + rect["h"] // 2

        # Verify the center isn't trapped by a nested child whose
        # click handler doesn't propagate. We check what
        # elementFromPoint returns at the center vs the candidate's
        # identifying attributes (data-name / id / aria-label). If
        # they don't match AND the candidate isn't an ancestor, shift
        # to the rect's top padding (y = rect.y + small offset).
        target_dn = top.get("data_name")
        target_id = top.get("id")
        target_al = top.get("aria_label")

        async def _is_safe(px: int, py: int) -> bool:
            return await page.evaluate(
                r"""({px, py, dn, id, al}) => {
                    const el = document.elementFromPoint(px, py);
                    if (!el) return false;
                    // Walk up: target is el, or el's ancestor, matches.
                    let p = el;
                    for (let i = 0; i < 6 && p; i++) {
                        if (dn && p.getAttribute('data-name') === dn) return true;
                        if (id && p.id === id) return true;
                        if (al && p.getAttribute('aria-label') === al) return true;
                        p = p.parentElement;
                    }
                    // Or maybe el is a descendant of the target — but
                    // we only walk UP from elementFromPoint. To check
                    // "is el a descendant of target", we'd need target
                    // by selector. Skip for now — false negatives here
                    // just trigger the corrective shift, no harm.
                    return false;
                }""",
                {"px": px, "py": py, "dn": target_dn, "id": target_id, "al": target_al},
            )

        safe_point_corrected = False
        if not await _is_safe(sx, sy):
            # Try top padding — a few pixels in from the rect's top edge.
            offset = max(3, min(8, rect["h"] // 6))
            ty = rect["y"] + offset
            if await _is_safe(sx, ty):
                sy = ty
                safe_point_corrected = True
            else:
                # Try left padding.
                tx = rect["x"] + offset
                if await _is_safe(tx, sy):
                    sx = tx
                    safe_point_corrected = True
                # If neither worked, fall through with the original
                # center — the click_result will surface element_before
                # so the caller can see what was actually hit.

        click_result = await click_at(
            sx, sy, button="left", double=False,
            bypass_overlap=bypass_overlap,
        )

        return {
            "ok": True,
            "query": query,
            "matched": top,
            "score": top["score"],
            "safe_point": {"x": sx, "y": sy},
            "safe_point_corrected": safe_point_corrected,
            "click_result": click_result,
            "alternates": candidates[1:4],
        }


async def metadata() -> dict:
    """Return current chart's symbol, interval, and URL. Read-only."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)
        return await _extract_metadata(page)


# ---------------------------------------------------------------------------
# Window management (CDP Browser.setWindowBounds + macOS fullscreen)
# ---------------------------------------------------------------------------

async def _window_bounds(page) -> tuple[object, int, dict]:
    """Open a CDP session on `page`, return (session, window_id, bounds).

    `bounds` is Chrome's current {left, top, width, height, windowState}.
    Chrome enforces a minimum size (~500x400); smaller values get clamped
    or rejected silently by DevTools."""
    cdp = await page.context.new_cdp_session(page)
    target = await cdp.send("Browser.getWindowForTarget")
    window_id = target["windowId"]
    bounds = target["bounds"]
    return cdp, window_id, bounds


async def size() -> dict:
    """Report the current browser window bounds AND the page viewport.

    Window bounds reflect OS-level window size; viewport is the page's
    CSS-pixel content area (window - chrome + devicePixelRatio effects).
    They differ because Chrome's tab strip, address bar, and macOS
    traffic-lights take ~80-130px of the window height."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)
        _, window_id, bounds = await _window_bounds(page)
        viewport = await page.evaluate(
            "() => ({w: window.innerWidth, h: window.innerHeight, "
            "dpr: window.devicePixelRatio})"
        )
        audit.log("chart.size", window_id=window_id,
                  bounds=bounds, viewport=viewport)
        return {
            "ok": True,
            "window_id": window_id,
            "bounds": bounds,
            "viewport": viewport,
        }


async def resize(width: int, height: int) -> dict:
    """Resize the browser window to `width` × `height` (OS pixels).

    Uses CDP `Browser.setWindowBounds`. If the window is currently
    fullscreen or maximized, setWindowBounds silently ignores size
    changes — so we force `windowState: normal` first, then apply the
    size. Returns the before/after bounds and the resulting viewport.

    Affects the ENTIRE browser window (any other tabs move too). For
    the dedicated Chromium-Automation profile that's expected."""
    if width < 400 or height < 300:
        raise ValueError(
            f"width/height must be at least 400x300 (got {width}x{height}); "
            "Chrome rejects smaller sizes"
        )
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)
        cdp, window_id, before = await _window_bounds(page)

        # Chrome refuses size changes while fullscreen/maximized. Flip
        # to normal first; Chrome preserves the resulting size when we
        # then send width/height.
        if before.get("windowState") in ("fullscreen", "maximized", "minimized"):
            await cdp.send("Browser.setWindowBounds", {
                "windowId": window_id,
                "bounds": {"windowState": "normal"},
            })
            await page.wait_for_timeout(300)

        await cdp.send("Browser.setWindowBounds", {
            "windowId": window_id,
            "bounds": {"width": width, "height": height},
        })
        # Give the page a moment to relayout before reading back.
        await page.wait_for_timeout(400)

        _, _, after = await _window_bounds(page)
        viewport = await page.evaluate(
            "() => ({w: window.innerWidth, h: window.innerHeight})"
        )
        audit.log("chart.resize",
                  requested={"width": width, "height": height},
                  before=before, after=after, viewport=viewport)
        return {
            "ok": True,
            "window_id": window_id,
            "before": before,
            "after": after,
            "viewport": viewport,
        }


async def fullscreen(mode: str = "toggle") -> dict:
    """Enter, exit, or toggle the browser's fullscreen mode.

    Uses CDP `Browser.setWindowBounds` with `windowState: fullscreen` /
    `normal`. (Tried Cmd+Ctrl+F via Playwright first — doesn't work,
    because Playwright dispatches keyboard events to page content, not
    to Chrome's browser chrome where that shortcut is handled.)

    `mode` ∈ {"on", "off", "toggle"}. Reads current windowState first
    and no-ops if already in the desired state. CDP's state transition
    is synchronous from our side but the OS animation (macOS Spaces)
    runs in the background.

    Cross-platform: `fullscreen` state works on macOS, Linux, and
    Windows via CDP — the OS-level transition differs but the result
    is the same (browser fills the display)."""
    if mode not in ("on", "off", "toggle"):
        raise ValueError(f"mode must be on/off/toggle (got {mode!r})")
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        await click_reconnect_if_present(page)
        cdp, window_id, before = await _window_bounds(page)
        was_fullscreen = before.get("windowState") == "fullscreen"

        if mode == "toggle":
            target_state = "normal" if was_fullscreen else "fullscreen"
        elif mode == "on":
            target_state = "fullscreen"
        else:  # off
            target_state = "normal"

        changed = target_state != before.get("windowState")
        if changed:
            await cdp.send("Browser.setWindowBounds", {
                "windowId": window_id,
                "bounds": {"windowState": target_state},
            })
            # Allow the fullscreen animation + viewport relayout to
            # settle before reading back state.
            await page.wait_for_timeout(1000)

        _, _, after = await _window_bounds(page)
        is_fullscreen = after.get("windowState") == "fullscreen"
        viewport = await page.evaluate(
            "() => ({w: window.innerWidth, h: window.innerHeight})"
        )
        audit.log("chart.fullscreen",
                  mode=mode, target_state=target_state, changed=changed,
                  was_fullscreen=was_fullscreen,
                  is_fullscreen=is_fullscreen,
                  viewport=viewport)
        return {
            "ok": True,
            "mode": mode,
            "target_state": target_state,
            "changed": changed,
            "was_fullscreen": was_fullscreen,
            "is_fullscreen": is_fullscreen,
            "viewport": viewport,
        }


async def reconnect() -> dict:
    """Explicit invocation of the session-disconnect-modal check.

    The same check runs as a preflight on every other `tv chart`
    subcommand (and all `chart_session`-using surfaces), so you rarely
    need this. Useful for debugging ("is the modal actually up?") and
    for a manual reconnect nudge when TV's auto-dismiss race is tight.
    Returns `{present: False}` when no modal is visible."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        # Deliberately call the primitive WITHOUT relying on the
        # auto-preflight — we want the full detect+click result
        # returned to the caller, not swallowed upstream.
        result = await click_reconnect_if_present(page)
        audit.log("chart.reconnect", **result)
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.chart")
    sub = p.add_subparsers(dest="cmd", required=True)

    ss = sub.add_parser("set-symbol", help="Navigate chart to a symbol")
    ss.add_argument("symbol")
    ss.add_argument("--tf", "--interval", dest="interval",
                    help="Timeframe, e.g. 5m, 1h, 1D")

    sh = sub.add_parser("screenshot", help="Capture a chart PNG")
    sh.add_argument("symbol", nargs="?",
                    help="Optional symbol to navigate to before capture")
    sh.add_argument("timeframe", nargs="?",
                    help="Optional timeframe, e.g. 1D, 1h, 5m (case-insensitive)")
    sh.add_argument("-o", "--output", type=Path, default=None,
                    help="Output PNG path (default: ~/Desktop/TradingView/...)")
    sh.add_argument("--area", default="chart",
                    choices=sorted(list(_SCREENSHOT_AREAS) + ["full"]),
                    help="Region to capture (default: chart). Use 'full' for "
                         "the entire viewport when chart-only crops hide the "
                         "sidebar / Pine editor / Account Manager you want to see.")

    sub.add_parser("metadata", help="Print current chart metadata")

    sub.add_parser(
        "reconnect",
        help="Detect + dismiss the 'Session disconnected' modal. "
             "This check also runs as a preflight on every other tv "
             "command; use this for explicit debugging.",
    )

    ds = sub.add_parser(
        "describe-screen",
        help="Take a screenshot AND return the inventory of clickable "
             "elements (with rects, centers, and selector hints) — bridges "
             "the screenshot ↔ DOM gap for vision-driven control.",
    )
    ds.add_argument("--area", default="full",
                    choices=sorted(list(_SCREENSHOT_AREAS) + ["full"]),
                    help="Region to capture AND scope the inventory to "
                         "(default: full)")
    ds.add_argument("--include-all", action="store_true",
                    help="Include unaddressable elements too (default: only "
                         "elements with data-name OR aria-label OR id)")
    ds.add_argument("-o", "--output", type=Path, default=None,
                    help="Screenshot path (default: ~/Desktop/TradingView/...)")

    clbl = sub.add_parser(
        "click-label",
        help="Click an element by free-text description (data-name, "
             "aria-label, or visible text — fuzzy match). No coords or "
             "selectors needed.",
    )
    clbl.add_argument("query", help="Description of the element to click "
                                    "(e.g. 'Watchlist', 'Add symbol', 'Pine')")
    clbl.add_argument("--area", default="full",
                      choices=sorted(list(_SCREENSHOT_AREAS) + ["full"]),
                      help="Scope the search to a region (default: full)")
    clbl.add_argument("--bypass-overlap", action="store_true",
                      help="Wrap click in lib.overlays.bypass_overlap_intercept")
    clbl.add_argument("--min-score", type=int, default=25,
                      help="Reject matches below this score (default: 25)")

    cl = sub.add_parser(
        "click-at",
        help="Click at viewport pixel coordinates (selector-free; "
             "combine with screenshot --area full for vision-driven control)",
    )
    cl.add_argument("x", type=int, help="Viewport x (pixels)")
    cl.add_argument("y", type=int, help="Viewport y (pixels)")
    cl.add_argument("--button", choices=("left", "right", "middle"),
                    default="left", help="Mouse button (default: left)")
    cl.add_argument("--double", action="store_true", help="Double-click")
    cl.add_argument("--bypass-overlap", action="store_true",
                    help="Wrap in lib.overlays.bypass_overlap_intercept "
                         "(disables Pine Editor / overlap-manager pointer "
                         "events around the click)")

    sub.add_parser(
        "size",
        help="Report current browser window bounds AND page viewport.",
    )

    rs = sub.add_parser(
        "resize",
        help="Resize the browser window (OS pixels) via CDP. "
             "Affects the whole window — any other tabs move too.",
    )
    rs.add_argument("width", type=int, help="Window width in pixels (>= 400)")
    rs.add_argument("height", type=int, help="Window height in pixels (>= 300)")

    fs = sub.add_parser(
        "fullscreen",
        help="Enter/exit macOS fullscreen via Cmd+Ctrl+F. "
             "macOS only; wrong shortcut on Linux/Windows.",
    )
    fs.add_argument("mode", nargs="?", default="toggle",
                    choices=("on", "off", "toggle"),
                    help="on/off/toggle (default: toggle)")

    args = p.parse_args()

    if args.cmd == "set-symbol":
        run(lambda: set_symbol(args.symbol, args.interval))
    elif args.cmd == "screenshot":
        run(lambda: screenshot(args.symbol, args.timeframe, args.output, area=args.area))
    elif args.cmd == "metadata":
        run(lambda: metadata())
    elif args.cmd == "reconnect":
        run(lambda: reconnect())
    elif args.cmd == "click-at":
        run(lambda: click_at(
            args.x, args.y, button=args.button, double=args.double,
            bypass_overlap=args.bypass_overlap,
        ))
    elif args.cmd == "describe-screen":
        run(lambda: describe_screen(
            area=args.area, include_all=args.include_all,
            output=args.output,
        ))
    elif args.cmd == "click-label":
        run(lambda: click_label(
            args.query, area=args.area,
            bypass_overlap=args.bypass_overlap, min_score=args.min_score,
        ))
    elif args.cmd == "size":
        run(lambda: size())
    elif args.cmd == "resize":
        run(lambda: resize(args.width, args.height))
    elif args.cmd == "fullscreen":
        run(lambda: fullscreen(args.mode))


if __name__ == "__main__":
    _main()
