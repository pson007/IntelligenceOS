"""Named TradingView keyboard shortcuts.

Keyboard shortcuts frequently survive UI redesigns better than DOM
selectors — they go through the same command dispatcher the UI does,
but bypass hash-rotated class names. Prefer keyboard over click when
both paths exist.

These are for the English TV layout with default bindings. If the user
has customized shortcuts or uses a different language, some may miss —
but the curated ones below (core drawing / panel toggles) are stable
across layouts per TradingView docs.
"""

from __future__ import annotations

from playwright.async_api import Page

# Drawing tools
TREND_LINE = "Alt+T"
HORIZONTAL_LINE = "Alt+H"
VERTICAL_LINE = "Alt+V"
FIB_RETRACEMENT = "Alt+F"
RECTANGLE = "Alt+R"

# Panels
INDICATORS_DIALOG = "/"  # quick search
HIDE_ALL_DRAWINGS = "Alt+D"
REMOVE_ALL_INDICATORS = "Ctrl+Alt+N"

# Chart type
CANDLES = "Alt+2"
HEIKIN_ASHI = "Alt+6"
BARS = "Alt+1"
LINE = "Alt+3"

# Navigation
RESET_CHART = "Ctrl+R"


async def press(page: Page, shortcut: str) -> None:
    """Press a TradingView keyboard shortcut.

    Playwright's `keyboard.press` accepts the `Ctrl+...` / `Alt+...`
    notation and translates Ctrl→Meta on macOS where TV expects it for
    most bindings. We normalize explicitly with `ControlOrMeta` for
    clarity on cross-platform shortcuts.
    """
    normalized = shortcut.replace("Ctrl+", "ControlOrMeta+")
    await page.keyboard.press(normalized)
