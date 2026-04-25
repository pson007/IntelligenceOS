"""Drive the ChatGPT web UI to analyze a chart screenshot.

Parallel to claude_web.py — same "user has a subscription, not an API
key" angle, same attached-Chrome pattern, same prompt shape. Kept as
a separate module rather than a shared abstraction because the DOMs
differ enough that a shared interface would leak abstractions. When
both sites ship similar Markdown / typographic rendering, I still
want two clear sources of truth for which site's quirks live where.

Flow:
  1. Open chatgpt.com in a new tab of the CDP-attached Chrome.
  2. Select the desired model (Instant / Thinking) via the top-left
     dropdown.
  3. Attach the screenshot via the hidden `#upload-photos` input.
  4. Wait for the attachment chip to render (polled, not timed).
  5. Paste the combined system + user prompt into ProseMirror.
  6. Click the Send button.
  7. Wait for streaming to finish — Stop button disappears AND the
     last response text stabilizes for 1.2s.
  8. Scrape the last assistant bubble's innerText, normalize
     typographic substitutions, sniff for out-of-band states.

Selectors discovered via live DOM probe on 2026-04-19. ChatGPT rotates
class hashes frequently so everything here leans on stable attributes
(id, data-testid, aria-label).
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeoutError

from session import tv_context  # top-level module in tradingview/

from .lib import audit

CHATGPT_URL = "https://chatgpt.com/"

# ProseMirror composer — id is the stable anchor across UI rewrites.
SEL_COMPOSER = '#prompt-textarea'
# Hidden image-only file input — ChatGPT has three inputs (files,
# photos, camera). We want `upload-photos` because it's image/*-only
# and won't trigger document-parsing flows.
SEL_FILE_INPUT = 'input[type="file"]#upload-photos'

SEL_SEND_BUTTON = 'button[data-testid="send-button"]'
# Stop button appears mid-stream. Multiple possible aria-labels across
# versions — match any of them.
SEL_STOP_CANDIDATES = [
    'button[data-testid="stop-button"]',
    'button[aria-label="Stop generating"]',
    'button[aria-label="Stop streaming"]',
]

SEL_MODEL_BUTTON = '[data-testid="model-switcher-dropdown-button"]'
# Model menu items. "Instant" / "Thinking" show up on accounts with
# the new simplified picker. data-testid is stable enough; label text
# is what we match on (model_name passed in).
# ChatGPT has shipped both `menuitemradio` and `menuitem` for the model
# picker across recent builds; selector matches either so we don't break
# on dropdown role rotations.
SEL_MODEL_MENUITEM = '[role="menuitemradio"], [role="menuitem"]'

# Assistant message bubble. ChatGPT uses `data-message-author-role`
# which is the cleanest possible role signal — distinguishes user vs
# assistant unambiguously. The inner `.markdown` div has the rendered
# response body.
SEL_ASSISTANT_MESSAGE = '[data-message-author-role="assistant"]'
SEL_ASSISTANT_BODY_FALLBACKS = [
    '.markdown',                  # standard rendered body
    '[data-message-author-role="assistant"]',  # whole bubble if body not found
]

# Attachment thumbnail — after set_input_files, a preview appears
# in the composer. Match by file basename in the img alt attribute,
# same pattern as claude_web.

# Out-of-band states that return text-shaped-but-not-JSON. Narrow
# patterns only — false positives here would block legitimate answers.
_OOB_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"you[''`]?ve (?:reached|hit) (?:your )?(?:daily |hourly )?(?:usage |message )?limit", re.I),
     "ChatGPT usage limit hit — wait for the reset window or switch provider"),
    (re.compile(r"(?:exceeded|reached) (?:your )?(?:free|plus|daily) (?:tier|plan|limit)", re.I),
     "ChatGPT tier limit hit — try a different plan or provider"),
    (re.compile(r"I (?:can't|cannot) (?:help|assist|see|view|analyze|process) (?:this )?(?:image|chart|screenshot)", re.I),
     "ChatGPT couldn't see the chart — upload may not have landed"),
    (re.compile(r"something went wrong", re.I),
     "ChatGPT returned a generic error — retry or switch model"),
]


# Typographic substitutions — ChatGPT's markdown renderer also applies
# Smartypants-style substitutions (curly quotes, em-dashes) on prose.
# Same normalization as claude_web for the same reason: the downstream
# JSON parser doesn't know about U+2019.
_SMART_QUOTE_MAP = str.maketrans({
    "\u201C": '"',
    "\u201D": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u2032": "'",
    "\u2033": '"',
})


def _pbcopy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def _normalize_text(s: str) -> str:
    return s.translate(_SMART_QUOTE_MAP)


async def _last_message_text(page: Page) -> str:
    """Return the innerText of the last assistant message bubble.

    Prefers `.markdown` body (cleaner text, no copy/regenerate chrome)
    but falls back to the whole bubble if needed. `.last` picks the
    most recent — a fresh /new tab should have exactly one assistant
    reply, but the guard is free."""
    try:
        # Scope to the last assistant bubble first, then pull body
        last_bubble = page.locator(SEL_ASSISTANT_MESSAGE).last
        if await last_bubble.count() > 0:
            # Prefer .markdown scoped within the bubble
            body = last_bubble.locator('.markdown').first
            if await body.count() > 0:
                txt = await body.inner_text()
                if txt and txt.strip():
                    return txt
            # Fallback: the whole bubble (may include copy/regenerate chrome)
            txt = await last_bubble.inner_text()
            if txt and txt.strip():
                return txt
    except Exception:
        pass
    return ""


async def _stop_button_visible(page: Page) -> bool:
    for sel in SEL_STOP_CANDIDATES:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _wait_for_response_complete(page: Page, timeout_s: int) -> None:
    """Block until the in-flight response finishes.

    Same two-phase pattern as claude_web: wait up to 10s for any Stop
    button to appear (streaming started), then wait for it to disappear
    with a 1.2s text-stabilization fallback."""
    deadline = time.time() + timeout_s

    # Phase 1: wait for stop button (survivable if missed)
    p1_deadline = time.time() + 10
    while time.time() < p1_deadline:
        if await _stop_button_visible(page):
            break
        await page.wait_for_timeout(250)

    # Phase 2: wait for stop button to disappear + stabilization
    while time.time() < deadline:
        if not await _stop_button_visible(page):
            t1 = await _last_message_text(page)
            await page.wait_for_timeout(1200)
            t2 = await _last_message_text(page)
            if t1 and t1 == t2:
                return
        await page.wait_for_timeout(500)

    raise PWTimeoutError(f"ChatGPT response did not finish within {timeout_s}s")


def _check_oob(text: str) -> None:
    """Raise on known out-of-band states so the downstream parser gets
    a clear cause instead of 'invalid JSON'."""
    for pat, reason in _OOB_PATTERNS:
        if pat.search(text):
            head = text[:240].replace("\n", " ").strip()
            raise RuntimeError(f"{reason}. Response head: {head!r}")


async def _dismiss_chatgpt_overlays(page: Page) -> None:
    """Pre-flight cleanup for chatgpt.com — onboarding modals,
    "What's new" tooltips, prompt-suggestion popovers, and the
    occasional auth-renewal banner can sit on top of the model
    switcher and intercept clicks. Best-effort: Escape twice +
    click any visible Close/Got-it/Dismiss button."""
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(120)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(120)
        # Click any obvious dismiss button on a popover/banner.
        await page.evaluate(r"""() => {
            const selectors = [
                'button[aria-label="Close"]',
                'button[aria-label="Dismiss"]',
                'button[data-testid="close-button"]',
            ];
            for (const s of selectors) {
                const btn = document.querySelector(s);
                if (btn && btn.getBoundingClientRect().width > 0) {
                    btn.click();
                }
            }
            // Common "Got it" / "Continue" CTAs on first-run banners.
            const ctaTexts = ['got it', 'continue', 'okay', 'dismiss'];
            const buttons = Array.from(document.querySelectorAll('button'));
            for (const b of buttons) {
                const t = (b.innerText || '').trim().toLowerCase();
                if (ctaTexts.includes(t)
                    && b.getBoundingClientRect().width > 0
                    && b.getBoundingClientRect().width < 300) {
                    b.click();
                    break;
                }
            }
        }""")
    except Exception:
        pass


async def _select_model(page: Page, model_name: str) -> None:
    """Open the model dropdown and pick the menuitem whose text matches
    `model_name` (case-insensitive substring). No-op if the button
    already shows the requested model.

    ChatGPT's new picker has "Instant" and "Thinking" entries (plus
    Configure...). The selector accepts either literal label or short
    alias. `_resolve_model` in analyze_mtf normalizes aliases to the
    display label before this is called."""
    button = page.locator(SEL_MODEL_BUTTON).first
    try:
        current = (await button.inner_text()) or ""
    except Exception:
        current = ""
    if model_name.lower() in current.lower():
        audit.log("chatgpt_web.model_already_selected", model=model_name)
        return

    audit.log("chatgpt_web.model_select_start", model=model_name, current=current)

    # Pre-clear chatgpt-side popovers that intercept clicks on the
    # model switcher (onboarding banners, "what's new" tooltips, etc).
    await _dismiss_chatgpt_overlays(page)

    # Bring button into view + wait for it to stabilize before clicking.
    try:
        await button.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass

    # Try open + retry with progressive escalation. Slow chatgpt.com
    # loads OR an overlay still intercepting a soft click both surface
    # as "aria-expanded=false after click". Escalate to force-click +
    # JS-direct click on subsequent attempts.
    opened = False
    for attempt in range(3):
        try:
            if attempt == 0:
                await button.click(timeout=3000)
            elif attempt == 1:
                await button.click(force=True, timeout=3000)
            else:
                # JS-level click bypasses any pointer-event interception.
                await page.evaluate(
                    'document.querySelector('
                    + repr(SEL_MODEL_BUTTON) + ').click()'
                )
        except Exception as e:
            audit.log("chatgpt_web.model_button.click_fail",
                      attempt=attempt + 1, err=str(e))
            await _dismiss_chatgpt_overlays(page)
            continue
        try:
            await page.wait_for_selector(
                SEL_MODEL_MENUITEM, state="visible", timeout=6000,
            )
            opened = True
            break
        except PWTimeoutError:
            audit.log("chatgpt_web.model_dropdown.retry", attempt=attempt + 1)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(800)
            await _dismiss_chatgpt_overlays(page)

    if not opened:
        # Diagnostic: capture the menu region's DOM state so audit shows
        # what TV/ChatGPT actually rendered. Catches role-rotation drift.
        diag = await page.evaluate(r"""() => {
            const items = Array.from(document.querySelectorAll(
              '[role="menuitemradio"], [role="menuitem"], [role="option"]'
            ));
            return {
                count: items.length,
                roles: items.slice(0, 5).map(i => i.getAttribute('role')),
                texts: items.slice(0, 5).map(i => (i.innerText||'').trim().slice(0, 40)),
                btn_aria: document.querySelector(
                  '[data-testid="model-switcher-dropdown-button"]'
                )?.getAttribute('aria-expanded'),
                btn_text: (document.querySelector(
                  '[data-testid="model-switcher-dropdown-button"]'
                ) || {}).innerText || null,
            };
        }""")
        # Best-effort model switch — if the dropdown won't open after
        # all retries, ChatGPT's default model (usually Instant) is
        # almost always what the caller wanted anyway. Killing the whole
        # analyze for a model-switch failure when we can still use the
        # default is bad UX. Audit captures the failure so we can
        # diagnose patterns without breaking user flow.
        audit.log("chatgpt_web.model_dropdown.fail",
                  requested=model_name, attempts=3, **diag)
        return

    items = page.locator(SEL_MODEL_MENUITEM)
    count = await items.count()
    target = model_name.lower()
    for i in range(count):
        item = items.nth(i)
        text = ((await item.inner_text()) or "").lower()
        if target in text:
            await item.click()
            await page.wait_for_timeout(400)
            audit.log("chatgpt_web.model_selected", model=model_name)
            return

    await page.keyboard.press("Escape")
    raise RuntimeError(
        f"ChatGPT model matching {model_name!r} not found. "
        f"Your tier may not have access to that model."
    )


async def _wait_for_attachment(page: Page, basename: str, timeout_s: int = 30) -> None:
    """Poll for the attachment tile to render.

    ChatGPT wraps each uploaded file in a tile `<div>` with
    `aria-label="<basename>"` (the inner <img> has an empty alt and
    loads from `backend-api/estuary/content?id=file_...`). This differs
    from claude.ai where the filename lives in img alt — we learned it
    via live DOM probe on 2026-04-19. Matching on `[aria-label="..."]`
    catches both the tile div and the "Remove file N: ..." button, any
    of which is enough to confirm the upload landed.
    """
    # Defensive escape in case a future filename has quotes/backslashes.
    safe = basename.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))
    try:
        await page.wait_for_selector(
            f'[aria-label="{safe}"]',
            state="visible", timeout=timeout_s * 1000,
        )
        return
    except PWTimeoutError:
        pass

    raise RuntimeError(
        f"attachment tile for {basename} never appeared within "
        f"{timeout_s}s — upload likely failed. (Check chatgpt.com in "
        f"the attached Chrome — is the file visible in the composer?)"
    )


async def analyze_via_chatgpt_web(
    image_path: str,
    system_prompt: str,
    user_text: str,
    *,
    model: str | None = None,
    timeout_s: int = 180,
) -> tuple[str, dict, float]:
    """Send `image_path` + prompt to ChatGPT and return the raw response.

    `model` — display label from the dropdown. "Instant" or "Thinking"
    on modern accounts. None keeps whatever is currently selected.

    Returns `(raw_text, usage_dict, cost_usd)`. ChatGPT doesn't expose
    token counts or cost — usage zeroed, cost 0.0 (bundled in sub).
    """
    if not Path(image_path).exists():
        raise FileNotFoundError(image_path)
    basename = Path(image_path).name

    combined = f"{system_prompt}\n\n---\n\n{user_text}"

    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        audit.log("chatgpt_web.start", image=image_path)
        try:
            await page.goto(CHATGPT_URL, wait_until="domcontentloaded")

            try:
                await page.wait_for_selector(SEL_COMPOSER, state="visible", timeout=15_000)
            except PWTimeoutError:
                raise RuntimeError(
                    "ChatGPT composer didn't appear within 15s — "
                    "probably not signed in. Open https://chatgpt.com "
                    "in the automation Chrome, sign in, then retry."
                ) from None

            if any(x in page.url.lower() for x in ("login", "oauth", "auth0")):
                raise RuntimeError(
                    "ChatGPT redirected to an auth flow. Sign in once "
                    "in the automation Chrome, then retry."
                )

            if model:
                await _select_model(page, model)

            audit.log("chatgpt_web.upload_start", image=image_path)
            await page.locator(SEL_FILE_INPUT).first.set_input_files(image_path)
            await _wait_for_attachment(page, basename, timeout_s=30)
            audit.log("chatgpt_web.upload_done")

            _pbcopy(combined)
            composer = page.locator(SEL_COMPOSER).first
            await composer.click()
            await page.keyboard.press("ControlOrMeta+v")
            await page.wait_for_timeout(600)

            audit.log("chatgpt_web.send")
            send = page.locator(SEL_SEND_BUTTON).first
            await send.wait_for(state="visible", timeout=5000)
            await send.click()

            await _wait_for_response_complete(page, timeout_s=timeout_s)

            text = await _last_message_text(page)
            if not text:
                raise RuntimeError(
                    "ChatGPT response was empty — assistant-message "
                    "selector may be out of date."
                )
            text = _normalize_text(text)
            _check_oob(text)
            audit.log("chatgpt_web.done", chars=len(text))
            return text, {"input_tokens": 0, "output_tokens": 0}, 0.0
        finally:
            try:
                await page.close()
            except Exception:
                pass


async def analyze_via_chatgpt_web_multi(
    image_paths: list[str],
    system_prompt: str,
    user_text: str,
    *,
    model: str | None = None,
    timeout_s: int = 300,
) -> tuple[str, dict, float]:
    """Multi-image variant for deep analysis. Uploads N images, waits
    for every thumbnail, then sends the combined prompt.

    Longer default timeout (300s) — ChatGPT on 9 images with Thinking
    mode can deliberate for a while."""
    missing = [p for p in image_paths if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(f"images not found: {missing}")
    if not image_paths:
        raise ValueError("no images provided")

    combined = f"{system_prompt}\n\n---\n\n{user_text}"

    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        audit.log("chatgpt_web.start", images=len(image_paths))
        try:
            await page.goto(CHATGPT_URL, wait_until="domcontentloaded")

            try:
                await page.wait_for_selector(SEL_COMPOSER, state="visible", timeout=15_000)
            except PWTimeoutError:
                raise RuntimeError(
                    "ChatGPT composer didn't appear within 15s — "
                    "probably not signed in."
                ) from None

            if any(x in page.url.lower() for x in ("login", "oauth", "auth0")):
                raise RuntimeError(
                    "ChatGPT redirected to an auth flow. Sign in once "
                    "in the automation Chrome, then retry."
                )

            if model:
                await _select_model(page, model)

            audit.log("chatgpt_web.upload_start", count=len(image_paths))
            await page.locator(SEL_FILE_INPUT).first.set_input_files(image_paths)
            for p in image_paths:
                await _wait_for_attachment(page, Path(p).name, timeout_s=30)
            audit.log("chatgpt_web.upload_done", count=len(image_paths))

            _pbcopy(combined)
            composer = page.locator(SEL_COMPOSER).first
            await composer.click()
            await page.keyboard.press("ControlOrMeta+v")
            await page.wait_for_timeout(600)

            audit.log("chatgpt_web.send")
            send = page.locator(SEL_SEND_BUTTON).first
            await send.wait_for(state="visible", timeout=5000)
            await send.click()

            await _wait_for_response_complete(page, timeout_s=timeout_s)

            text = await _last_message_text(page)
            if not text:
                raise RuntimeError(
                    "ChatGPT response was empty — selector may be out of date."
                )
            text = _normalize_text(text)
            _check_oob(text)
            audit.log("chatgpt_web.done", chars=len(text))
            return text, {"input_tokens": 0, "output_tokens": 0}, 0.0
        finally:
            try:
                await page.close()
            except Exception:
                pass
