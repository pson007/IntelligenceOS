"""Alerts surface — create/list/delete TradingView alerts.

Closes the autonomous loop: Pine strategy (or manual condition) fires
a TV alert → webhook POST → `tv-worker/` Cloudflare Worker →
`bridge.py` FastAPI → `tv orders place-market` (or whatever action).
With `tv_automation.alerts` you can build and deploy alerts
programmatically rather than clicking through the TV UI.

Supported operations (Tier 2a MVP):
  * list — read the right-sidebar alerts panel
  * create_price — symbol + operator + threshold + optional
    message/webhook/notifications
  * delete / delete_all — remove alerts by ID or wholesale
  * pause / resume — toggle the per-row enable switch

Not supported (deferred):
  * Indicator-based alerts (condition type "Indicator") — the
    condition builder for indicators is a separate probe cycle.
  * Editing an existing alert's fields — the Edit dialog is a
    different modal variant; minor extension when needed.

CLI:
    tv alerts list
    tv alerts create-price MNQ1! crossing 27000 \\
        --message '{"symbol": "{{ticker}}", "price": "{{close}}"}' \\
        --webhook https://your.worker/hook \\
        --name "MNQ breakout 27000"
    tv alerts delete <alert_id>
    tv alerts delete-all
    tv alerts pause <alert_id>
    tv alerts resume <alert_id>
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Literal

from playwright.async_api import BrowserContext, Page

from . import config
from .lib import audit, selectors
from .lib.cli import run
from .lib.context import chart_session
from .lib.errors import (
    ChartNotReadyError, ModalError, VerificationFailedError,
)
from .lib.guards import with_lock
from .lib.overlays import dismiss_toasts
from .lib.urls import chart_url_for

CHART_URL = "https://www.tradingview.com/chart/"

# Canonical operator codes ↔ TV's display text.
_OPERATOR_DISPLAY = {
    "crossing": "Crossing",
    "crossing-up": "Crossing Up",
    "crossing-down": "Crossing Down",
}

# Canonical trigger frequency codes ↔ display text.
_TRIGGER_DISPLAY = {
    "once-only": "Once only",
    "every-time": "Every time",
}


# ---------------------------------------------------------------------------
# Navigation / sidebar helpers.
# ---------------------------------------------------------------------------

async def _navigate_to_symbol(page: Page, symbol: str) -> None:
    """Switch chart to `symbol` preserving the saved-layout URL segment."""
    target = chart_url_for(page.url, symbol=symbol)
    if page.url != target:
        await page.goto(target, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("canvas", state="visible", timeout=20_000)
        except Exception as e:
            raise ChartNotReadyError(
                f"Chart canvas didn't appear for {symbol}: {e}"
            )
        await page.wait_for_timeout(600)


async def _ensure_alerts_sidebar_open(page: Page) -> None:
    """Ensure the right-sidebar alerts panel is expanded.

    Detects open-state by the presence (visible) of the set-alert
    button. Clicks the alerts icon only when needed — a redundant click
    would toggle the sidebar closed."""
    if await selectors.any_visible(page, "alerts_panel", "set_alert_button"):
        return
    await dismiss_toasts(page)
    icon = await selectors.first_visible(
        page, "alerts_panel", "sidebar_icon", timeout_ms=5000,
    )
    await icon.click()
    # Wait for the panel's "+" button to appear.
    await selectors.first_visible(
        page, "alerts_panel", "set_alert_button", timeout_ms=5000,
    )


async def _open_create_alert_dialog(page: Page) -> None:
    """Click the '+' button to open the Create Alert dialog. Waits for
    the dialog container to become visible."""
    await _ensure_alerts_sidebar_open(page)
    btn = await selectors.first_visible(
        page, "alerts_panel", "set_alert_button", timeout_ms=5000,
    )
    await btn.click()
    try:
        await selectors.first_visible(
            page, "alerts_dialog", "container", timeout_ms=5000,
        )
    except Exception as e:
        raise ModalError(
            f"Create Alert dialog didn't appear after clicking + button: {e}"
        )


async def _close_dialog(page: Page) -> None:
    """Dismiss the Create Alert dialog cleanly."""
    try:
        cancel = await selectors.first_visible(
            page, "alerts_dialog", "cancel_button", timeout_ms=2000,
        )
        await cancel.click()
    except Exception:
        # Fallback: Escape.
        await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Dialog-field setters.
# ---------------------------------------------------------------------------

async def _set_operator(page: Page, op: str) -> None:
    """Set the Condition → operator dropdown (Crossing / Crossing Up /
    Crossing Down). Idempotent — skips the click if already set."""
    want_display = _OPERATOR_DISPLAY[op]
    op_btn = await selectors.first_visible(
        page, "alerts_dialog", "operator_button", timeout_ms=3000,
    )
    current = (await op_btn.inner_text()).strip()
    if current == want_display:
        return
    await op_btn.click()
    await page.wait_for_timeout(400)
    # Click the matching option.
    option = page.locator(
        f'[role="option"]:text-is("{want_display}")'
    ).first
    await option.click(timeout=3000)
    await page.wait_for_timeout(300)


async def _set_value(page: Page, value: float) -> None:
    inp = await selectors.first_visible(
        page, "alerts_dialog", "value_input", timeout_ms=3000,
    )
    await inp.fill(str(value))
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(200)


async def _set_trigger(page: Page, trigger: str) -> None:
    """Set Once only / Every time."""
    want_display = _TRIGGER_DISPLAY[trigger]
    btn = await selectors.first_visible(
        page, "alerts_dialog", "trigger_button", timeout_ms=3000,
    )
    # Trigger button's visible text may include a subtitle; match on first line.
    current_full = (await btn.inner_text()).strip()
    current = current_full.splitlines()[0].strip() if current_full else ""
    if current == want_display:
        return
    await btn.click()
    await page.wait_for_timeout(400)
    option = page.locator(
        f'[role="option"]:has-text("{want_display}"), '
        f'[role="menuitem"]:has-text("{want_display}")'
    ).first
    await option.click(timeout=3000)
    await page.wait_for_timeout(300)


async def _set_message_and_name(
    page: Page, *, name: str | None, message: str | None,
) -> None:
    """Open the Edit Message sub-modal and fill name + message fields.

    Both fields have stable `id=` attributes discovered 2026-04-17:
    `input#alert-name` and `textarea#alert-message`. The sub-modal
    itself has class-prefix `messagePopup-`, distinguishing it from
    the parent Create Alert dialog.

    After filling, click Apply (NOT Cancel — that drops edits). If
    both args are None, we don't open the sub-modal at all.
    """
    if name is None and message is None:
        return

    # Click the message-preview button ("SYMBOL Crossing VALUE" text)
    # via JS — Playwright's actionable click can race here similarly
    # to the notifications button.
    clicked = await page.evaluate(r"""() => {
        const dlg = Array.from(document.querySelectorAll('div[class*="dialog-"]'))
            .find(d => (d.innerText || '').includes('Create alert on'));
        if (!dlg) return false;
        // The message-preview button has class prefix `button-KijOUKJc`
        // and is NOT the notifications button (which contains "Webhook").
        const btns = Array.from(dlg.querySelectorAll('button[class*="button-KijOUKJc"]'));
        const target = btns.find(b => !(b.innerText || '').includes('Webhook')
                                   && !(b.innerText || '').includes('App'));
        if (!target) return false;
        target.click();
        return true;
    }""")
    if not clicked:
        raise ModalError("Message-preview button not found in Create Alert dialog")
    # Wait for the Edit Message sub-modal.
    await selectors.first_visible(
        page, "alerts_dialog", "edit_message_popup", timeout_ms=5000,
    )

    if name is not None:
        name_input = await selectors.first_visible(
            page, "alerts_dialog", "edit_message_name_input", timeout_ms=2000,
        )
        await name_input.fill(name)

    if message is not None:
        textarea = await selectors.first_visible(
            page, "alerts_dialog", "edit_message_textarea", timeout_ms=2000,
        )
        # Textarea may have a default value from the condition preview —
        # fill() clears and replaces atomically.
        await textarea.fill(message)

    apply_btn = await selectors.first_visible(
        page, "alerts_dialog", "edit_message_apply", timeout_ms=3000,
    )
    await apply_btn.click()
    # Wait for the sub-modal to close (parent dialog back on top).
    await page.wait_for_timeout(500)


async def _set_notifications(
    page: Page, *,
    webhook_url: str | None,
    notify_app: bool,
    notify_toast: bool,
    notify_email: bool,
    notify_sound: bool,
) -> dict:
    """Open the Edit Notifications sub-modal and configure channels.

    Stable handles discovered 2026-04-17:
      - Webhook URL input has `id="webhook-url"`.
      - Checkboxes have no ids; identified by sibling label text
        via xpath (e.g. "Notify in app", "Webhook URL", "Play sound").

    Returns a dict of `{channel: 'on'|'off'|'unchanged'}` for audit.
    Skipping the sub-modal entirely when all args are None/False keeps
    TV's existing notification settings untouched.
    """
    any_change = any([
        webhook_url is not None, notify_app, notify_toast,
        notify_email, notify_sound,
    ])
    if not any_change:
        return {}

    # Click the "App, Toasts, Email, Webhook, Sound" button directly via
    # JS. Playwright's element-click sometimes races or is intercepted
    # here even though the button is visible; JS click on the matched
    # DOM element is what our manual probe verified works.
    clicked = await page.evaluate(r"""() => {
        const dlg = Array.from(document.querySelectorAll('div[class*="dialog-"]'))
            .find(d => (d.innerText || '').includes('Create alert on'));
        if (!dlg) return false;
        for (const b of dlg.querySelectorAll('button')) {
            const t = (b.innerText || '').trim();
            if (t.includes('App') && t.includes('Webhook')) { b.click(); return true; }
        }
        return false;
    }""")
    if not clicked:
        raise ModalError("Notifications button not found in Create Alert dialog")
    # Wait for the Notifications sub-modal. The `:has-text("Notify in app")`
    # filter uniquely identifies it — parent dialog doesn't contain that
    # phrase.
    await selectors.first_visible(
        page, "alerts_dialog", "notif_popup", timeout_ms=5000,
    )

    result: dict = {}

    async def _toggle(role: str, desired: bool, key: str) -> None:
        try:
            cb = await selectors.first_visible(
                page, "alerts_dialog", role, timeout_ms=2000,
            )
        except Exception:
            result[key] = "absent"
            return
        checked = await cb.is_checked()
        if bool(checked) == bool(desired):
            result[key] = "unchanged"
            return
        await cb.click()
        await page.wait_for_timeout(150)
        result[key] = "on" if desired else "off"

    await _toggle("notif_toggle_app", notify_app, "app")
    await _toggle("notif_toggle_toast", notify_toast, "toast")
    await _toggle("notif_toggle_email", notify_email, "email")
    await _toggle("notif_toggle_sound", notify_sound, "sound")

    if webhook_url is not None:
        # Ensure the webhook checkbox is ON, then fill the URL input.
        # The URL field is always present in the DOM (doesn't appear
        # only on toggle-on, per 2026-04-17 probe), but enabling the
        # checkbox is what makes TV actually POST to it.
        await _toggle("notif_toggle_webhook", True, "webhook")
        url_input = await selectors.first_visible(
            page, "alerts_dialog", "notif_webhook_url_input", timeout_ms=2000,
        )
        await url_input.fill(webhook_url)
        # Tab to commit the input value into React state.
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(200)
        result["webhook_url"] = webhook_url

    # Apply the sub-modal to persist changes back to the parent form.
    apply_btn = await selectors.first_visible(
        page, "alerts_dialog", "notif_apply", timeout_ms=3000,
    )
    await apply_btn.click()
    await page.wait_for_timeout(500)
    return result


# ---------------------------------------------------------------------------
# List alerts from the right-sidebar panel.
# ---------------------------------------------------------------------------

async def _read_alerts_list(page: Page) -> list[dict]:
    """Scrape the alerts panel for currently-configured alerts.

    Group by row container: each alert has `alert-item-description`
    (the human-readable condition), `alert-item-ticker` (symbol), and
    `alert-item-status` ("Active" / "Stopped") data-named children.
    We walk up from the description element to find the shared row
    ancestor, then collect the trio of fields.
    """
    if await selectors.any_visible(page, "alerts_panel", "empty_state"):
        return []

    rows = await page.evaluate(r"""() => {
        // Each alert has exactly one `alert-item-description` element.
        const descs = Array.from(document.querySelectorAll(
            '[data-name="alert-item-description"]'
        ));
        return descs.map(d => {
            // Walk up until we find a parent that also contains the
            // ticker and status elements — that's the row container.
            let row = d;
            for (let i = 0; i < 6 && row.parentElement; i++) {
                row = row.parentElement;
                if (row.querySelector('[data-name="alert-item-ticker"]') &&
                    row.querySelector('[data-name="alert-item-status"]')) {
                    break;
                }
            }
            const ticker = row.querySelector('[data-name="alert-item-ticker"]');
            const status = row.querySelector('[data-name="alert-item-status"]');
            return {
                description: (d.innerText || '').trim(),
                ticker: ticker ? (ticker.innerText || '').trim() : null,
                status: status ? (status.innerText || '').trim() : null,
            };
        });
    }""")
    return rows or []


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------

async def list_alerts() -> dict:
    """List all currently-configured TV alerts from the sidebar panel."""
    async with chart_session() as (_ctx, page):
        await _ensure_alerts_sidebar_open(page)
        alerts = await _read_alerts_list(page)
        audit.log("alerts.list", count=len(alerts))
        return {"ok": True, "count": len(alerts), "alerts": alerts}


async def create_price_alert(
    symbol: str,
    op: str,
    value: float,
    *,
    message: str | None = None,
    webhook_url: str | None = None,
    name: str | None = None,
    trigger: str = "once-only",
    notify_app: bool = False,
    notify_toast: bool = False,
    notify_email: bool = False,
    notify_sound: bool = False,
    dry_run: bool = False,
) -> dict:
    """Create a price-crossing alert for `symbol`.

    op ∈ {crossing, crossing-up, crossing-down}. TV's Price condition
    exposes only these three operators; use an indicator-based alert
    for > / < / entering / exiting semantics.
    """
    # Validate inputs up front.
    if op not in _OPERATOR_DISPLAY:
        raise ValueError(
            f"op must be one of {sorted(_OPERATOR_DISPLAY)}, got {op!r}"
        )
    if trigger not in _TRIGGER_DISPLAY:
        raise ValueError(
            f"trigger must be one of {sorted(_TRIGGER_DISPLAY)}, got {trigger!r}"
        )
    # Symbol validation: reuse the existing allowlist from limits.yaml —
    # same defense-in-depth against LLM hallucinations; and tick
    # alignment on the value since it's a price.
    config.check_symbol(symbol)
    config.check_tick_alignment(symbol, value, field="alert value")

    async with chart_session() as (_ctx, page):
        await _navigate_to_symbol(page, symbol)

        async with with_lock("tv_browser"):
            with audit.timed(
                "alerts.create_price",
                symbol=symbol, op=op, value=value,
                has_webhook=webhook_url is not None,
                trigger=trigger,
                dry_run=dry_run,
            ) as audit_ctx:
                await _open_create_alert_dialog(page)

                # Verify the dialog is scoped to our symbol — TV pre-fills
                # from the active chart, but if the user has multiple
                # charts open we want to fail-fast rather than create an
                # alert on the wrong instrument.
                dialog_text = await page.evaluate(r"""() => {
                    const c = document.querySelector(
                        'div[class*="dialog-"][class*="popup-"]'
                    );
                    return c ? (c.innerText || '').slice(0, 100) : '';
                }""")
                bare = symbol.split(":")[-1].upper()
                if bare not in dialog_text.upper():
                    await _close_dialog(page)
                    raise VerificationFailedError(
                        "alert dialog symbol",
                        expected=bare,
                        actual=dialog_text[:60],
                    )

                # Configure the base fields — operator, value, trigger.
                await _set_operator(page, op)
                await _set_value(page, value)
                await _set_trigger(page, trigger)

                # Edit Message sub-modal (name + message body). Only
                # opens if either is supplied.
                await _set_message_and_name(
                    page, name=name, message=message,
                )

                # Edit Notifications sub-modal. Only opens if webhook
                # URL or any notification flag is supplied — leaving
                # all None/False inherits TV's current defaults.
                notif_result = await _set_notifications(
                    page,
                    webhook_url=webhook_url,
                    notify_app=notify_app,
                    notify_toast=notify_toast,
                    notify_email=notify_email,
                    notify_sound=notify_sound,
                )
                audit_ctx["notifications"] = notif_result
                audit_ctx["configured"] = True

                if dry_run:
                    await _close_dialog(page)
                    return {
                        "ok": True, "dry_run": True,
                        "symbol": symbol, "op": op, "value": value,
                        "message": message, "webhook_url_set": webhook_url is not None,
                        "name": name, "trigger": trigger,
                    }

                # Snapshot alert list before submit so we can detect the
                # new alert after.
                before = await _read_alerts_list(page)
                before_ids = {a.get("id_hint") for a in before}

                submit = await selectors.first_visible(
                    page, "alerts_dialog", "submit_button", timeout_ms=3000,
                )
                await submit.click()

                # Wait for dialog to close and sidebar to update.
                await page.wait_for_timeout(1500)

                # Poll for the new alert to appear.
                new_alert: dict | None = None
                for _ in range(10):
                    await page.wait_for_timeout(400)
                    current = await _read_alerts_list(page)
                    for row in current:
                        hint = row.get("id_hint")
                        if hint and hint not in before_ids:
                            new_alert = row
                            break
                    if new_alert:
                        break

                audit_ctx["new_alert_hint"] = (
                    new_alert.get("id_hint") if new_alert else None
                )

                return {
                    "ok": True, "dry_run": False,
                    "verified": bool(new_alert),
                    "symbol": symbol, "op": op, "value": value,
                    "message": message, "name": name,
                    "webhook_url_set": webhook_url is not None,
                    "trigger": trigger,
                    "new_alert": new_alert,
                    "count_before": len(before),
                    "count_after": len(current) if new_alert else None,
                }


async def _click_row_action(
    page: Page, identifier: str, action_data_names: str | list[str],
) -> dict:
    """Locate the alert row matching `identifier` (substring of its
    `alert-item-description`), dispatch mouseenter to reveal the
    hover-only action buttons, and click the FIRST available button
    whose data-name appears in `action_data_names`.

    Why accept a list: TV renames per-row buttons based on state —
    `alert-stop-button` exists on Active alerts, `alert-restart-button`
    on Paused ones. Callers pass both options and we click whichever
    is present.
    """
    if isinstance(action_data_names, str):
        action_data_names = [action_data_names]
    return await page.evaluate(
        r"""({ident, actionNames}) => {
            const descs = Array.from(document.querySelectorAll(
                '[data-name="alert-item-description"]'
            ));
            for (const d of descs) {
                if (!(d.innerText || '').includes(ident)) continue;
                let row = d;
                for (let i = 0; i < 6 && row.parentElement; i++) {
                    row = row.parentElement;
                    if (row.querySelector('[data-name="alert-item-ticker"]')) break;
                }
                row.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                let btn = null, clickedName = null;
                for (const name of actionNames) {
                    btn = row.querySelector(`[data-name="${name}"]`);
                    if (btn) { clickedName = name; break; }
                }
                if (!btn) {
                    const available = Array.from(row.querySelectorAll('[data-name^="alert-"]'))
                        .map(b => b.getAttribute('data-name'));
                    return {
                        found: true, clicked: false,
                        reason: 'button missing',
                        wanted: actionNames,
                        available,
                    };
                }
                btn.click();
                return {
                    found: true, clicked: true,
                    clicked_name: clickedName,
                    row_text: (row.innerText || '').trim().slice(0, 150),
                    prev_status: (
                        row.querySelector('[data-name="alert-item-status"]') || {}
                    ).innerText || null,
                };
            }
            return {found: false};
        }""",
        {"ident": identifier, "actionNames": action_data_names},
    )


async def _confirm_destructive(page: Page, timeout_ms: int = 3000) -> bool:
    """Wait for TV's destructive-action confirm dialog and click its
    positive button. Returns True if confirmed.

    Observed dialog shape (2026-04-17): `popupDialog-B02UUUN3`-classed
    div with buttons `[Delete, No, close]`. We poll for up to
    `timeout_ms` because the dialog is painted async after the trigger
    click. Match via JS exact-text equality — `has-text` is substring
    and can match 'Delete All Inactive' when we want just 'Delete'.
    """
    deadline = timeout_ms
    step = 200
    while deadline > 0:
        clicked = await page.evaluate(r"""() => {
            // Find any visible dialog with a positive-action button.
            const POS = ['Delete', 'Yes, delete', 'Yes', 'Remove', 'Confirm', 'OK'];
            const dialogs = Array.from(document.querySelectorAll(
                'div[class*="dialog-"]'
            )).filter(d => {
                const r = d.getBoundingClientRect();
                return r.width > 200 && r.height > 100;
            });
            for (const dlg of dialogs) {
                const btns = Array.from(dlg.querySelectorAll('button'));
                for (const label of POS) {
                    const match = btns.find(b => (b.innerText || '').trim() === label);
                    if (match) { match.click(); return label; }
                }
            }
            return null;
        }""")
        if clicked:
            await page.wait_for_timeout(400)
            return True
        await page.wait_for_timeout(step)
        deadline -= step
    return False


async def delete_alert(identifier: str, *, dry_run: bool = False) -> dict:
    """Delete an alert whose description contains `identifier`."""
    async with chart_session() as (_ctx, page):
        await _ensure_alerts_sidebar_open(page)
        async with with_lock("tv_browser"):
            with audit.timed(
                "alerts.delete", identifier=identifier, dry_run=dry_run,
            ) as audit_ctx:
                if dry_run:
                    # Just locate the row and report what we'd delete.
                    found = await page.evaluate(
                        r"""(ident) => {
                            const descs = Array.from(document.querySelectorAll(
                                '[data-name="alert-item-description"]'
                            ));
                            for (const d of descs) {
                                if ((d.innerText || '').includes(ident)) {
                                    return (d.innerText || '').trim();
                                }
                            }
                            return null;
                        }""", identifier,
                    )
                    audit_ctx["dry_run_found"] = found
                    return {
                        "ok": found is not None, "dry_run": True,
                        "identifier": identifier, "would_delete": found,
                    }

                before = await _read_alerts_list(page)
                click_result = await _click_row_action(
                    page, identifier, ["alert-delete-button"],
                )
                audit_ctx["click_result"] = click_result
                if not click_result.get("clicked"):
                    return {
                        "ok": False, "identifier": identifier,
                        "reason": click_result.get("reason", "row_not_found"),
                        "click_result": click_result,
                    }

                # TV may pop a confirmation dialog for delete — click through.
                confirmed = await _confirm_destructive(page)
                audit_ctx["confirmed"] = confirmed

                # Poll for the row to disappear.
                await page.wait_for_timeout(500)
                gone = False
                for _ in range(10):
                    await page.wait_for_timeout(300)
                    current = await _read_alerts_list(page)
                    if not any(
                        identifier in (a.get("description") or "")
                        for a in current
                    ):
                        gone = True
                        break

                return {
                    "ok": True, "dry_run": False,
                    "identifier": identifier,
                    "verified": gone,
                    "confirmed_dialog": confirmed,
                    "count_before": len(before),
                    "count_after": len(current) if gone else None,
                }


async def pause_alert(identifier: str) -> dict:
    """Toggle the alert's active state (pause ↔ resume). TV's
    `alert-stop-button` is a single toggle — calling pause() on a
    paused alert resumes it. For semantic clarity, use `pause_alert`
    to mean "make it inactive if currently active" and `resume_alert`
    for the reverse; internally both use the same toggle but gate on
    the row's current status.
    """
    return await _toggle_alert(identifier, desired_active=False)


async def resume_alert(identifier: str) -> dict:
    return await _toggle_alert(identifier, desired_active=True)


async def _toggle_alert(identifier: str, *, desired_active: bool) -> dict:
    async with chart_session() as (_ctx, page):
        await _ensure_alerts_sidebar_open(page)
        async with with_lock("tv_browser"):
            with audit.timed(
                "alerts.toggle", identifier=identifier,
                desired_active=desired_active,
            ) as audit_ctx:
                # Read current state; skip if already correct.
                current = await _read_alerts_list(page)
                row = next(
                    (a for a in current
                     if identifier in (a.get("description") or "")),
                    None,
                )
                if row is None:
                    return {
                        "ok": False, "identifier": identifier,
                        "reason": "row_not_found",
                    }
                current_active = (row.get("status") or "").lower() == "active"
                if current_active == desired_active:
                    audit_ctx["noop"] = True
                    return {
                        "ok": True, "identifier": identifier,
                        "already_in_state": True,
                        "status": row.get("status"),
                    }

                # Active alerts expose `alert-stop-button` (pause);
                # paused alerts expose `alert-restart-button` (resume).
                click_result = await _click_row_action(
                    page, identifier,
                    ["alert-stop-button", "alert-restart-button"],
                )
                if not click_result.get("clicked"):
                    return {
                        "ok": False, "identifier": identifier,
                        "reason": click_result.get("reason", "row_not_found"),
                    }

                # Poll for the status to actually flip. A single 500ms
                # wait + read is racy — TV's `alert-item-status`
                # indicator can lag the click by 1-2s, returning the
                # stale "Paused" status for a freshly-resumed alert
                # (and vice versa). Poll until we see the desired
                # state OR the timeout elapses.
                want_status = "active" if desired_active else "paused"
                new_row = row
                verified = False
                for _ in range(15):  # ~3s total at 200ms steps
                    await page.wait_for_timeout(200)
                    new_list = await _read_alerts_list(page)
                    new_row = next(
                        (a for a in new_list
                         if identifier in (a.get("description") or "")),
                        None,
                    )
                    if new_row is None:
                        # Row vanished — alert may have been deleted
                        # mid-toggle. Bail and let the caller handle.
                        break
                    cur_status = (new_row.get("status") or "").lower()
                    if cur_status == want_status:
                        verified = True
                        break
                audit_ctx["verified"] = verified
                return {
                    "ok": True, "identifier": identifier,
                    "prev_status": row.get("status"),
                    "new_status": new_row.get("status") if new_row else None,
                    "verified": verified,
                }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.alerts")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List currently-configured alerts")

    cp = sub.add_parser("create-price", help="Create a price-crossing alert")
    cp.add_argument("symbol")
    cp.add_argument("op", choices=list(_OPERATOR_DISPLAY.keys()))
    cp.add_argument("value", type=float)
    cp.add_argument("--message", default=None,
                    help="Message body sent to webhook / shown in toast")
    cp.add_argument("--webhook", dest="webhook_url", default=None,
                    help="Webhook URL (Pro+ feature). Implies --notify-webhook.")
    cp.add_argument("--name", default=None, help="Alert display name")
    cp.add_argument("--trigger", choices=list(_TRIGGER_DISPLAY.keys()),
                    default="once-only")
    cp.add_argument("--notify-app", action="store_true")
    cp.add_argument("--notify-toast", action="store_true")
    cp.add_argument("--notify-email", action="store_true")
    cp.add_argument("--notify-sound", action="store_true")
    cp.add_argument("--dry-run", action="store_true")

    dl = sub.add_parser("delete", help="Delete an alert by description substring")
    dl.add_argument("identifier",
                    help="Substring of the alert's description (e.g. 'MNQ1! Crossing 27')")
    dl.add_argument("--dry-run", action="store_true")

    pa = sub.add_parser("pause", help="Pause an active alert")
    pa.add_argument("identifier")

    rs = sub.add_parser("resume", help="Resume a paused alert")
    rs.add_argument("identifier")

    args = p.parse_args()

    if args.cmd == "list":
        run(lambda: list_alerts())
    elif args.cmd == "create-price":
        run(lambda: create_price_alert(
            args.symbol, args.op, args.value,
            message=args.message, webhook_url=args.webhook_url,
            name=args.name, trigger=args.trigger,
            notify_app=args.notify_app, notify_toast=args.notify_toast,
            notify_email=args.notify_email, notify_sound=args.notify_sound,
            dry_run=args.dry_run,
        ))
    elif args.cmd == "delete":
        run(lambda: delete_alert(args.identifier, dry_run=args.dry_run))
    elif args.cmd == "pause":
        run(lambda: pause_alert(args.identifier))
    elif args.cmd == "resume":
        run(lambda: resume_alert(args.identifier))


if __name__ == "__main__":
    _main()
