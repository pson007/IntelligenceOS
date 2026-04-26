"""Pin every automation to a single clean TradingView layout.

Pre-existing indicators, drawings, or saved Replay state on the active
chart contaminate every automation downstream — vision LLMs misread a
busy chart, screenshot framing differs by indicator stack height,
Replay state restoration brings back stale cursors. This module makes
"the layout I'm running on" an explicit, asserted invariant rather
than an implicit assumption.

The expected layout is named **"1run Automation"** by default
(override with `AUTOMATION_LAYOUT_NAME` env var). It should contain:
  - one symbol pane (MNQ1! by default)
  - no studies / indicators / drawings
  - no saved Replay state
  - default chart type (candles)

Workflows call `await layout_guard.ensure_layout(page)` as their first
operation inside a `chart_session`. This:
  1. Reads the current layout name from the header toolbar.
  2. If it matches the expected name, returns immediately.
  3. Otherwise, switches via `layouts.load(name)` and re-verifies.
  4. Raises `LayoutMismatchError` if the named layout doesn't exist
     (caller's responsibility to bootstrap it; see CLI below).

CLI bootstrap — run ONCE to create the clean layout:
    cd tradingview && .venv/bin/python -m tv_automation.layout_guard --bootstrap

Stripping indicators uses `chart.removeEntity(study.id())` per study
returned by `chart.getAllStudies()`, then `layouts.save_as` with the
expected name.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from typing import Any

from playwright.async_api import Page

from .lib import audit


EXPECTED_LAYOUT_NAME = os.environ.get(
    "AUTOMATION_LAYOUT_NAME", "1run Automation",
)


_LAYOUT_NAME_JS = r"""() => {
    const btn = document.querySelector('[data-name="save-load-menu"]');
    if (!btn) return {layout_name: null};
    const btnRect = btn.getBoundingClientRect();
    const all = Array.from(document.querySelectorAll('span, div, button'))
        .filter(n => {
            const r = n.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return false;
            if (Math.abs(r.y - btnRect.y) > 20) return false;
            if (r.x >= btnRect.x) return false;
            const t = (n.innerText || '').trim();
            if (!t || t.length < 2 || t.length > 50) return false;
            if (t.includes('\n')) return false;
            if (/^\d+[mhdD]$|^D$|^W$|^M$/.test(t)) return false;
            return r.x > 700;
        });
    if (all.length === 0) return {layout_name: null};
    all.sort((a, b) =>
        b.getBoundingClientRect().x - a.getBoundingClientRect().x);
    return {layout_name: (all[0].innerText || '').trim()};
}"""


class LayoutMismatchError(RuntimeError):
    """Active chart isn't on the expected automation layout."""

    def __init__(self, expected: str, actual: str | None,
                 *, action: str = "manual") -> None:
        self.expected = expected
        self.actual = actual
        self.action = action
        msg = (f"layout_mismatch: expected {expected!r}, "
               f"got {actual!r}; action={action}")
        super().__init__(msg)


async def current_layout(page: Page) -> dict[str, Any]:
    """Read the active layout's name + URL id from `page` directly.
    Doesn't open a new chart_session (so it composes inside existing
    workflow blocks)."""
    try:
        info = await page.evaluate(_LAYOUT_NAME_JS)
    except Exception:
        info = {"layout_name": None}
    name = (info or {}).get("layout_name")
    url = page.url
    layout_id = None
    m = re.search(r"/chart/([^/?]+)", url)
    if m and m.group(1):
        layout_id = m.group(1)
    return {"name": name, "layout_id": layout_id, "url": url}


async def is_correct_layout(page: Page) -> bool:
    """True when the active layout's name matches `EXPECTED_LAYOUT_NAME`."""
    info = await current_layout(page)
    return info.get("name") == EXPECTED_LAYOUT_NAME


async def assert_layout(page: Page) -> dict[str, Any]:
    """Raise `LayoutMismatchError` if the active chart isn't on the
    expected automation layout. Doesn't try to switch — use
    `ensure_layout` for auto-switch behavior."""
    info = await current_layout(page)
    if info.get("name") != EXPECTED_LAYOUT_NAME:
        audit.log("layout_guard.assert.mismatch",
                  expected=EXPECTED_LAYOUT_NAME, **info)
        raise LayoutMismatchError(EXPECTED_LAYOUT_NAME, info.get("name"),
                                   action="assert")
    audit.log("layout_guard.assert.ok", **info)
    return info


def _normalize_layout_name(s: str | None) -> str:
    """Strip leading non-alphanumeric/non-letter chars (emoji prefixes
    like 🟢, 📊, 🕵 the user uses to flag active layouts) and lowercase
    for tolerant comparison. TV's `getSavedCharts` returns the full
    name including emoji, but the toolbar's `.innerText` reader returns
    only the text portion — emojis render as glyphs that don't show up
    in innerText. Comparing normalized forms keeps both sources alike."""
    if not s:
        return ""
    return re.sub(r"^[^A-Za-z0-9]+", "", s).strip().lower()


