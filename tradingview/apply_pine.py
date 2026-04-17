"""
Paste a Pine Script into TradingView's Pine Editor, save it, and add to chart.

Flow:
  1. Preflight → attach to automation Chromium.
  2. Find the chart tab (open one if none).
  3. Open the Pine Editor panel (bottom).
  4. Copy the Pine code to the macOS clipboard (pbcopy) so we can paste
     it atomically instead of typing char-by-char (Monaco is slow to
     handle keyboard typing on files > a few hundred chars).
  5. Focus the editor, select-all, paste, save (⌘S) — TV asks for a
     script name on first save; we pre-fill the indicator's title.
  6. Click "Add to chart".

Usage:
    .venv/bin/python apply_pine.py                       # latest .pine in pine/generated/
    .venv/bin/python apply_pine.py path/to/indicator.pine
    .venv/bin/python apply_pine.py --name "My Indicator" path/to/file.pine
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeoutError

from preflight import ensure_automation_chromium
from session import is_logged_in, tv_context

GENERATED_DIR = Path(__file__).parent / "pine" / "generated"
CHART_URL = "https://www.tradingview.com/chart/"

# ---- Selectors ----------------------------------------------------------
# Pine Editor opener — icon in the bottom-right sidebar (aria-label "Pine").
# Clicking it expands the bottom panel with Pine Editor focused.
SEL_PINE_TAB_CANDIDATES = [
    '[data-name="pine-dialog-button"]',
]

# Monaco editor inside the Pine panel. TradingView gives it its own
# class (`pine-editor-monaco`) which is more specific than the generic
# `.monaco-editor` that backtesting / strategy tester also use.
SEL_MONACO = ".pine-editor-monaco"
# Monaco puts its input target in a textarea-shaped div-with-contenteditable
# on recent builds, but there's still a real <textarea> for screen-readers.
SEL_MONACO_TEXTAREA = ".pine-editor-monaco textarea"

# Save button — TV uses hashed module classes with a stable prefix.
SEL_SAVE_BUTTON_CANDIDATES = [
    'button[class*="saveButton-"]',
]

# "Add to chart" button — stable via the accessible `title` attribute
# (TV uses `title` for the tooltip on this icon-only button).
SEL_ADD_TO_CHART_CANDIDATES = [
    'button[title="Add to chart"]',
]


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def pbcopy(text: str) -> None:
    """Copy text to the macOS clipboard via pbcopy."""
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def extract_indicator_title(pine: str) -> str | None:
    """Read the title string out of `indicator("...", ...)`.
    Used to pre-fill the Save-as dialog."""
    m = re.search(r'indicator\s*\(\s*"([^"]+)"', pine)
    return m.group(1) if m else None


async def first_visible(page: Page, selectors: list[str], timeout: int = 5000):
    """Return the first visible locator that matches any of `selectors`."""
    # Simple polling loop — Playwright's racing API is finicky across versions.
    for _ in range(timeout // 250):
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue
        await page.wait_for_timeout(250)
    raise PWTimeoutError(
        f"None of these became visible within {timeout}ms: {selectors}"
    )


async def find_chart_page(ctx):
    for p in ctx.pages:
        if "tradingview.com/chart" in p.url:
            await p.bring_to_front()
            return p
    page = await ctx.new_page()
    await page.goto(CHART_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("canvas", state="visible", timeout=30_000)
    await page.wait_for_timeout(1500)
    return page


async def open_pine_editor(page: Page) -> None:
    """Ensure the Pine Editor panel is open and focused."""
    # If the Monaco editor is already visible, we're done.
    if await page.locator(SEL_MONACO).first.count() > 0:
        if await page.locator(SEL_MONACO).first.is_visible():
            return

    tab = await first_visible(page, SEL_PINE_TAB_CANDIDATES, timeout=5000)
    await tab.click()
    await page.wait_for_selector(SEL_MONACO, state="visible", timeout=10_000)
    await page.wait_for_timeout(600)


async def replace_editor_content(page: Page, pine: str) -> None:
    """Put `pine` on the clipboard, focus the editor, select-all, paste."""
    pbcopy(pine)

    # Click inside the Monaco editor to give it focus. Using the textarea
    # is more reliable than clicking the container because Monaco's
    # container has a bunch of child overlays.
    ta = page.locator(SEL_MONACO_TEXTAREA).first
    await ta.wait_for(state="attached", timeout=5000)
    await ta.click(force=True)
    await page.wait_for_timeout(150)

    # Select all existing content, then paste.
    await page.keyboard.press("ControlOrMeta+a")
    await page.wait_for_timeout(80)
    await page.keyboard.press("ControlOrMeta+v")
    await page.wait_for_timeout(600)


async def save_and_add_to_chart(page: Page, script_name: str | None) -> None:
    """Click Save in the editor toolbar; if a Save-As dialog appears,
    fill the name; then click Add to chart (which also compiles)."""
    # Click the save button in the editor toolbar.
    try:
        save_btn = await first_visible(page, SEL_SAVE_BUTTON_CANDIDATES, timeout=3000)
        await save_btn.click()
        await page.wait_for_timeout(900)
    except PWTimeoutError:
        # Fallback to keyboard shortcut.
        await page.keyboard.press("ControlOrMeta+s")
        await page.wait_for_timeout(900)

    # If TV opened a "Save Script" dialog (first save of a new untitled
    # script), it focuses a text input. Pre-fill the name from the
    # `indicator()` title.
    focused_tag = await page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    if focused_tag == "INPUT" and script_name:
        await page.keyboard.press("ControlOrMeta+a")
        await page.keyboard.type(script_name)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1500)

    # Click "Add to chart". If the script is already on chart, TV hides the
    # button (save alone re-compiles and refreshes the in-place instance).
    # So a missing button is a success signal, not a failure.
    try:
        btn = await first_visible(page, SEL_ADD_TO_CHART_CANDIDATES, timeout=3000)
        await btn.click()
        await page.wait_for_timeout(1500)
        print("Added indicator to chart.", flush=True)
    except PWTimeoutError:
        # Verify by reading the chart's indicator legend — if the new
        # indicator name appears, the save implicitly refreshed it.
        name_re = re.escape(extract_indicator_title(await page.evaluate(
            "() => document.querySelector('.pine-editor-monaco')?.innerText || ''"
        )) or "")
        if name_re:
            legend_text = await page.evaluate("""() =>
              Array.from(document.querySelectorAll(
                '[data-name="legend-source-title"], [class*="legendMainSourceWrapper"]'
              )).map(e => e.innerText).join(' | ')""")
            if name_re and re.search(name_re, legend_text, re.I):
                print("Indicator already on chart — save refreshed it in place.",
                      flush=True)
                return
        print(
            "NOTE: 'Add to chart' button not found and the indicator name "
            "was not detected in the chart legend. Check TradingView manually.",
            flush=True,
        )


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def resolve_pine_path(arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(p)
        return p
    # Default: newest .pine in pine/generated/
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted(GENERATED_DIR.glob("*.pine"),
                        key=lambda x: x.stat().st_mtime,
                        reverse=True)
    if not candidates:
        raise FileNotFoundError(
            f"No .pine files found in {GENERATED_DIR}. "
            "Generate one first (e.g. via capture_chart.py + analysis)."
        )
    return candidates[0]


async def main() -> int:
    ap = argparse.ArgumentParser(description="Apply Pine code to TradingView.")
    ap.add_argument("path", nargs="?", help="Path to .pine file")
    ap.add_argument("--name",
                    help="Script name for first-time Save-as "
                         "(default: parsed from indicator() title)")
    args = ap.parse_args()

    pine_path = resolve_pine_path(args.path)
    pine = pine_path.read_text()
    name = args.name or extract_indicator_title(pine) or pine_path.stem
    print(f"File:  {pine_path}", flush=True)
    print(f"Name:  {name}", flush=True)
    print(f"Size:  {len(pine)} chars", flush=True)

    await ensure_automation_chromium()

    async with tv_context(headless=False) as ctx:
        page = await find_chart_page(ctx)

        if not await is_logged_in(page):
            print("ERROR: not signed in to TradingView.", flush=True)
            return 1

        print("Opening Pine Editor...", flush=True)
        await open_pine_editor(page)

        print("Replacing editor contents...", flush=True)
        await replace_editor_content(page, pine)

        print("Saving + adding to chart...", flush=True)
        await save_and_add_to_chart(page, name)

        await page.screenshot(path="/tmp/tv_pine_applied.png")
        print("Screenshot → /tmp/tv_pine_applied.png", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
