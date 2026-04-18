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
from .lib.guards import assert_logged_in
from .lib.urls import chart_url_for

# Friendly timeframe → TradingView's URL `interval` param.
# TV uses minute counts as strings, plus single letters for D/W/M.
# Lookup is case-insensitive for minute/hour frames ("1h" / "1H" both ok)
# while preserving the canonical casing for D/W/M (TV's URL param is
# uppercase there).
_TIMEFRAME_MAP = {
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
    page = await ctx.new_page()
    await page.goto(CHART_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    await page.wait_for_timeout(1500)
    return page


async def _navigate(page: Page, symbol: str | None, interval: str | None) -> None:
    """Navigate the chart to symbol/interval, PRESERVING any saved-layout
    path segment in the current URL (e.g. `/chart/wqVfOr3Z/`). Without
    this, every symbol change wipes the user's saved indicators/drawings."""
    if not symbol and not interval:
        return
    target = chart_url_for(page.url, symbol, interval)
    await page.goto(target, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    # Slight buffer — quick-trade bar, indicators, legend all hydrate
    # after the canvas paints.
    await page.wait_for_timeout(1500)


async def _extract_metadata(page: Page) -> dict:
    """Read the active chart's symbol + interval from title and DOM.
    Title is authoritative for symbol; interval is pulled from the
    active interval button when the title doesn't include it (common
    with saved layouts)."""
    title = await page.title()
    url = page.url
    symbol = interval = None

    m = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s+([A-Z0-9]+)\s+chart", title)
    if m:
        symbol, interval = m.group(1), m.group(2)
    else:
        m2 = re.match(r"^\s*([A-Z0-9:\._\-!]+)\s", title)
        if m2:
            symbol = m2.group(1)

    if not symbol:
        um = re.search(r"[?&]symbol=([^&]+)", url)
        if um:
            symbol = um.group(1)
    if not interval:
        um = re.search(r"[?&]interval=([^&]+)", url)
        if um:
            interval = um.group(1)

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

        audit.log("chart.screenshot",
                  path=str(output), area=captured_area,
                  fell_back=fell_back, **meta)
        return {
            "path": str(output), "area": captured_area,
            "fell_back": fell_back, **meta,
        }


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


async def metadata() -> dict:
    """Return current chart's symbol, interval, and URL. Read-only."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await assert_logged_in(page)
        return await _extract_metadata(page)


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

    args = p.parse_args()

    if args.cmd == "set-symbol":
        run(lambda: set_symbol(args.symbol, args.interval))
    elif args.cmd == "screenshot":
        run(lambda: screenshot(args.symbol, args.timeframe, args.output, area=args.area))
    elif args.cmd == "metadata":
        run(lambda: metadata())
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


if __name__ == "__main__":
    _main()
