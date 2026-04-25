"""Selector healing CLI — recover when stored selectors drift.

When TradingView ships a UI tweak that breaks `selectors.yaml`, the
historical fix was: re-run the relevant probe, eyeball the snapshot
diff, edit selectors.yaml. This shortens that to one command:

    tv heal alerts_panel.sidebar_icon
        # Tries each candidate from selectors.yaml. If any work, prints
        # "still resolves" + which one. If all fail, runs the healer
        # against current DOM and prints ranked replacement candidates.

    tv heal --selector '[data-name="alerts-typo"]' [--scope <css>]
        # Heal an arbitrary selector — useful for testing the healer or
        # for one-off recovery without a yaml entry.

Output is a JSON report of replacement candidates. We deliberately do
NOT auto-edit selectors.yaml — auto-pollution is the failure mode that
makes this kind of system fragile. Healed selectors are SUGGESTIONS;
human/LLM in the loop applies them with a YAML-snippet paste:

    tv heal alerts_panel.sidebar_icon
    # → top candidate: [data-name="alerts-icon"]
    # paste under alerts_panel.sidebar_icon as a new fallback line.
"""

from __future__ import annotations

import argparse

from playwright.async_api import Page

from .lib import selectors as _selectors
from .lib.cli import run
from .lib.context import chart_session
from .lib.selectors_healer import (
    crosscheck_with_api, extract_hints, find_candidates,
)


# Surface-roles whose semantic value has a JS-API ground truth.
# Used by `heal` to print a `state_check` block alongside DOM
# candidates — distinguishes "selector drifted" from "TV state
# actually changed and our DOM probe is correctly reporting it."
_API_CROSSCHECK_ROLES = {
    "chart.symbol": "symbol",
    "chart.interval": "resolution",
    "chart.timeframe": "resolution",
    "replay.strip": "replay_active",
    "replay.toolbar": "replay_active",
}


async def _try_resolve(page: Page, candidates: list[str]) -> str | None:
    """Return the first candidate selector that currently resolves to a
    visible element, or None if none do."""
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return sel
        except Exception:
            continue
    return None


async def heal(
    surface_role: str | None,
    raw_selector: str | None,
    *,
    scope: str | None = None,
) -> dict:
    """Heal a selector by either:
      - `surface_role` ("alerts_panel.sidebar_icon") → looks up the
        candidates in selectors.yaml, tries them, and runs the healer
        if all fail.
      - `raw_selector` (a CSS string) → skips the yaml lookup, runs the
        healer directly. Useful for testing.
    """
    if not surface_role and not raw_selector:
        raise ValueError("provide either surface_role or --selector")

    candidates: list[str] = []
    if surface_role:
        if "." not in surface_role:
            raise ValueError(
                f"surface_role must be 'surface.name' (got {surface_role!r})"
            )
        surface, name = surface_role.split(".", 1)
        candidates = _selectors.candidates(surface, name)
    if raw_selector:
        candidates = [raw_selector]

    async with chart_session() as (_ctx, page):
        # Step 1: see if the existing selector(s) still work.
        if surface_role:
            working = await _try_resolve(page, candidates)
            if working:
                return {
                    "ok": True, "needed_heal": False,
                    "surface_role": surface_role,
                    "working_selector": working,
                    "candidates_tried": candidates,
                    "message": "Selector still resolves — no heal needed.",
                }

        # Step 2: extract hints from each failed candidate, find
        # replacements. If multiple candidates failed, we union their
        # hints and dedup the resulting candidate elements.
        all_candidates_dom: list[dict] = []
        seen_keys: set[tuple] = set()
        per_failed: list[dict] = []
        for sel in candidates:
            hints = extract_hints(sel)
            if not hints:
                per_failed.append({
                    "failed_selector": sel,
                    "hints": {},
                    "candidates": [],
                    "note": "no extractable hints (no data-name/aria-label/id/text)",
                })
                continue
            cands = await find_candidates(page, hints, scope_selector=scope)
            per_failed.append({
                "failed_selector": sel,
                "hints": hints,
                "candidates": cands,
            })
            # Union into the global list, dedup by suggested_selector.
            for c in cands:
                key = (c.get("suggested_selector"), c["rect"]["x"], c["rect"]["y"])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_candidates_dom.append(c)

        # Re-rank the union by score, keep top 10.
        all_candidates_dom.sort(key=lambda c: c["score"], reverse=True)
        all_candidates_dom = all_candidates_dom[:10]

        # API ground-truth crosscheck — when this surface_role has a
        # corresponding JS-API path, surface what TV's API says vs
        # what the DOM probe was looking for. `verdict=consensus`
        # means the API agrees state changed (selector is the problem);
        # `dom_drift` means API says state is stable but DOM probe
        # missed it (DOM probe reading something stale).
        state_check = None
        if surface_role and surface_role in _API_CROSSCHECK_ROLES:
            api_role = _API_CROSSCHECK_ROLES[surface_role]
            state_check = await crosscheck_with_api(page, api_role, None)

        return {
            "ok": True, "needed_heal": True,
            "surface_role": surface_role,
            "raw_selector": raw_selector,
            "scope": scope,
            "per_failed_selector": per_failed,
            "best_candidates": all_candidates_dom,
            "state_check": state_check,
            "message": (
                f"Top suggestion: {all_candidates_dom[0]['suggested_selector']!r}"
                if all_candidates_dom
                else "No candidates found — re-probe the surface."
            ),
        }


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.heal")
    p.add_argument(
        "surface_role", nargs="?",
        help="surface.role (e.g. alerts_panel.sidebar_icon) — looks up "
             "candidates from selectors.yaml",
    )
    p.add_argument(
        "--selector", dest="raw_selector",
        help="Heal an arbitrary selector instead of looking up by surface.role",
    )
    p.add_argument(
        "--scope",
        help="Optional CSS selector to scope the healer's DOM scan "
             "(e.g. 'div[class*=\"screenerContainer-\"]' for a screener "
             "selector)",
    )

    args = p.parse_args()
    run(lambda: heal(args.surface_role, args.raw_selector, scope=args.scope))


if __name__ == "__main__":
    _main()
