"""Focus policy — suppress Playwright's tab-activation by default.

Background: `page.bring_to_front()` sends CDP `Target.activateTarget`,
which activates the tab within Chrome — and on macOS Spaces that pulls
Chrome's window out of its background Space and onto whichever Space
the user is currently in. Result: every F1/F2/F3 capture, every Bar
Replay step, every pivot screenshot yanks the focus away from whatever
the user is doing on their laptop.

The good news is `bring_to_front` is almost always defensive, not
required. CDP-based inputs (`Input.dispatchKeyEvent`,
`Input.dispatchMouseEvent`) and CDP-based screenshots
(`Page.captureScreenshot`) do NOT require the tab to be active — they
speak directly to the browser process. The `bring_to_front` calls are
a carry-over from OS-level-keyboard-sim days.

This module neutralizes them at import time by replacing
`Page.bring_to_front` with a no-op — unless the operator explicitly
sets `TV_QUIET=0` in the environment (rare case where a specific flow
genuinely needs the tab active, e.g. debugging by eye).

Import this module EARLY, before any `chart_session()` call — that way
every Page instance Playwright creates already has the patched method.
"""

from __future__ import annotations

import os


_QUIET = os.getenv("TV_QUIET", "1") != "0"


def _install_patch() -> None:
    """Apply the no-op patch to playwright.async_api.Page.bring_to_front.
    Idempotent: safe to call multiple times (module import caching means
    it naturally runs once, but the guard makes re-imports harmless)."""
    if not _QUIET:
        return
    try:
        from playwright.async_api import Page
    except ImportError:
        return
    if getattr(Page.bring_to_front, "_tv_quiet_noop", False):
        return  # already patched

    async def _noop(self):
        return None

    _noop._tv_quiet_noop = True  # type: ignore[attr-defined]
    Page.bring_to_front = _noop  # type: ignore[method-assign]


_install_patch()
