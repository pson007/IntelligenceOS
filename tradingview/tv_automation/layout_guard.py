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


async def ensure_layout(page: Page) -> dict[str, Any]:
    """First-line invariant for every automation. Returns layout info
    when the active chart is on `EXPECTED_LAYOUT_NAME`; switches to it
    when not (via `layouts.load`); raises if the layout doesn't exist.

    Caller is expected to be inside its own `chart_session` block;
    the inner `layouts.load` call uses a nested session, which is
    safe — Playwright reuses CDP connections."""
    info = await current_layout(page)
    if info.get("name") == EXPECTED_LAYOUT_NAME:
        audit.log("layout_guard.ensure.already_on", **info)
        return info

    audit.log("layout_guard.ensure.switching",
              from_name=info.get("name"),
              to_name=EXPECTED_LAYOUT_NAME)
    try:
        from . import layouts
        result = await layouts.load(EXPECTED_LAYOUT_NAME)
        if not result.get("ok"):
            raise LayoutMismatchError(
                EXPECTED_LAYOUT_NAME, info.get("name"), action="load_failed",
            )
    except Exception as e:
        audit.log("layout_guard.ensure.load_fail", err=str(e))
        raise LayoutMismatchError(
            EXPECTED_LAYOUT_NAME, info.get("name"), action="load_exception",
        ) from e

    # Re-read to confirm. The page object is now pointing at the new
    # layout's URL; query the JS again for the new name.
    await page.wait_for_timeout(1500)
    after = await current_layout(page)
    if after.get("name") != EXPECTED_LAYOUT_NAME:
        raise LayoutMismatchError(
            EXPECTED_LAYOUT_NAME, after.get("name"),
            action="post_switch_mismatch",
        )
    audit.log("layout_guard.ensure.switched", **after)
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