async def _load_layout_via_api(page: Page, name: str) -> dict | None:
    """Switch to a saved layout by name. Looks up the layout's chart-id
    via `getSavedCharts` (emoji-safe — matches against TV's own data,
    not a typed-into-DOM search box) then dispatches
    `loadChartFromServer(id)`. Confirmed to navigate the SPA in
    practice — caller's `ensure_layout` polls `current_layout()` for
    the toolbar-name confirmation (with normalized comparison since
    the toolbar drops emoji glyphs).

    Returns the lookup dict {`ok`, `id`, `url_slug`, `match_name`} on
    success, or None on lookup failure."""
    lookup = await page.evaluate(r"""(target) => new Promise((resolve) => {
        try {
            window.TradingViewApi.getSavedCharts((charts) => {
                if (!charts || !Array.isArray(charts)) {
                    resolve({ok: false, reason: 'getSavedCharts returned no data'});
                    return;
                }
                const exact = charts.find(c => (c.name || c.title || '') === target);
                const norm = (s) => (s || '').replace(/^[^A-Za-z0-9]+/, '').trim().toLowerCase();
                const targetNorm = norm(target);
                const fuzzy = exact || charts.find(c => norm(c.name || c.title) === targetNorm);
                const sub = fuzzy || charts.find(c =>
                    (c.name || c.title || '').toLowerCase().includes(target.toLowerCase())
                );
                if (!sub) {
                    resolve({ok: false, reason: 'no name match', available: charts.length});
                    return;
                }
                resolve({
                    ok: true,
                    id: sub.id || sub.chartId,
                    url_slug: sub.url || null,
                    match_name: sub.name || sub.title,
                });
            });
            setTimeout(() => resolve({ok: false, reason: 'getSavedCharts timeout'}), 5000);
        } catch (e) {
            resolve({ok: false, reason: 'exception: ' + e.message});
        }
    })""", name)

    if not lookup or not lookup.get("ok"):
        audit.log("layout_guard.api_load.fail",
                  expected=name, **(lookup or {}))
        return None

    slug = lookup.get("url_slug")
    if not slug:
        audit.log("layout_guard.api_load.no_slug",
                  expected=name, match=lookup.get("match_name"))
        return None

    # Direct navigation to the chart URL is more reliable than the
    # `loadChartFromServer` SPA path — that one was observed to silently
    # no-op going Profile → Automation (2026-04-26) even though the
    # reverse worked. `page.goto` bypasses TV's internal SPA router
    # and always re-loads the chart fresh.
    #
    # Install a permissive dialog handler in case TV throws a
    # beforeunload prompt (rare on /chart/ URLs but cheap). The
    # handler auto-accepts so we don't hang on a stale prompt.
    async def _accept_dialog(d):
        try: await d.accept()
        except Exception: pass

    page.on("dialog", _accept_dialog)
    try:
        target_url = f"https://www.tradingview.com/chart/{slug}/"
        await page.goto(target_url, wait_until="domcontentloaded",
                        timeout=20_000)
    except Exception as e:
        audit.log("layout_guard.api_load.nav_fail",
                  expected=name, err=str(e))
        try: page.remove_listener("dialog", _accept_dialog)
        except Exception: pass
        return None
    finally:
        try: page.remove_listener("dialog", _accept_dialog)
        except Exception: pass

    audit.log("layout_guard.api_load.dispatched",
              expected=name, match=lookup.get("match_name"),
              id=lookup.get("id"), slug=slug)
    return lookup


