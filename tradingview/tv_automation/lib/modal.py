"""Generic modal dialog handling.

Most of TradingView's mutating UI is modal: indicator settings, save-as
dialogs, alert creation, symbol search, Pine script publish. This module
provides a uniform API so individual modules don't hand-roll dialog
handling each time.

Design:
  * wait_for_modal — returns the topmost dialog locator, optionally
    matching a title substring
  * fill_by_label — sets a form field by its visible label
  * confirm / cancel — click common buttons
  * close_all — dismiss every open dialog (recovery helper)
"""

from __future__ import annotations

from playwright.async_api import Locator, Page

from .errors import ModalError

_DIALOG_SELECTORS = [
    'div[role="dialog"]',
    '[data-name$="-dialog"]',
]


async def wait_for_modal(
    page: Page,
    title_contains: str | None = None,
    timeout_ms: int = 5000,
) -> Locator:
    """Wait for a modal dialog to appear, return its locator.

    If `title_contains` is given, the modal's visible text must include
    that substring — useful when multiple modals could be up (e.g. an
    alert creation dialog atop an indicator settings dialog).
    """
    step_ms = 200
    iterations = max(1, timeout_ms // step_ms)
    for _ in range(iterations):
        for sel in _DIALOG_SELECTORS:
            loc = page.locator(sel).last  # topmost dialog
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            if title_contains is None:
                return loc
            try:
                text = await loc.inner_text()
                if title_contains in text:
                    return loc
            except Exception:
                continue
        await page.wait_for_timeout(step_ms)
    raise ModalError(
        f"No modal appeared within {timeout_ms}ms"
        + (f" (expected title containing {title_contains!r})" if title_contains else "")
    )


async def fill_by_label(modal: Locator, label_text: str, value: str | int | float | bool) -> None:
    """Set a form field inside a modal by its associated label text.

    Strategy:
      1. Find the label element whose text matches label_text.
      2. The associated input is either:
         - explicit via `for=` (native label) — find input by id
         - implicit via DOM adjacency — find the first input after the
           label in document order
      3. For booleans: click the input if its checked state doesn't match.
      4. For numbers/strings: `fill()` the value.
    """
    label = modal.locator(f'label:has-text("{label_text}")').first
    if await label.count() == 0:
        # TradingView often uses `<div>` with label-like text instead of <label>.
        # Fall back to "element with exact text" → next sibling input.
        label = modal.locator(f'text="{label_text}"').first
        if await label.count() == 0:
            raise ModalError(f"No field with label {label_text!r} found in modal")

    # Prefer an input directly associated via `for`.
    for_attr = await label.get_attribute("for")
    if for_attr:
        input_el = modal.locator(f'#{for_attr}').first
    else:
        # XPath: first input that follows this label in document order.
        input_el = label.locator('xpath=following::input[1]').first

    if await input_el.count() == 0:
        raise ModalError(f"No input found for label {label_text!r}")

    input_type = (await input_el.get_attribute("type") or "").lower()
    if isinstance(value, bool) or input_type == "checkbox":
        checked = await input_el.is_checked()
        if bool(checked) != bool(value):
            await input_el.click()
    else:
        await input_el.fill(str(value))


async def confirm(modal: Locator, button_text: str = "OK") -> None:
    """Click a confirmation button inside the modal. Common labels:
    'OK', 'Save', 'Apply', 'Confirm', 'Create'."""
    btn = modal.locator(f'button:has-text("{button_text}")').first
    if await btn.count() == 0:
        raise ModalError(f"No button with text {button_text!r} in modal")
    await btn.click()


async def cancel(modal: Locator, page: Page) -> None:
    """Cancel a modal — click the Cancel button if present, else Escape."""
    cancel_btn = modal.locator('button:has-text("Cancel")').first
    if await cancel_btn.count() > 0:
        await cancel_btn.click()
    else:
        await page.keyboard.press("Escape")


async def close_all(page: Page) -> int:
    """Dismiss every visible modal. Recovery helper — use when you're
    not sure what state the page is in (e.g. after an error) and want
    a clean slate. Returns count of modals closed."""
    closed = 0
    for _ in range(10):  # safety cap
        dialog = page.locator('div[role="dialog"]').last
        if await dialog.count() == 0 or not await dialog.is_visible():
            break
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        closed += 1
    return closed


async def dismiss_overlays(page: Page, *, max_passes: int = 4) -> dict:
    """Aggressive pre-capture cleanup: dismiss any visible dialog,
    settings panel, dropdown, or context menu sitting on top of the
    chart. Used by `chart.screenshot` so a stray Settings dialog
    (Symbol / Canvas / Trading tabs etc.) doesn't end up in the PNG.

    Three escalation passes:
      1. Press Escape (covers most TV modals + drops armed drawing tools).
      2. Find any visible TV-style dialog via `popupDialog-*` /
         `dialog-*` / `[role="dialog"]` selectors and click its X /
         Close button.
      3. Click any visible Cancel button inside a dialog as a final
         attempt before giving up.

    Repeats up to `max_passes` times in case dismissing one reveals
    another. Returns `{passes, modals_left, dismissed_via}` for audit."""
    dismissed_via: list[str] = []

    # Selectors matching TV's actual modal classes — `role="dialog"`
    # alone misses TV's settings/options dialogs (CSS-modules classes).
    DIALOG_SELS = [
        '[class*="popupDialog-"]',
        '[class^="dialog-"]',
        '[class*=" dialog-"]',
        '[role="dialog"]',
        '[role="alertdialog"]',
    ]

    def _js_dialog_count() -> str:
        return r"""() => {
            const sels = [
                '[class*="popupDialog-"]',
                '[class^="dialog-"]',
                '[class*=" dialog-"]',
                '[role="dialog"]',
                '[role="alertdialog"]',
            ];
            const seen = new Set();
            let n = 0;
            for (const s of sels) {
                document.querySelectorAll(s).forEach(el => {
                    if (seen.has(el)) return;
                    const r = el.getBoundingClientRect();
                    if (r.width < 100 || r.height < 50) return;
                    if (r.bottom < 0 || r.top > window.innerHeight) return;
                    seen.add(el);
                    n++;
                });
            }
            return n;
        }"""

    for pass_idx in range(max_passes):
        modal_count = await page.evaluate(_js_dialog_count())
        if modal_count == 0:
            break

        # Pass 1: Escape always cheap; covers most TV modals + drawing
        # tool deselection + symbol-search dropdown.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)

        modal_count = await page.evaluate(_js_dialog_count())
        if modal_count == 0:
            dismissed_via.append("escape")
            continue

        # Pass 2: click an X / Close button inside the topmost dialog.
        # Walk through known-good selectors with a JS find — cheaper
        # than multiple Playwright queries.
        clicked = await page.evaluate(r"""() => {
            const sels = [
                '[class*="popupDialog-"]',
                '[class^="dialog-"]',
                '[class*=" dialog-"]',
                '[role="dialog"]',
                '[role="alertdialog"]',
            ];
            for (const s of sels) {
                const dialogs = Array.from(document.querySelectorAll(s));
                for (const d of dialogs.reverse()) {
                    const r = d.getBoundingClientRect();
                    if (r.width < 100 || r.height < 50) continue;
                    // Common close-button selectors inside TV dialogs.
                    const closeBtn = d.querySelector(
                        'button[aria-label="Close"], '
                      + '[data-name="close-button"], '
                      + 'button[class*="closeButton-"], '
                      + 'svg[class*="close-"]'
                    );
                    if (closeBtn) {
                        (closeBtn.closest('button') || closeBtn).click();
                        return 'close_button';
                    }
                    // Cancel as fallback.
                    const cancelBtn = Array.from(d.querySelectorAll('button'))
                        .find(b => /^(cancel|close)$/i.test(
                            (b.innerText||'').trim()
                        ));
                    if (cancelBtn) { cancelBtn.click(); return 'cancel_button'; }
                }
            }
            return null;
        }""")
        if clicked:
            dismissed_via.append(clicked)
            await page.wait_for_timeout(250)
            continue

        # Pass 3: nothing dismissable — bail this iteration.
        break

    final_count = await page.evaluate(_js_dialog_count())
    return {
        "passes": len(dismissed_via),
        "modals_left": final_count,
        "dismissed_via": dismissed_via,
    }
