"""Selector healing — when a stored selector stops resolving, suggest a
replacement by fuzzy-matching the original's identifying hints against
the current DOM.

The intuition: TradingView's hashed class suffixes rotate occasionally
and stable identifiers (data-name, aria-label, id) sometimes get
renamed. When `selectors.yaml` drifts from reality, the recovery
historically required a probe re-run + manual selector update.

This module shortcuts that loop:

  1. Parse the failed selector → extract identifying hints
     (data-name string, aria-label string, id, text).
  2. Scan the current DOM for elements that fuzzy-match those hints.
     Score each candidate by closeness — exact match scores high,
     "data-name CONTAINS the original" scores medium, etc.
  3. Return the ranked list. Caller (the `tv heal` CLI, or in the
     future an in-process retry hook) picks the top candidate and
     emits a YAML snippet for review/paste.

We deliberately do NOT auto-modify selectors.yaml — auto-pollution
is the failure mode that makes this kind of system fragile. Healed
selectors are a SUGGESTION; the human/LLM in the loop applies them.
"""

from __future__ import annotations

import re
from typing import Any

from playwright.async_api import Page


# Patterns we know how to extract from a selector. Each captures the
# value following a stable identifier convention (data-name, aria-label,
# id, has-text). Order matters: more-specific patterns first.
_HINT_PATTERNS = [
    ("data_name", re.compile(r'\[data-name=["\']([^"\']+)["\']\]')),
    ("data_name", re.compile(r'\[data-name\^=["\']([^"\']+)["\']\]')),  # ^=
    ("aria_label", re.compile(r'\[aria-label=["\']([^"\']+)["\']\]')),
    ("aria_label", re.compile(r'\[aria-label\*=["\']([^"\']+)["\']\]')),  # *=
    ("id", re.compile(r'#([a-zA-Z][\w-]*)')),
    ("text", re.compile(r':(?:has-text|text-is)\(["\']([^"\']+)["\']\)')),
    ("data_qa_id", re.compile(r'\[data-qa-id=["\']([^"\']+)["\']\]')),
    ("role", re.compile(r'\[role=["\']([^"\']+)["\']\]')),
]


def extract_hints(selector: str) -> dict[str, str]:
    """Parse a CSS selector and return a dict of identifying hints.

    Multiple matches of the same key keep the FIRST hit (most-specific
    pattern wins). Selector tokens we don't understand (class fragments,
    nth-of-type, etc.) are ignored — they're rarely useful for fuzzy
    matching anyway."""
    out: dict[str, str] = {}
    for key, pat in _HINT_PATTERNS:
        if key in out:
            continue
        m = pat.search(selector)
        if m:
            out[key] = m.group(1)
    return out


# JS scorer — kept inline as a string template so we can pass hints
# through evaluate(). Shared by find_candidates regardless of scope.
_SCORER_JS = r"""
({hints, scopeSel}) => {
    const root = scopeSel ? document.querySelector(scopeSel) : document.body;
    if (!root) return [];

    const dnHint  = (hints.data_name  || '').toLowerCase();
    const alHint  = (hints.aria_label || '').toLowerCase();
    const idHint  = (hints.id         || '').toLowerCase();
    const txtHint = (hints.text       || '').toLowerCase();
    const qaHint  = (hints.data_qa_id || '').toLowerCase();
    const roleHint= (hints.role       || '').toLowerCase();

    const out = [];
    root.querySelectorAll('*').forEach(el => {
        const r = el.getBoundingClientRect();
        // Skip 0-area + off-screen elements (TV's translateX(-999999)
        // overflow trick). A tiny tolerance for elements about to mount.
        if (r.width < 2 || r.height < 2) return;
        if (r.x + r.width < 0 || r.y + r.height < 0) return;

        const dn   = (el.getAttribute('data-name') || '').toLowerCase();
        const al   = (el.getAttribute('aria-label') || '').toLowerCase();
        const id   = (el.id || '').toLowerCase();
        const qa   = (el.getAttribute('data-qa-id') || '').toLowerCase();
        const role = (el.getAttribute('role') || '').toLowerCase();
        const txt  = (el.innerText || '').trim().toLowerCase();

        let score = 0;
        const matches = [];

        // data-name: highest signal in TV.
        if (dnHint) {
            if (dn === dnHint) { score += 100; matches.push('data-name=='); }
            else if (dn && dn.includes(dnHint)) { score += 65; matches.push('data-name⊇'); }
            else if (dn && dnHint.includes(dn) && dn.length >= 3) {
                score += 45; matches.push('data-name⊆');
            }
        }
        // aria-label: stable for accessibility, second-tier signal.
        if (alHint) {
            if (al === alHint) { score += 80; matches.push('aria-label=='); }
            else if (al && al.includes(alHint)) { score += 50; matches.push('aria-label⊇'); }
            else if (al && alHint.includes(al) && al.length >= 3) {
                score += 30; matches.push('aria-label⊆');
            }
        }
        // id: stable when present.
        if (idHint) {
            if (id === idHint) { score += 95; matches.push('id=='); }
            else if (id && id.includes(idHint)) { score += 60; matches.push('id⊇'); }
        }
        // data-qa-id: TV uses this for chart legend etc.
        if (qaHint) {
            if (qa === qaHint) { score += 100; matches.push('data-qa-id=='); }
            else if (qa && qa.includes(qaHint)) { score += 60; matches.push('data-qa-id⊇'); }
        }
        // text: weakest stable signal.
        if (txtHint) {
            if (txt === txtHint) { score += 35; matches.push('text=='); }
            else if (txt && txt.includes(txtHint) && txt.length < 200) {
                score += 18; matches.push('text⊇');
            }
        }
        // role: tie-breaker only — many elements share roles.
        if (roleHint && role === roleHint && score > 0) {
            score += 10; matches.push('role==');
        }

        if (score === 0) return;

        // Build the best-guess replacement selector for this element.
        let suggested = null;
        const dnRaw = el.getAttribute('data-name');
        const alRaw = el.getAttribute('aria-label');
        const idRaw = el.id;
        const qaRaw = el.getAttribute('data-qa-id');
        if (dnRaw)      suggested = `[data-name="${dnRaw}"]`;
        else if (qaRaw) suggested = `[data-qa-id="${qaRaw}"]`;
        else if (idRaw) suggested = `#${idRaw}`;
        else if (alRaw) suggested = `[aria-label="${alRaw.replace(/"/g, '\\"')}"]`;

        out.push({
            score,
            matches,
            tag: el.tagName,
            data_name: el.getAttribute('data-name'),
            aria_label: el.getAttribute('aria-label'),
            id: el.id || null,
            data_qa_id: el.getAttribute('data-qa-id'),
            role: el.getAttribute('role'),
            text: (el.innerText || '').trim().slice(0, 60).replace(/\s+/g, ' '),
            rect: {
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
            },
            suggested_selector: suggested,
        });
    });
    out.sort((a, b) => b.score - a.score);
    // Cap at 10 — beyond this, signal-to-noise drops sharply.
    return out.slice(0, 10);
}
"""


