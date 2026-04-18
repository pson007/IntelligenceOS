"""Detect + dismiss TradingView's 'Session disconnected' modal.

When a TV account signs in from another browser/device, the original
session gets a blocking modal:

    Session disconnected
    Your session ended because your account was accessed from another
    browser or device. ...
    [Connect]

Until the user clicks Connect, the chart is frozen — every downstream
tv automation (screenshot, click, trade) would operate against a
stale view. Auto-dismissing the modal at session entry makes the
whole CLI resilient to this.

Scope: this is a library-level infra concern, like `lib/modal.py`.
`lib/context.chart_session()` calls `click_reconnect_if_present` after
`assert_logged_in`, so every surface gets auto-reconnect for free.
An explicit `tv chart reconnect` CLI exposes the same thing for
manual invocation and debugging.

Detection uses a single `page.evaluate()` that returns `None` when no
modal is present (<10ms hot path), so the always-on overhead on
unaffected commands is negligible.
"""

from __future__ import annotations

from playwright.async_api import Page

from . import audit

# JS: detect the TV reconnect modal and find its Connect button.
#
# The modal uses hash-suffixed class names (`wrapper-SiBYNi_V`,
# `title-vhfmr0Do`, etc.) and carries NO role="dialog" / data-name —
# our earlier selector-based search missed it entirely. All TV modals
# are mounted inside `#overlap-manager-root`; we scope to there and
# fast-reject on `textContent` when no trigger phrase is present.
#
# Hot path (no modal): one getElementById + one textContent regex test,
# <1ms. Slow path (modal up): find title element → find Connect button.
_DETECT_JS = r"""() => {
    const root = document.getElementById('overlap-manager-root');
    if (!root) return null;
    const RECONNECT_MODAL_TEXT = /session disconnected|session ended|connection lost/i;
    const RECONNECT_BUTTON_TEXT = /^(connect|reconnect|retry|try again)$/i;
    // Fast reject: textContent is cheap (no layout) and short when no
    // modal is up (#overlap-manager-root is usually empty or just
    // holds tooltip fragments).
    if (!RECONNECT_MODAL_TEXT.test(root.textContent || '')) return null;

    // Slow path: find the specific title element + button.
    // Title tags in TV modals are typically <p>/<h1>/<h2>/<h3>.
    const titleCandidates = root.querySelectorAll('p, h1, h2, h3, div, span');
    let titleText = '';
    for (const el of titleCandidates) {
        const t = (el.innerText || '').trim();
        if (t.length === 0 || t.length > 200) continue;
        if (!RECONNECT_MODAL_TEXT.test(t)) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        titleText = t;
        break;
    }

    // Find a reconnect button anywhere in the modal root.
    const buttons = root.querySelectorAll('button');
    for (const b of buttons) {
        const t = (b.innerText || '').trim();
        if (!RECONNECT_BUTTON_TEXT.test(t)) continue;
        const r = b.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        return {
            modal_text: (titleText || 'matched by phrase').slice(0, 160),
            button_text: t,
            center: {
                x: Math.round(r.x + r.width / 2),
                y: Math.round(r.y + r.height / 2),
            },
            rect: {
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
            },
        };
    }

    // Modal matched but no reconnect button found — report so the
    // caller knows SOMETHING is up, even if we can't fix it.
    return {
        modal_text: (titleText || 'matched by phrase').slice(0, 160),
        button_text: null,
        center: null,
        rect: null,
    };
}"""


async def detect_session_modal(page: Page) -> dict | None:
    """Return details about a visible session-disconnect modal, or None.

    Single JS round-trip. Hot path (no modal) runs in <10ms. When a
    modal IS present, returns `{modal_text, button_text, center, rect}`.
    `center` and `button_text` are None if the modal is present but
    no recognizable reconnect button was found inside it."""
    return await page.evaluate(_DETECT_JS)


async def click_reconnect_if_present(page: Page) -> dict:
    """Detect + click Connect in one call. Safe to call unconditionally;
    returns `{present: False}` when no modal is up.

    On click, waits 1500ms for the session to reconnect, then re-probes
    to confirm the modal dismissed. Non-fatal on failure — logs via
    audit and returns `clicked: False` with a reason. The caller can
    decide whether to proceed or abort."""
    info = await detect_session_modal(page)
    if info is None:
        return {"present": False, "clicked": False}

    audit.log("session_modal.detected",
              modal_text=info.get("modal_text"),
              button_text=info.get("button_text"))

    if not info.get("center"):
        return {
            "present": True, "clicked": False,
            "reason": "no_reconnect_button_found",
            "modal_text": info.get("modal_text"),
        }

    x = info["center"]["x"]
    y = info["center"]["y"]
    try:
        await page.mouse.click(x, y)
    except Exception as e:
        audit.log("session_modal.click_failed",
                  error_type=type(e).__name__, error=str(e))
        return {
            "present": True, "clicked": False,
            "reason": f"click_error: {type(e).__name__}: {e}",
            "modal_text": info.get("modal_text"),
        }

    # Give TV time to reconnect + dismiss the modal. 1.5s is typical;
    # slower links may take longer but the next CLI action will find
    # residue if so.
    await page.wait_for_timeout(1500)
    residual = await detect_session_modal(page)
    dismissed = residual is None

    audit.log("session_modal.reconnect_clicked",
              modal_text=info.get("modal_text"),
              button_text=info.get("button_text"),
              x=x, y=y, dismissed=dismissed)

    return {
        "present": True,
        "clicked": True,
        "modal_dismissed": dismissed,
        "button_text": info.get("button_text"),
        "click_coords": {"x": x, "y": y},
        "modal_text": info.get("modal_text"),
    }