async def ensure_layout(page: Page,
                        layout_name: str | None = None) -> dict[str, Any]:
    """First-line invariant for every automation. Returns layout info
    when the active chart is on the expected layout; switches to it
    when not (via `layouts.load`); raises if the layout doesn't exist.

    `layout_name` defaults to `EXPECTED_LAYOUT_NAME` ("1run Automation"
    or whatever `AUTOMATION_LAYOUT_NAME` env var sets). Pass an explicit
    name to enforce a workflow-specific layout — `daily_profile` passes
    "1run Profile" because the profile capture needs a different study
    stack than the generic automation layout.

    Caller is expected to be inside its own `chart_session` block;
    the inner `layouts.load` call uses a nested session, which is
    safe — Playwright reuses CDP connections."""
    expected = layout_name or EXPECTED_LAYOUT_NAME
    expected_norm = _normalize_layout_name(expected)
    info = await current_layout(page)
    if _normalize_layout_name(info.get("name")) == expected_norm:
        audit.log("layout_guard.ensure.already_on",
                  expected=expected, **info)
        return info

    audit.log("layout_guard.ensure.switching",
              from_name=info.get("name"),
              to_name=expected)
    # Prefer the JS-API loader: emoji-safe, doesn't depend on the DOM
    # picker's search-box behavior, no opening/closing of the menu.
    # Falls back to the DOM-based `layouts.load` only if the API path
    # didn't dispatch — covers older TV builds where the API is missing.
    api_result = await _load_layout_via_api(page, expected)
    if api_result is None:
        try:
            from . import layouts
            result = await layouts.load(expected)
            if not result.get("ok"):
                raise LayoutMismatchError(
                    expected, info.get("name"), action="load_failed",
                )
        except Exception as e:
            audit.log("layout_guard.ensure.load_fail",
                      err=str(e), expected=expected)
            raise LayoutMismatchError(
                expected, info.get("name"), action="load_exception",
            ) from e

    # Re-read to confirm. The chart re-renders asynchronously after
    # `loadChartFromServer` — toolbar name + URL update at different
    # rates depending on study count and TV's React reconciliation.
    # Accept either signal: URL slug match (deterministic — TV puts
    # the chart-id slug in the path) OR normalized toolbar name match
    # (handles cases where URL stays the same on certain transitions).
    expected_slug = (api_result or {}).get("url_slug") if api_result else None
    after: dict[str, Any] = {"name": None, "layout_id": None}
    for _ in range(40):
        await page.wait_for_timeout(200)
        after = await current_layout(page)
        url_match = (expected_slug
                     and after.get("layout_id") == expected_slug)
        name_match = (_normalize_layout_name(after.get("name"))
                      == expected_norm)
        if url_match or name_match:
            break
    final_url_match = (expected_slug
                       and after.get("layout_id") == expected_slug)
    final_name_match = (_normalize_layout_name(after.get("name"))
                        == expected_norm)
    if not (final_url_match or final_name_match):
        raise LayoutMismatchError(
            expected, after.get("name"),
            action="post_switch_mismatch",
        )
    audit.log("layout_guard.ensure.switched",
              expected=expected,
              matched_via="url_slug" if final_url_match else "name",
              **after)
    return after


async def strip_all_indicators(page: Page) -> int:
    """Remove every study from the active chart. Returns the count
    removed. Used by the bootstrap CLI to produce a clean layout."""
    count = await page.evaluate(r"""() => {
        try {
            const c = window.TradingViewApi._activeChartWidgetWV.value();
            if (!c) return 0;
            const studies = c.getAllStudies();
            let n = 0;
            for (const s of studies) {
                try {
                    const id = s.id;
                    if (id !== undefined && c.removeEntity) {
                        c.removeEntity(id);
                        n++;
                    }
                } catch (e) {}
            }
            return n;
        } catch (e) { return -1; }
    }""")
    audit.log("layout_guard.strip_indicators", removed=count)
    return int(count) if count and count > 0 else 0


# ---------------------------------------------------------------------------
# Bootstrap CLI — run once to create the clean layout.
# ---------------------------------------------------------------------------


async def bootstrap() -> dict[str, Any]:
    """Create the clean automation layout. Strips all indicators from
    a fresh chart, sets symbol=MNQ1! 1m, then saves as the expected
    name. Idempotent — re-runs are safe (existing layout overwritten
    via save-as semantics)."""
    from .lib.context import chart_session
    from . import layouts, replay_api

    async with chart_session() as (_ctx, page):
        # Read current state for the report.
        before = await current_layout(page)
        print(f"current layout: {before.get('name')!r} "
              f"({before.get('layout_id')})")

        # Strip all indicators in-place.
        removed = await strip_all_indicators(page)
        print(f"removed {removed} indicator(s)")

        # Pin symbol + TF to MNQ1! 1m via the JS API.
        landed = await replay_api.set_symbol_in_place(
            page, symbol="MNQ1!", interval="1",
        )
        if landed:
            print(f"set symbol/TF: {landed['symbol']} @ {landed['resolution']}")
        await page.wait_for_timeout(1500)

        # Save as the expected name.
        save_result = await layouts.save_as(EXPECTED_LAYOUT_NAME)
        print(f"save_as: {save_result}")

        after = await current_layout(page)
        print(f"new layout: {after.get('name')!r} ({after.get('layout_id')})")
        return {
            "before": before, "after": after, "removed": removed,
            "save_result": save_result,
        }


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.layout_guard")
    p.add_argument("--bootstrap", action="store_true",
                   help="Create the clean automation layout (run once)")
    p.add_argument("--check", action="store_true",
                   help="Print the current layout and whether it matches")
    args = p.parse_args()

    if args.bootstrap:
        result = asyncio.run(bootstrap())
        import json
        print(json.dumps(result, indent=2))
    elif args.check:
        async def _check() -> None:
            from .lib.context import chart_session
            async with chart_session() as (_ctx, page):
                info = await current_layout(page)
                ok = info.get("name") == EXPECTED_LAYOUT_NAME
                print(f"current: {info.get('name')!r}")
                print(f"expected: {EXPECTED_LAYOUT_NAME!r}")
                print(f"match: {ok}")
        asyncio.run(_check())
    else:
        p.print_help()


if __name__ == "__main__":
    _main()