async def find_candidates(
    page: Page,
    hints: dict[str, str],
    *,
    scope_selector: str | None = None,
) -> list[dict[str, Any]]:
    """Scan the page for elements that fuzzy-match the given hints.

    `hints` keys: data_name / aria_label / id / data_qa_id / text / role.
    `scope_selector` (optional CSS) restricts the search — useful when
    you know the element is inside a particular panel (e.g. scope the
    healer to `'div[class*="screenerContainer-"]'` for a screener
    selector).

    Returns up to 10 candidates ranked by score (highest first). Each
    has `suggested_selector`, ready to paste into selectors.yaml as a
    new fallback under the same role."""
    if not hints:
        return []
    return await page.evaluate(
        _SCORER_JS,
        {"hints": hints, "scopeSel": scope_selector},
    )


async def crosscheck_with_api(
    page: Page, dom_role: str, dom_value: Any,
) -> dict[str, Any]:
    """Compare a DOM-derived value to TV's JS API ground truth.

    Distinguishes "selector drifted, but state is correct" from "state
    actually changed". When the DOM read says one thing but the API
    says another, the API is authoritative — which means the DOM-based
    selector is reading something stale or wrong.

    Roles supported:
      - `symbol` — DOM title parse vs `chart.symbol()` / `symbolExt().ticker`
      - `resolution` — DOM toolbar text vs `chart.resolution()`
      - `replay_active` — DOM strip presence vs `replayApi.isReplayStarted()`

    Returns `{role, dom_value, api_value, agree, api_available, verdict}`
    where `verdict` is one of `consensus` (both agree), `dom_drift`
    (api says dom is wrong), `api_unreachable` (no comparison possible).
    """
    from .. import replay_api

    if not await replay_api.api_available(page):
        return {"role": dom_role, "dom_value": dom_value, "api_value": None,
                "agree": None, "api_available": False,
                "verdict": "api_unreachable"}

    api_value: Any = None
    if dom_role == "symbol":
        ext = await replay_api.chart_symbol_ext(page)
        api_value = (ext or {}).get("ticker") if ext else None
        if not api_value:
            st = await replay_api.chart_state(page)
            api_value = (st or {}).get("symbol")
    elif dom_role == "resolution":
        st = await replay_api.chart_state(page)
        api_value = (st or {}).get("resolution")
    elif dom_role == "replay_active":
        api_value = await replay_api.is_replay_started(page)
    else:
        return {"role": dom_role, "dom_value": dom_value, "api_value": None,
                "agree": None, "api_available": True,
                "verdict": "unsupported_role"}

    agree = (api_value == dom_value)
    return {
        "role": dom_role, "dom_value": dom_value, "api_value": api_value,
        "agree": agree, "api_available": True,
        "verdict": "consensus" if agree else "dom_drift",
    }
