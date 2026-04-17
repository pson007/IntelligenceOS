"""
Create a new TradingView chart layout with a given name.

Opens the layouts menu (top-right gear icon, data-name="save-load-menu"),
clicks "Create new layout", then renames the resulting layout via the
"Rename..." menu item.

Usage:
    .venv/bin/python create_layout.py [NAME]

If NAME is omitted, a random OC<nnn> name is generated.
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

from playwright.async_api import TimeoutError as PWTimeoutError

from preflight import ensure_automation_chromium
from session import tv_context, is_logged_in, open_chart, CDP_URL

CHART_URL = "https://www.tradingview.com/chart/"

SEL_LAYOUT_MENU = '[data-name="save-load-menu"]'


def generate_name() -> str:
    return f"OC{random.randint(100, 999)}"


async def open_layout_menu(page) -> None:
    """Open the Manage Layouts dropdown."""
    await page.locator(SEL_LAYOUT_MENU).first.click(timeout=5000)
    await page.wait_for_timeout(500)


async def list_layouts(page) -> list[str]:
    """Return the names of layouts shown under 'RECENTLY USED'.

    Reads from the already-open layouts menu. TV populates the recent-list
    asynchronously after the popup paints, so we poll briefly until at
    least one layout row appears (or the 'RECENTLY USED' header is present
    but the list genuinely empty, which we only see on a fresh account).

    Note: 'RECENTLY USED' is bounded — only the ~8 most recently opened
    layouts show. Older ones live in the full picker reached via the
    'Open layout…' dialog, which we don't query here.
    """
    js = """() => {
      const popups = document.querySelectorAll('[class*="menuBox-"]');
      const popup = popups[popups.length - 1];
      if (!popup) return null;
      // Layout rows are the ones whose ellipsis class hash differs from
      // the shared command class (ellipsis-Uy_he976 is used for 'Save
      // layout', 'Rename…', etc.).
      const rows = Array.from(popup.querySelectorAll('[class*="ellipsis-"]'))
        .map(e => ({t: (e.innerText || '').trim(), c: e.className}))
        .filter(x => x.t && !x.c.includes('Uy_he976'))
        .map(x => x.t);
      // Signal to Python whether we at least saw the popup structure.
      const sawHeader = popup.innerText && popup.innerText.includes('RECENTLY USED');
      return {rows, sawHeader};
    }"""
    # Poll up to 3s: the popup's layout list hydrates asynchronously.
    for _ in range(15):
        res = await page.evaluate(js)
        if res is None:
            await page.wait_for_timeout(200)
            continue
        if res["rows"] or res["sawHeader"]:
            return res["rows"]
        await page.wait_for_timeout(200)
    return []


async def click_menu_item(page, text: str) -> None:
    """Click a dropdown item by its exact visible text.

    TradingView's menus use ``<div>`` items with no stable data-name, so
    we match by text. Note: menu labels use the Unicode ellipsis U+2026
    (``…``), not three ASCII dots — pass the exact character.
    """
    # Scope to the open popup container so we don't click a same-text
    # element elsewhere on the page. TradingView's popup class is
    # 'menuBox-...' with a hash suffix that rotates; match the prefix.
    popup = page.locator('[class*="menuBox-"]').last
    item = popup.get_by_text(text, exact=True).first
    if await item.count() == 0:
        # Fallback: any visible element with that exact text.
        item = page.get_by_text(text, exact=True).first
    await item.click(timeout=5000)
    await page.wait_for_timeout(500)


async def save_layout_with_name(page, new_name: str) -> None:
    """Rename the just-created layout.

    "Create new layout…" auto-creates AND auto-saves a layout with a
    default name (something like "New chart"). That means:
      * "Save layout" is disabled (nothing dirty to save).
      * "Rename…" IS enabled — it's the correct path for renaming a
        clean, freshly-created layout.

    Flow:
      1. Open the layouts menu.
      2. Click "Rename…" — opens a small dialog with a text input
         pre-populated with the current name.
      3. Select-all, type the new name, press Enter.
    """
    await open_layout_menu(page)
    # Menu labels use U+2026 Unicode ellipsis, not three ASCII dots.
    await click_menu_item(page, "Rename\u2026")
    await page.wait_for_timeout(800)

    # The rename dialog focuses a text input with the current name selected.
    focused_tag = await page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    print(f"  After 'Rename…' click, focused element: {focused_tag}", flush=True)

    if focused_tag == "INPUT":
        await page.keyboard.press("ControlOrMeta+a")
        await page.keyboard.type(new_name)
    else:
        # Fallback: find the dialog's text input directly.
        loc = page.locator(
            'div[class*="dialog"] input[type="text"], '
            'div[class*="Dialog"] input[type="text"], '
            'input[data-name="name-input"]'
        ).first
        await loc.wait_for(state="visible", timeout=5000)
        await loc.fill(new_name)

    await page.keyboard.press("Enter")
    await page.wait_for_timeout(1500)


async def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else generate_name()
    print(f"Target layout name: {name}", flush=True)

    # Self-heal: start automation Chromium if it's not already running,
    # and block on sign-in if the sessionid cookie is missing. No-op in
    # launch mode (when TV_CDP_URL is unset).
    await ensure_automation_chromium()

    # In attach mode (TV_CDP_URL set) we drive the automation Chromium and
    # reuse any existing TradingView tab. In launch mode we spin up our own
    # visible Chromium against the persistent profile.
    async with tv_context(headless=False) as ctx:
        page = await open_chart(ctx)

        if not await is_logged_in(page):
            if CDP_URL:
                print(
                    "ERROR: attached to Chrome, but no TradingView session "
                    "cookie. Sign in to TradingView in that Chrome window, "
                    "then re-run.",
                    flush=True,
                )
            else:
                print("ERROR: not logged in. Run login.py first.", flush=True)
            return 1

        # Snapshot the existing layouts BEFORE creation so we can prove
        # the new one is a genuinely new entry (not a rename of any existing).
        await open_layout_menu(page)
        layouts_before = await list_layouts(page)
        print(f"Layouts before: {len(layouts_before)} — {layouts_before}", flush=True)
        if name in layouts_before:
            print(
                f"ERROR: a layout named {name!r} already exists. "
                f"Pick a different name (or rename/delete the existing one).",
                flush=True,
            )
            return 4
        # Close the menu before the next action (clicking elsewhere).
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)

        # Step 1: Create a new (blank) layout.
        # Menu labels use Unicode ellipsis U+2026 — "Create new layout…"
        # NOT "Create new layout...".
        print("Opening layout menu...", flush=True)
        await open_layout_menu(page)
        print("Clicking 'Create new layout…'...", flush=True)
        try:
            await click_menu_item(page, "Create new layout\u2026")
        except PWTimeoutError:
            print("ERROR: 'Create new layout…' menu item not found.", flush=True)
            await page.screenshot(path="/tmp/tv_layout_menu.png")
            return 2

        # After creating, TradingView reloads the chart into the new layout.
        # Wait for the canvas to re-paint.
        await page.wait_for_timeout(2500)
        await page.wait_for_selector("canvas", state="visible", timeout=15_000)

        # Dismiss the welcome-video overlay that TradingView shows on new
        # layouts. Its header element (class contains "isShowVideo") covers
        # the top-right toolbar including the save-load-menu button. The
        # overlay has a close button — click it, or press Escape.
        video_overlay = page.locator('[class*="isShowVideo"]').first
        if await video_overlay.count() > 0:
            print("Dismissing welcome-video overlay...", flush=True)
            # Try Escape first (cheapest).
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(600)
            # If still there, look for a close-button inside it.
            if await video_overlay.count() > 0 and await video_overlay.is_visible():
                close_btn = page.locator(
                    '[class*="isShowVideo"] button, '
                    '[class*="isShowVideo"] [role="button"], '
                    '[class*="isShowVideo"] [class*="close"]'
                ).first
                if await close_btn.count() > 0:
                    await close_btn.click(force=True, timeout=2000)
                    await page.wait_for_timeout(500)

        # Step 2: Save the new (unsaved) layout with the target name.
        print(f"Saving layout as {name!r}...", flush=True)
        try:
            await save_layout_with_name(page, name)
        except PWTimeoutError as e:
            print(f"ERROR: save flow failed — {e}", flush=True)
            await page.screenshot(path="/tmp/tv_layout_save.png")
            return 3

        await page.wait_for_timeout(1500)
        await page.screenshot(path="/tmp/tv_layout_created.png")
        print(f"Screenshot → /tmp/tv_layout_created.png", flush=True)

        # Verify: the new name must appear in the layouts list, and it
        # must not have been there before. That's the proof we created
        # rather than renamed. (We can't rely on count deltas because TV's
        # 'RECENTLY USED' is capped at ~8 and bumps older entries off.)
        await open_layout_menu(page)
        layouts_after = await list_layouts(page)
        await page.keyboard.press("Escape")
        print(f"Layouts after:  {layouts_after}", flush=True)
        if name not in layouts_after:
            print(
                f"ERROR: {name!r} not found in layouts list after creation.",
                flush=True,
            )
            return 5
        if name in layouts_before:
            print(
                f"ERROR: {name!r} was already in the list before — this "
                f"wasn't a brand-new creation.",
                flush=True,
            )
            return 6
        print(
            f"Verified: {name!r} is a brand-new layout entry "
            f"(not present before, present after).",
            flush=True,
        )
        print(f"\nDone. Created layout: {name}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
