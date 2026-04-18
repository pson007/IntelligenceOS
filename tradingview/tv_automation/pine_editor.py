"""Pine Editor surface — paste scripts, save, add to chart, read compile errors.

Three-step lifecycle for every apply:
  1. Open the Pine Editor panel if collapsed.
  2. Paste new content, save (Ctrl/Cmd+S), handle Save-As dialog if new.
  3. Click "Add to chart" OR — if the script is already on the chart —
     the save in step 2 refreshes it in place.

Compile errors live in a bottom console pane inside the Pine Editor.
After applying, we scrape that console for error text; empty → clean
compile, non-empty → return the errors so the caller can fix and retry.

CLI:
    python -m tv_automation.pine_editor apply path/to/file.pine
    python -m tv_automation.pine_editor apply --name "My RSI" path.pine
    python -m tv_automation.pine_editor compile-check
    python -m tv_automation.pine_editor errors   # read console only
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from playwright.async_api import Page

from preflight import ensure_automation_chromium
from session import tv_context

from .lib import audit, selectors
from .lib.cli import run
from .lib.errors import ModalError
from .lib.guards import assert_logged_in, with_lock

CHART_URL = "https://www.tradingview.com/chart/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pbcopy(text: str) -> None:
    """Put text on the macOS clipboard. Pasting is the reliable way to
    push >1KB Pine into Monaco — keyboard.type() on Monaco is unusably
    slow for real indicators."""
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def _extract_title(pine: str) -> str | None:
    """Parse the indicator/strategy title from `indicator("...")` or
    `strategy("...")` — pre-fills the Save-As dialog."""
    m = re.search(r'(?:indicator|strategy)\s*\(\s*"([^"]+)"', pine)
    return m.group(1) if m else None


async def _find_chart_page(ctx) -> Page:
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


async def _ensure_editor_open(page: Page) -> None:
    """Pine Editor collapses by default; expand it if needed."""
    monaco = page.locator(selectors.candidates("pine_editor", "monaco")[0]).first
    if await monaco.count() > 0 and await monaco.is_visible():
        return
    tab = await selectors.first_visible(page, "pine_editor", "open_button", timeout_ms=5000)
    await tab.click()
    await page.wait_for_selector(
        selectors.candidates("pine_editor", "monaco")[0],
        state="visible", timeout=10_000,
    )
    await page.wait_for_timeout(600)


async def _replace_editor_content(page: Page, pine: str) -> None:
    """Clipboard-paste the Pine code into the Monaco editor."""
    _pbcopy(pine)
    ta = page.locator(selectors.candidates("pine_editor", "monaco_textarea")[0]).first
    await ta.wait_for(state="attached", timeout=5000)
    await ta.click(force=True)
    await page.wait_for_timeout(150)
    await page.keyboard.press("ControlOrMeta+a")
    await page.wait_for_timeout(80)
    await page.keyboard.press("ControlOrMeta+v")
    await page.wait_for_timeout(600)


async def _save(page: Page, script_name: str | None) -> None:
    """Click Save (or Ctrl+S); handle first-time Save-As naming dialog."""
    try:
        btn = await selectors.first_visible(page, "pine_editor", "save_button", timeout_ms=3000)
        await btn.click()
    except Exception:
        # Fallback keyboard shortcut — works even when toolbar is off-screen.
        await page.keyboard.press("ControlOrMeta+s")
    await page.wait_for_timeout(900)

    # First save of a new script pops a "Save Script" dialog with an
    # input focused. Detect by activeElement tag and pre-fill the name.
    focused_tag = await page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    if focused_tag == "INPUT" and script_name:
        await page.keyboard.press("ControlOrMeta+a")
        await page.keyboard.type(script_name)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1500)


async def _add_to_chart_if_needed(page: Page) -> str:
    """Click 'Add to chart' if present, otherwise Save above refreshed
    an existing in-chart instance. Returns a status string for the audit
    log."""
    try:
        btn = await selectors.first_visible(
            page, "pine_editor", "add_to_chart_button", timeout_ms=3000,
        )
        await btn.click()
        await page.wait_for_timeout(1500)
        return "added_to_chart"
    except Exception:
        return "refreshed_in_place"


async def _read_compile_errors(page: Page, include_warnings: bool = False) -> list[str]:
    """Scrape the Pine Editor console for error rows.

    The console is a <table> inside the Pine Editor showing a log of
    Compiling.../Compiled./Error/Warning entries. Each log row has a
    class of the form `selectable-<hash>` plus one of `error-<hash>` or
    `warning-<hash>` for non-info rows. We match by the stable `error-`
    / `warning-` prefix.

    Returned strings preserve the visible text ("Error at 6:6 Undeclared
    identifier 'foo'"). Duplicates are deduped. Info-only rows
    (Compiling..., Compiled.) are ignored.
    """
    return await page.evaluate(f"""(includeWarnings) => {{
      const seen = new Set();
      const out = [];
      const selectors = ['tr[class*="error-"]'];
      if (includeWarnings) selectors.push('tr[class*="warning-"]');
      for (const sel of selectors) {{
        document.querySelectorAll(sel).forEach(r => {{
          const t = (r.innerText || '').trim();
          if (!t || seen.has(t)) return;
          seen.add(t);
          out.push(t);
        }});
      }}
      return out;
    }}""", include_warnings)


async def _read_console_row_texts(page: Page) -> list[str]:
    """Snapshot every console-log row's visible text. Used for the
    apply-window boundary: rows present BEFORE an apply are baseline,
    rows that appear AFTER are attributable to it.

    Each row's text starts with its timestamp ('9:07:05 PMCompiling...')
    so timestamps disambiguate identical-content entries (the same
    'Compiling...' string fires every save)."""
    return await page.evaluate(r"""() => {
      const rows = Array.from(document.querySelectorAll(
        'tr[class*="selectable-"]'
      ));
      return rows.map(r => (r.innerText || '').trim());
    }""")


async def _wait_for_new_compiling_row(
    page: Page, baseline: set[str], timeout_s: float = 6.0,
) -> str | None:
    """Poll until a new console row appears whose text contains 'Compiling'
    AND wasn't in the baseline snapshot. Returns the matching row text,
    or None on timeout.

    Rationale (ROADMAP §5d): the previous apply-window logic
    (`new_errors = all[len(before):]`) silently fails if TV ever clears
    the console — the diff goes to zero and looks like clean compile.
    Anchoring on a strictly-new 'Compiling...' row proves OUR apply
    triggered a recompile before we attribute any errors to it."""
    import asyncio
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        current = await _read_console_row_texts(page)
        for t in current:
            if t in baseline:
                continue
            # Match the visible-content portion that follows the
            # timestamp prefix. TV emits both 'Compiling...' and (more
            # rarely) localized variants; substring match keeps it
            # tolerant of whitespace / dot count drift.
            if "Compiling" in t:
                return t
        await asyncio.sleep(0.2)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def apply(
    path: Path,
    name: str | None = None,
    check_errors: bool = True,
    *,
    dry_run: bool = False,
) -> dict:
    """Paste a .pine file into the Pine Editor, save, add to chart,
    return compile status.

    `dry_run=True` validates the file locally (exists, readable, has a
    detectable title) and reports what WOULD happen, without touching
    the browser. Returns {'dry_run': True, 'path', 'name', 'size',
    'preview'}. Use this before real applies when an LLM wants to
    confirm the file is well-formed.
    """
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    pine = path.read_text()
    script_name = name or _extract_title(pine) or path.stem

    if dry_run:
        audit.log("pine_editor.apply.dry_run",
                  path=str(path), name=script_name, size=len(pine))
        return {
            "ok": True, "dry_run": True,
            "path": str(path), "name": script_name,
            "size": len(pine),
            "preview": pine[:200] + ("..." if len(pine) > 200 else ""),
            "detected_title": _extract_title(pine),
        }

    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_chart_page(ctx)
        await assert_logged_in(page)

        async with with_lock("tv_browser"):
            with audit.timed("pine_editor.apply",
                             path=str(path), name=script_name, size=len(pine)) as ctx_audit:
                await _ensure_editor_open(page)

                # Snapshot every console row text BEFORE the apply. Used
                # to disambiguate this apply's compile-window from the
                # persistent history. Errors text alone isn't enough —
                # if TV ever clears the console, the diff would silently
                # go to zero. Snapshotting all row texts (timestamps
                # included) lets us anchor on a strictly-new
                # 'Compiling...' row to bound this apply's window.
                console_baseline_texts: set[str] = set()
                before_errors: list[str] = []
                if check_errors:
                    console_baseline_texts = set(await _read_console_row_texts(page))
                    before_errors = await _read_compile_errors(page)

                await _replace_editor_content(page, pine)
                await _save(page, script_name)
                status = await _add_to_chart_if_needed(page)

                # Wait for OUR apply's compile to actually start. Without
                # this, a fast post-apply error scrape can race the
                # console — we'd see the pre-apply state and incorrectly
                # report success. Once the boundary row appears, any new
                # error rows belong to this apply.
                compile_boundary: str | None = None
                if check_errors:
                    compile_boundary = await _wait_for_new_compiling_row(
                        page, console_baseline_texts, timeout_s=6.0,
                    )
                    # Give the compiler a beat to produce its result row.
                    await page.wait_for_timeout(800)

                # Post-apply, attribute errors strictly by membership:
                # any error row whose text isn't in the baseline is from
                # this apply. Robust to console clears, row reorders,
                # and de-duplication of identical messages across runs.
                all_errors = (
                    await _read_compile_errors(page) if check_errors else []
                )
                new_errors = [
                    e for e in all_errors if e not in console_baseline_texts
                ]

                ctx_audit["status"] = status
                ctx_audit["new_error_count"] = len(new_errors)
                ctx_audit["total_error_count"] = len(all_errors)
                ctx_audit["compile_boundary_seen"] = compile_boundary is not None

                return {
                    "ok": len(new_errors) == 0,
                    "path": str(path),
                    "name": script_name,
                    "size": len(pine),
                    "status": status,
                    "errors": new_errors,
                    "historical_errors": before_errors,
                    "compile_boundary": compile_boundary,
                }


async def compile_errors(include_warnings: bool = False) -> list[str]:
    """Read-only: return the current Pine Editor's compile errors.
    Pass `include_warnings=True` to also include Warning rows."""
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_chart_page(ctx)
        await assert_logged_in(page)
        await _ensure_editor_open(page)
        return await _read_compile_errors(page, include_warnings=include_warnings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.pine_editor")
    sub = p.add_subparsers(dest="cmd", required=True)

    ap = sub.add_parser("apply", help="Apply a .pine file to the chart")
    ap.add_argument("path", type=Path)
    ap.add_argument("--name",
                    help="Script name for first-time save (default: parsed from indicator()/strategy())")
    ap.add_argument("--no-check-errors", dest="check_errors",
                    action="store_false", default=True,
                    help="Skip scraping the Pine console for compile errors")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate the file locally without touching the browser")

    e = sub.add_parser("errors", help="Read current Pine Editor compile errors")
    e.add_argument("--include-warnings", action="store_true",
                   help="Also include Warning rows (not just Errors)")

    args = p.parse_args()

    if args.cmd == "apply":
        run(lambda: apply(args.path, args.name, args.check_errors, dry_run=args.dry_run))
    elif args.cmd == "errors":
        run(lambda: compile_errors(include_warnings=args.include_warnings))


if __name__ == "__main__":
    _main()
