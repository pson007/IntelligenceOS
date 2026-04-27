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
  7. Collapse the Pine Editor panel so the trader sees the full chart
     with the new indicator applied.

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
from tv_automation import health, layout_guard, pine_compile, replay_api

GENERATED_DIR = Path(__file__).parent / "pine" / "generated"
PARSE_FAIL_DIR = Path(__file__).parent / "pine" / "parse_failures"
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
#
# When a script with the same title is ALREADY on the chart, TV swaps
# the label to "Update on chart" (verified 2026-04-20). Both variants
# do the same thing: compile the current editor contents and apply
# to the chart. Either button present = success path.
SEL_ADD_TO_CHART_CANDIDATES = [
    'button[title="Add to chart"]',
    'button[title="Update on chart"]',
]

# Closing the Pine Editor has two different affordances depending on
# where the user has it docked — discovered live on 2026-04-19:
#
#   1. Side-docked (right panel): an X button with aria-label="Close"
#      sits in the panel's outer chrome, *above* .pine-editor-monaco.
#      It's not a descendant of .tv-script-widget, so we have to walk
#      up the DOM from Monaco until we hit an ancestor that contains it.
#   2. Bottom-docked (widget bar): a chevron with aria-label="Collapse
#      panel" and data-name="toggle-visibility-button" collapses the
#      whole widget bar. The label flips to "Expand panel" when closed,
#      which is our built-in guard against re-expanding.
SEL_COLLAPSE_PANEL_CANDIDATES = [
    'button[aria-label="Collapse panel"]',
    '[data-name="toggle-visibility-button"][aria-label="Collapse panel"]',
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
    """Locate (or open) a TradingView chart tab.

    First tries CDP `/json/list` for stable target identification when
    multiple chart tabs are open — `chart_targets()` returns each tab's
    `chart_id` (parsed from the URL path), letting us pick deterministically
    instead of grabbing whichever Playwright iterated to first."""
    from tv_automation import tabs as tv_tabs
    targets = await tv_tabs.chart_targets()
    target_url = targets[0]["url"] if targets else None

    for p in ctx.pages:
        if "tradingview.com/chart" in p.url:
            if target_url and p.url != target_url:
                continue  # prefer the CDP-discovered first chart
            await p.bring_to_front()
            return p

    # No matching tab attached to this Playwright context — fall back
    # to opening fresh.
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
    """Put `pine` on the clipboard, focus the editor, select-all, paste.

    Why the focus dance (and not just `ta.click(force=True)`):
    if a drawing tool (Text, Trend Line, etc.) is the active tool on
    the chart when apply fires, its pointer-capturing overlay eats
    clicks on the Pine Editor area. `force=True` bypasses actionability
    checks, so the DOM click event dispatches — but keyboard focus
    never moves to the textarea. The subsequent Cmd+V then paints the
    whole Pine source into a *new text annotation on the chart*.

    Guards: (1) Escape twice to drop any active drawing tool +
    dismiss a draft annotation, (2) focus Monaco's textarea via JS
    (bypasses pointer capture — focus is decoupled from the mouse
    pipeline), (3) verify document.activeElement actually landed
    inside .pine-editor-monaco before issuing the paste."""
    pbcopy(pine)

    # Drop any active drawing tool / close a draft annotation so the
    # chart canvas stops capturing pointer events. Two Escapes covers
    # "open annotation" and "armed tool" in either order.
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(60)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(100)

    ta = page.locator(SEL_MONACO_TEXTAREA).first
    await ta.wait_for(state="attached", timeout=5000)

    # Focus via element.focus() first — immune to any pointer-event
    # interception the chart's tool layer might still be doing.
    focused_ok = await page.evaluate("""() => {
      const ta = document.querySelector('.pine-editor-monaco textarea');
      if (!ta) return false;
      ta.focus();
      const a = document.activeElement;
      return !!(a && a.closest && a.closest('.pine-editor-monaco'));
    }""")
    if not focused_ok:
        # Fallback: force-click, then re-verify. If focus STILL didn't
        # land in Monaco, refuse to paste — a silent mis-paste corrupts
        # the chart (Pine source as a text annotation), which is worse
        # than a loud failure.
        await ta.click(force=True)
        await page.wait_for_timeout(150)
        inside = await page.evaluate(
            "() => !!(document.activeElement && document.activeElement.closest"
            " && document.activeElement.closest('.pine-editor-monaco'))"
        )
        if not inside:
            raise RuntimeError(
                "Could not focus the Pine Editor (Monaco textarea). "
                "A drawing tool is likely active on the chart — click "
                "the cursor/select tool in TV's left toolbar, then retry."
            )

    # Select all existing content, then paste.
    await page.keyboard.press("ControlOrMeta+a")
    await page.wait_for_timeout(80)
    await page.keyboard.press("ControlOrMeta+v")
    await page.wait_for_timeout(600)


async def save_and_add_to_chart(page: Page, script_name: str | None) -> dict:
    """Click Save in the editor toolbar; if a Save-As dialog appears,
    fill the name; then click Add to chart (which also compiles).

    Reads Monaco compile diagnostics (errors/warnings) BEFORE returning
    — Monaco's marker model is destroyed when the editor panel closes,
    so this read order is load-bearing. Returns
    `{compile: {available, errors, warnings, items}}`."""
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

    # Find "Add to chart" (brand-new script) or "Update on chart" (same-
    # titled script already on chart). Both do the same thing when
    # enabled: compile + apply. Key nuance: after a successful save of
    # an already-on-chart script, TV DISABLES the Update button — the
    # chart is already in sync, so there's nothing to click. A disabled
    # button is the clearest "already applied" signal we have; treat it
    # as success.
    try:
        btn = await first_visible(page, SEL_ADD_TO_CHART_CANDIDATES, timeout=6000)
        title = await btn.get_attribute("title")
        is_enabled = await btn.is_enabled()
        if not is_enabled:
            print(f"'{title}' button is disabled — script is already in "
                  f"sync with the chart (save was sufficient).", flush=True)
            return {"compile": await pine_compile.read_compile_summary(page)}
        await btn.click()
        await page.wait_for_timeout(1500)
        print(f"Clicked '{title}'. Indicator applied to chart.", flush=True)
    except PWTimeoutError:
        # Neither variant appeared. Fall back to the legend check —
        # search the entire chart DOM for the indicator's title text
        # rather than relying on a specific legend selector (TV's legend
        # wrapper classes rotate across builds).
        script_title = extract_indicator_title(await page.evaluate(
            "() => document.querySelector('.pine-editor-monaco')?.innerText || ''"
        )) or ""
        if script_title:
            found = await page.evaluate(
                """(title) => {
                    const root = document.querySelector('.chart-markup-table')
                              || document.querySelector('.layout__area--center')
                              || document.body;
                    return (root.innerText || '').toLowerCase()
                            .includes(title.toLowerCase());
                }""",
                script_title,
            )
            if found:
                print(f"Indicator '{script_title}' already on chart — "
                      f"save refreshed it in place.", flush=True)
                return {"compile": await pine_compile.read_compile_summary(page)}
        # Hard fail: the toolbar button wasn't there AND we couldn't
        # confirm the indicator in the chart legend. Exit non-zero so
        # the UI shows an explicit error instead of a misleading
        # success toast.
        print(
            "ERROR: neither 'Add to chart' nor 'Update on chart' button "
            f"was visible, and indicator name {script_title!r} was not "
            "detected in the chart. Check TradingView manually.",
            flush=True, file=sys.stderr,
        )
        sys.exit(2)
    return {"compile": await pine_compile.read_compile_summary(page)}


async def close_pine_editor(page: Page) -> None:
    """Close / collapse the Pine Editor panel so the chart gets its full
    visible area back. Handles both side-docked (right panel, X button)
    and bottom-docked (widget bar, Collapse chevron) layouts. Best-effort
    — the indicator is already on chart by this point, so a failure here
    is cosmetic, not functional."""
    try:
        if not await page.locator(SEL_MONACO).first.is_visible():
            return  # already closed / never opened
    except Exception:
        return

    # Side-docked layout: walk up from Monaco to the first ancestor that
    # contains a button[aria-label="Close"]. The close button lives in
    # the panel's outer chrome, not inside .tv-script-widget, so a
    # straight `locator(..., has=...)` against a fixed container won't
    # find it — hence the JS walk.
    closed_via_x = await page.evaluate("""() => {
      const m = document.querySelector('.pine-editor-monaco');
      if (!m) return false;
      let node = m;
      while (node && node !== document.body) {
        const btn = node.querySelector('button[aria-label="Close"]');
        if (btn) { btn.click(); return true; }
        node = node.parentElement;
      }
      return false;
    }""")
    if closed_via_x:
        try:
            await page.wait_for_selector(SEL_MONACO, state="hidden", timeout=3000)
            print("Closed Pine Editor panel (side-dock).", flush=True)
            return
        except PWTimeoutError:
            pass  # click landed but Monaco didn't go hidden — try fallback

    # Bottom-docked layout: Collapse-panel chevron in the widget bar.
    try:
        btn = await first_visible(page, SEL_COLLAPSE_PANEL_CANDIDATES, timeout=2000)
        await btn.click()
        await page.wait_for_selector(SEL_MONACO, state="hidden", timeout=3000)
        print("Collapsed Pine Editor panel (bottom-dock).", flush=True)
    except PWTimeoutError:
        print("NOTE: could not auto-close Pine Editor panel "
              "(indicator is still applied to the chart).", flush=True)


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
    ap.add_argument("--layout",
                    help="Override the layout to apply against. Default: "
                         "the AUTOMATION_LAYOUT_NAME-pinned layout (for "
                         "CLI use). The ui_server apply-pine endpoints "
                         "pass the freshly-cloned 'Pine — TS' layout name "
                         "here so the script lands on the new copy "
                         "instead of being yanked back to the default.")
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

        # Chart readiness — fail loud if TradingViewApi isn't exposed
        # (e.g., chart tab still loading, maintenance page) instead of
        # bombing deeper in the Pine Editor flow.
        try:
            ready = await health.assert_chart_ready(page)
            print(f"Chart ready: {ready['symbol']} @ {ready['resolution']}",
                  flush=True)
        except health.ChartNotReadyError as e:
            print(f"ERROR: {e}", flush=True, file=sys.stderr)
            return 1

        # Pin to the requested layout. Default (no --layout arg) is the
        # clean automation layout from AUTOMATION_LAYOUT_NAME — every
        # CLI apply runs against a known-clean canvas. The ui_server
        # endpoints override this with the just-cloned "Pine — TS"
        # layout so the script lands there and the original active
        # layout stays untouched.
        try:
            li = await layout_guard.ensure_layout(page, layout_name=args.layout)
            print(f"Layout: {li['name']!r}", flush=True)
        except layout_guard.LayoutMismatchError as e:
            print(f"ERROR: {e}\nRun `python -m tv_automation.layout_guard "
                  f"--bootstrap` once to create the layout.",
                  flush=True, file=sys.stderr)
            return 1

        # Capture pre-apply study count so we can detect the silent
        # "subprocess succeeded but study didn't actually attach" mode.
        pre_state = await replay_api.chart_state(page)
        studies_before = len(pre_state["studies"]) if pre_state else None

        print("Opening Pine Editor...", flush=True)
        await open_pine_editor(page)

        print("Replacing editor contents...", flush=True)
        await replace_editor_content(page, pine)

        print("Saving + adding to chart...", flush=True)
        save_result = await save_and_add_to_chart(page, name)

        # `save_and_add_to_chart` reads compile diagnostics inside its
        # own scope (Monaco markers vanish when the editor closes), so
        # the load-bearing read order is enforced by the function, not
        # by callers.
        compile_summary = save_result.get("compile") or {
            "available": False, "errors": 0, "warnings": 0, "items": [],
        }
        if compile_summary["available"]:
            if compile_summary["errors"] > 0:
                dump = pine_compile.write_failure_dump(
                    pine, compile_summary, PARSE_FAIL_DIR, stem=pine_path.stem,
                )
                print(
                    f"WARN: Pine compiled with {compile_summary['errors']} "
                    f"error(s), {compile_summary['warnings']} warning(s). "
                    f"Diagnostics: {dump}",
                    flush=True, file=sys.stderr,
                )
                for m in compile_summary["items"][:5]:
                    print(f"  [{m['severity_label']}] line {m['line']}: "
                          f"{m['message']}", flush=True, file=sys.stderr)
            elif compile_summary["warnings"] > 0:
                print(f"NOTE: Pine compiled with "
                      f"{compile_summary['warnings']} warning(s).", flush=True)
            else:
                print("Pine compiled clean (no Monaco diagnostics).", flush=True)
        else:
            print("NOTE: could not read Monaco compile diagnostics "
                  "(fiber walk failed).", flush=True)

        # Study-count delta — emit machine-parseable line so the
        # ui_server subprocess wrapper can spot anomalies (e.g., delta
        # of 0 when the indicator name wasn't already on chart implies
        # the apply silently no-op'd).
        post_state = await replay_api.chart_state(page)
        studies_after = len(post_state["studies"]) if post_state else None
        if studies_before is not None and studies_after is not None:
            delta = studies_after - studies_before
            print(f"STUDY_COUNT_DELTA: before={studies_before} "
                  f"after={studies_after} delta={delta}", flush=True)

        print("Collapsing Pine Editor panel...", flush=True)
        await close_pine_editor(page)

        # Let TradingView finish its layout transition (panel collapse
        # reflows the chart) before capturing. 800ms is enough on a
        # warm chart; bump if observed short.
        await page.wait_for_timeout(800)

        # Save the post-apply screenshot to a DURABLE location next to
        # the pine file, sharing its stem. Lets the operator review
        # later (rate setups, build a training set), and lets the
        # backend tie the image to the originating decision by
        # scanning the filename. Machine-parseable marker
        # `APPLIED_SCREENSHOT:` so the ui_server subprocess wrapper
        # can extract the path without scraping the human prose.
        applied_dir = GENERATED_DIR.parent / "applied"
        applied_dir.mkdir(parents=True, exist_ok=True)
        shot_path = applied_dir / f"{pine_path.stem}.png"
        await page.screenshot(path=str(shot_path))
        print(f"APPLIED_SCREENSHOT: {shot_path}", flush=True)
        # Keep the /tmp copy too for quick local review (Finder, etc.)
        # — symlink rather than duplicating bytes.
        tmp_link = Path("/tmp/tv_pine_applied.png")
        try:
            if tmp_link.exists() or tmp_link.is_symlink():
                tmp_link.unlink()
            tmp_link.symlink_to(shot_path)
        except Exception:
            pass  # Non-fatal: the durable path is what matters.

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
