"""Drive the claude.ai web UI to analyze a chart screenshot.

For users with a Claude subscription but no API key. Same prompt as
`_call_anthropic`, just delivered through the browser instead of the API.

Flow:
  1. Open claude.ai/new in a new tab of the CDP-attached Chrome.
  2. Attach the screenshot via the hidden <input type="file">.
  3. Wait for the attachment thumbnail to render (not a fixed sleep —
     polls for an <img alt="<filename>"> to appear, so we never send
     before the upload finishes).
  4. Paste the combined system + user prompt into the TipTap composer
     via clipboard.
  5. Click "Send message".
  6. Wait for streaming to finish — Stop button disappears + 1.2s of
     unchanged last-response text.
  7. Scrape the last Claude response's innerText from
     `.font-claude-response` (multi-paragraph safe, and distinct from
     user messages which use `!font-user-message`).
  8. Sniff for common out-of-band states (rate limit, "I don't see an
     image") *before* returning, so the caller gets a clear error
     instead of a misleading JSON-parse failure.

Requires the user's real Chrome to be running with CDP on 9222 AND
already signed into claude.ai. If the composer doesn't appear within
15s, we assume not-signed-in and surface a clear error.

Selectors discovered via live DOM probes on 2026-04-19; claude.ai
occasionally rotates class hashes so we match on aria-label, data-testid,
and stable class substrings where possible.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeoutError

from session import tv_context  # top-level module in tradingview/

from .lib import audit

CLAUDE_URL = "https://claude.ai/new"

SEL_COMPOSER = '[contenteditable="true"][aria-label="Write your prompt to Claude"]'
SEL_FILE_INPUT = 'input[type="file"]#chat-input-file-upload-onpage'
SEL_SEND_BUTTON = 'button[aria-label="Send message"]'
SEL_STOP_BUTTON = 'button[aria-label="Stop response"]'
SEL_MODEL_BUTTON = '[data-testid="model-selector-dropdown"]'
# Menu items in the model-selector dropdown — the three main models
# render as menuitemradio (vs menuitem for the "Adaptive thinking"
# toggle and "More models" submenu).
SEL_MODEL_MENUITEM = '[role="menuitemradio"]'
# The whole response container — div wrapping all <p>s for a given
# answer. Explicitly NOT `font-claude-response-body` (the inner <p>)
# because long answers are split across multiple <p>s. Explicitly NOT
# a generic [data-testid="message"] either — user messages use
# `!font-user-message`, which would make `.last` ambiguous.
SEL_CLAUDE_RESPONSE = '.font-claude-response'

# Out-of-band states that return text-shaped-but-not-JSON. Kept narrow
# to avoid false positives on legitimate answers that happen to contain
# the trigger words. A match here short-circuits the parse step with a
# clear error, so the UI surfaces the actual cause rather than a
# generic "invalid JSON" message. Order matters — first match wins.
_OOB_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:out of|you[''`]?ve reached.*?)\s*(?:free\s*)?messages?", re.I),
     "claude.ai message limit hit — wait for the reset window or switch provider"),
    (re.compile(r"upgrade to (?:claude )?(?:pro|max|team|enterprise)", re.I),
     "response gated behind a higher Claude subscription tier"),
    (re.compile(r"I don[''`]?t see (?:an |any )?(?:image|attachment|chart|screenshot)", re.I),
     "chart screenshot didn't attach before send — likely a network / timing issue"),
    (re.compile(r"claude\.ai (?:is|was)\s+(?:temporarily\s+)?unavailable", re.I),
     "claude.ai is currently unavailable — try again in a minute"),
]


def _pbcopy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


# claude.ai's markdown renderer applies typographic substitutions
# (Smartypants-style) on prose — straight quotes become curly, double
# hyphens become em-dashes, etc. When we scrape `.font-claude-response`
# via innerText, we get the *rendered* characters. If the model meant
# to emit `"rationale"` with a straight apostrophe inside, we now see a
# curly one (U+2019) and the downstream JSON parser breaks at that byte.
# Map the common typographic variants back to their ASCII equivalents
# before returning. JSON structural quotes (`"{`, `}"`, etc.) are not
# affected because Claude emits JSON inside a monospace / code context
# where the renderer leaves them alone; these substitutions only touch
# the prose regions.
_SMART_QUOTE_MAP = str.maketrans({
    "\u201C": '"',  # left double quotation
    "\u201D": '"',  # right double quotation
    "\u2018": "'",  # left single quotation
    "\u2019": "'",  # right single quotation / apostrophe
    "\u2032": "'",  # prime
    "\u2033": '"',  # double prime
    # Em/en dashes and ellipsis are valid inside JSON strings so we
    # leave them alone; they're not syntax breakers.
})


def _normalize_text(s: str) -> str:
    """Undo claude.ai's typographic substitutions so the downstream
    JSON parser doesn't choke on a curly apostrophe inside the
    rationale."""
    return s.translate(_SMART_QUOTE_MAP)


async def _select_model(page: Page, model_name: str) -> None:
    """Open the Claude model dropdown and pick the first menu item whose
    text matches `model_name` (case-insensitive substring). No-op if
    the model button already shows the requested model.

    `model_name` is expected to be a display name like "Sonnet 4.6" or
    "Opus 4.7". The `_resolve_model` layer in analyze_mtf.py normalizes
    aliases ("sonnet", "opus", "haiku") into these display names before
    they get here, so miss = real problem, not a typo."""
    button = page.locator(SEL_MODEL_BUTTON).first
    try:
        current = (await button.inner_text()) or ""
    except Exception:
        current = ""
    if model_name.lower() in current.lower():
        audit.log("claude_web.model_already_selected", model=model_name)
        return

    audit.log("claude_web.model_select_start", model=model_name, current=current)
    await button.click()
    try:
        await page.wait_for_selector(SEL_MODEL_MENUITEM, state="visible", timeout=3000)
    except PWTimeoutError:
        # Menu didn't open — close any stray overlay and bail.
        await page.keyboard.press("Escape")
        raise RuntimeError("Claude model dropdown didn't open") from None

    items = page.locator(SEL_MODEL_MENUITEM)
    count = await items.count()
    target = model_name.lower()
    for i in range(count):
        item = items.nth(i)
        text = (await item.inner_text()) or ""
        if target in text.lower():
            await item.click()
            # Give the UI a beat to close the menu and re-render the
            # button label before we continue.
            await page.wait_for_timeout(400)
            audit.log("claude_web.model_selected", model=model_name)
            return

    await page.keyboard.press("Escape")
    raise RuntimeError(
        f"Claude model matching {model_name!r} not found in dropdown. "
        f"Your tier may not have access — try a smaller model."
    )


async def _last_message_text(page: Page) -> str:
    """Return the innerText of the last Claude response, or ''.

    `.font-claude-response` is the DIV wrapping the whole answer, so
    `inner_text()` covers multi-paragraph responses. `.last` grabs the
    most recent response in case the conversation ever has prior turns
    (we always go to /new, but cheap guard)."""
    try:
        loc = page.locator(SEL_CLAUDE_RESPONSE).last
        if await loc.count() > 0:
            txt = await loc.inner_text()
            if txt and txt.strip():
                return txt
    except Exception:
        pass
    return ""


async def _wait_for_response_complete(page: Page, timeout_s: int) -> None:
    """Block until the in-flight response finishes streaming.

    Two-phase check:
      Phase 1 — wait up to 10s for the Stop button to materialize. That
      confirms the message was actually sent and generation started.
      Missing it is survivable (sometimes the button is already gone for
      very short responses).

      Phase 2 — wait for the Stop button to disappear, plus a 1.2s
      stabilization window where last-message-text doesn't change. The
      stabilization catches the case where the button flickers invisible
      between render frames — without it we'd occasionally return with
      a mid-sentence response."""
    deadline = time.time() + timeout_s
    try:
        await page.wait_for_selector(SEL_STOP_BUTTON, state="visible", timeout=10_000)
    except PWTimeoutError:
        pass  # fast response; fall through

    while time.time() < deadline:
        try:
            stop_count = await page.locator(SEL_STOP_BUTTON).count()
            stop_visible = (
                stop_count > 0
                and await page.locator(SEL_STOP_BUTTON).first.is_visible()
            )
        except Exception:
            stop_visible = False

        if not stop_visible:
            t1 = await _last_message_text(page)
            await page.wait_for_timeout(1200)
            t2 = await _last_message_text(page)
            if t1 and t1 == t2:
                return
        await page.wait_for_timeout(500)

    raise PWTimeoutError(f"claude.ai response did not finish within {timeout_s}s")


def _check_oob(text: str) -> None:
    """Raise a clear error if `text` matches a known out-of-band state.

    Called right before returning the scraped text to the caller, so the
    UI sees e.g. 'claude.ai message limit hit' instead of 'LLM returned
    invalid JSON'. Patterns are narrow by design — false positives here
    would block legitimate analyses."""
    for pat, reason in _OOB_PATTERNS:
        if pat.search(text):
            head = text[:240].replace("\n", " ").strip()
            raise RuntimeError(f"{reason}. Response head: {head!r}")


async def analyze_via_claude_web(
    image_path: str,
    system_prompt: str,
    user_text: str,
    *,
    model: str | None = None,
    timeout_s: int = 180,
) -> tuple[str, dict, float]:
    """Send `image_path` + prompt to claude.ai and return the raw response.

    `model` — display name from the model-selector dropdown, e.g.
    "Sonnet 4.6", "Opus 4.7", "Haiku 4.5". None keeps whatever model
    is currently selected in claude.ai.

    Returns `(raw_text, usage_dict, cost_usd)`. claude.ai doesn't expose
    token counts or cost — usage is zeroed, cost is 0.0 (bundled in the
    subscription). Raises on upload / send / timeout / OOB failures.
    """
    if not Path(image_path).exists():
        raise FileNotFoundError(image_path)
    basename = Path(image_path).name

    # Web UI has no separate system field — prepend it with a clear
    # separator so Claude still picks up the "return JSON only" framing.
    combined = f"{system_prompt}\n\n---\n\n{user_text}"

    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        audit.log("claude_web.start", image=image_path)
        try:
            await page.goto(CLAUDE_URL, wait_until="domcontentloaded")

            # If composer doesn't render in 15s we're almost certainly
            # not signed in — inline auth modal, /oauth redirect, or
            # claude.ai being down. Surface a clear error instead of
            # letting the later code fail on a missing element.
            try:
                await page.wait_for_selector(SEL_COMPOSER, state="visible", timeout=15_000)
            except PWTimeoutError:
                raise RuntimeError(
                    "claude.ai composer didn't appear within 15s — "
                    "probably not signed in. Open https://claude.ai in "
                    "the automation Chrome, sign in, then retry."
                ) from None

            if "login" in page.url.lower() or "oauth" in page.url.lower():
                raise RuntimeError(
                    "claude.ai redirected to an auth flow. Sign in once "
                    "in the automation Chrome, then retry."
                )

            # Model selection happens before upload so any subscription-
            # tier errors surface immediately rather than after a long
            # upload.
            if model:
                await _select_model(page, model)

            audit.log("claude_web.upload_start", image=image_path)
            await page.locator(SEL_FILE_INPUT).first.set_input_files(image_path)

            # Poll for the attachment thumbnail — an <img alt="<basename>">
            # rendered inside the composer footer. 30s ceiling handles
            # large PNGs on flaky networks. Without this, on a slow link
            # we'd send the prompt before the image finishes uploading
            # → Claude responds "I don't see an image" → parse failure.
            # Escape embedded double-quotes in the filename just in case
            # (our basenames are alphanum + `._-`, but harmless belt).
            alt_sel = f'img[alt="{basename.replace(chr(92), chr(92)*2).replace(chr(34), chr(92) + chr(34))}"]'
            try:
                await page.wait_for_selector(alt_sel, state="visible", timeout=30_000)
            except PWTimeoutError:
                raise RuntimeError(
                    f"attachment thumbnail for {basename} never appeared "
                    "within 30s — upload likely failed."
                ) from None
            audit.log("claude_web.upload_done")

            _pbcopy(combined)
            composer = page.locator(SEL_COMPOSER).first
            await composer.click()
            await page.keyboard.press("ControlOrMeta+v")
            await page.wait_for_timeout(600)

            audit.log("claude_web.send")
            send = page.locator(SEL_SEND_BUTTON).first
            await send.wait_for(state="visible", timeout=5000)
            await send.click()

            await _wait_for_response_complete(page, timeout_s=timeout_s)

            text = await _last_message_text(page)
            if not text:
                raise RuntimeError(
                    "claude.ai response was empty — `.font-claude-response` "
                    "selector may be out of date."
                )

            text = _normalize_text(text)

            # Final gate: convert OOB states into clear errors BEFORE
            # the downstream JSON parser tries to make sense of them.
            _check_oob(text)

            audit.log("claude_web.done", chars=len(text))
            return text, {"input_tokens": 0, "output_tokens": 0}, 0.0
        finally:
            try:
                await page.close()
            except Exception:
                pass


async def analyze_via_claude_web_multi(
    image_paths: list[str],
    system_prompt: str,
    user_text: str,
    *,
    model: str | None = None,
    timeout_s: int = 300,
) -> tuple[str, dict, float]:
    """Multi-image variant for deep analysis.

    Uploads N images (claude.ai's file input has `multiple` set) and
    waits for every per-file thumbnail to render before sending. Same
    OOB-sniffing and smart-quote-normalization gates as the single-image
    flow — just looped over multiple thumbnails.

    Longer default timeout (300s) because deep analysis with 9 images
    is genuinely slow — Opus on 9 images can think for 60-90s. The
    single-image default (180s) would time out on deep runs.
    """
    missing = [p for p in image_paths if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(f"images not found: {missing}")
    if not image_paths:
        raise ValueError("no images provided")

    combined = f"{system_prompt}\n\n---\n\n{user_text}"

    async with tv_context(headless=False) as ctx:
        page = await ctx.new_page()
        audit.log("claude_web.start", images=len(image_paths))
        try:
            await page.goto(CLAUDE_URL, wait_until="domcontentloaded")

            try:
                await page.wait_for_selector(SEL_COMPOSER, state="visible", timeout=15_000)
            except PWTimeoutError:
                raise RuntimeError(
                    "claude.ai composer didn't appear within 15s — "
                    "probably not signed in."
                ) from None

            if "login" in page.url.lower() or "oauth" in page.url.lower():
                raise RuntimeError(
                    "claude.ai redirected to an auth flow. Sign in once "
                    "in the automation Chrome, then retry."
                )

            if model:
                await _select_model(page, model)

            audit.log("claude_web.upload_start", count=len(image_paths))
            # set_input_files accepts a list — one call attaches them all.
            await page.locator(SEL_FILE_INPUT).first.set_input_files(image_paths)

            # Poll for every thumbnail. If claude.ai silently enforces a
            # per-message attachment cap below len(image_paths), one of
            # these waits will time out with a clear "missing thumbnail"
            # message instead of letting us send an incomplete attachment
            # set.
            for p in image_paths:
                basename = Path(p).name
                alt_sel = (
                    f'img[alt="{basename.replace(chr(92), chr(92)*2).replace(chr(34), chr(92) + chr(34))}"]'
                )
                try:
                    await page.wait_for_selector(alt_sel, state="visible", timeout=30_000)
                except PWTimeoutError:
                    raise RuntimeError(
                        f"attachment thumbnail for {basename} never "
                        f"appeared — claude.ai may have rejected part of "
                        f"the {len(image_paths)}-image upload (per-message "
                        f"limit?)."
                    ) from None
            audit.log("claude_web.upload_done", count=len(image_paths))

            _pbcopy(combined)
            composer = page.locator(SEL_COMPOSER).first
            await composer.click()
            await page.keyboard.press("ControlOrMeta+v")
            await page.wait_for_timeout(600)

            audit.log("claude_web.send")
            send = page.locator(SEL_SEND_BUTTON).first
            await send.wait_for(state="visible", timeout=5000)
            await send.click()

            await _wait_for_response_complete(page, timeout_s=timeout_s)

            text = await _last_message_text(page)
            if not text:
                raise RuntimeError(
                    "claude.ai response was empty — selector may be out of date."
                )
            text = _normalize_text(text)
            _check_oob(text)
            audit.log("claude_web.done", chars=len(text))
            return text, {"input_tokens": 0, "output_tokens": 0}, 0.0
        finally:
            try:
                await page.close()
            except Exception:
                pass
