"""Selector registry — loads selectors.yaml and resolves named roles.

Every selector lookup goes through here. No module writes raw CSS
selectors inline; instead they call `first_visible(page, "trading_panel",
"quick_trade_buy")`. When a selector drifts, you update selectors.yaml
(usually via a probe script) and every caller picks up the fix.

Load is cached — the YAML is read once per process.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import Locator, Page

from .errors import SelectorDriftError

_YAML_PATH = Path(__file__).resolve().parent.parent / "selectors.yaml"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, list[str]]]:
    return yaml.safe_load(_YAML_PATH.read_text()) or {}


def candidates(surface: str, name: str) -> list[str]:
    """Return the ordered list of selector candidates for a role.
    Raises KeyError if the role isn't registered — treat that as a
    programmer error, not runtime drift."""
    data = _load()
    if surface not in data:
        raise KeyError(f"Unknown surface {surface!r} in selectors.yaml")
    if name not in data[surface]:
        raise KeyError(f"Unknown role {surface}.{name!r} in selectors.yaml")
    sels = data[surface][name]
    if not isinstance(sels, list) or not sels:
        raise KeyError(f"{surface}.{name} must be a non-empty list")
    return sels


async def first_visible(
    page: Page, surface: str, name: str, *, timeout_ms: int = 5000,
) -> Locator:
    """Return the first visible locator matching any candidate for this role.

    Polls each candidate in order, every 250ms, until one is visible or
    the timeout expires. A drift (no candidate became visible) raises
    SelectorDriftError so callers can fail loudly rather than silently
    clicking nothing.

    Why polling instead of Playwright's native `wait_for`: we want to try
    multiple selectors in order, returning on the FIRST match. Playwright
    can race on a single locator but not a list; this is simpler than
    building that orchestration manually.
    """
    sels = candidates(surface, name)
    step_ms = 250
    iterations = max(1, timeout_ms // step_ms)
    for _ in range(iterations):
        for sel in sels:
            loc = page.locator(sel).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                # Element is navigating/closing — try the next candidate.
                continue
        await asyncio.sleep(step_ms / 1000)
    raise SelectorDriftError(name, surface, sels)


async def first_present(
    page: Page, surface: str, name: str, *, timeout_ms: int = 5000,
) -> Locator:
    """Like first_visible but only requires the element to exist in the
    DOM (not necessarily visible). Use for elements inside panels that
    may be collapsed but still present."""
    sels = candidates(surface, name)
    step_ms = 250
    iterations = max(1, timeout_ms // step_ms)
    for _ in range(iterations):
        for sel in sels:
            loc = page.locator(sel).first
            try:
                if await loc.count() > 0:
                    return loc
            except Exception:
                continue
        await asyncio.sleep(step_ms / 1000)
    raise SelectorDriftError(name, surface, sels)


async def any_visible(page: Page, surface: str, name: str) -> bool:
    """True if any candidate is currently visible. Non-blocking probe
    — use for presence checks that shouldn't wait (e.g. 'is the broker
    picker dialog up right now?')."""
    for sel in candidates(surface, name):
        loc = page.locator(sel).first
        try:
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    return False
