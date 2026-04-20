"""Probe the Bar Replay feature.

Purpose: catalog selectors for (a) the toolbar button that activates
Replay mode and (b) the playback control strip that renders once
Replay is active — play/pause, step forward/back, jump-to date, speed
selector, and the exit-replay button.

Replay's playback strip only exists in the DOM *after* activation, so
this probe does a brief activate → catalog → deactivate cycle. It
attempts to leave the chart in exactly the state it started in.

Run:
    cd tradingview && .venv/bin/python -m tv_automation.probes.probe_replay
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from preflight import ensure_automation_chromium
from session import tv_context

from ..chart import _find_or_open_chart

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


_CATALOG_JS = r"""(scope) => {
    // Catalog every button, icon-button, and labelled control under the
    // given scope. Returns a flat list of stable anchor attributes —
    // data-name, aria-label, innerText, role — plus visibility so we can
    // filter offscreen / hidden controls at the caller.
    const root = scope ? document.querySelector(scope) : document.body;
    if (!root) return { scope, found: false, buttons: [], inputs: [], other: [] };

    const out = { scope, found: true, buttons: [], inputs: [], other: [] };

    root.querySelectorAll('button, [role="button"]').forEach(b => {
        // Icon-only buttons have no aria/data-name/text, so capture the
        // SVG <use> href — TV uses sprite-refs like "#replay-play" which
        // are stable across builds.
        const use = b.querySelector('use, symbol');
        const iconHref = use ? (use.getAttribute('href')
                              || use.getAttribute('xlink:href')) : null;
        const rect = b.getBoundingClientRect();
        out.buttons.push({
            tag: b.tagName.toLowerCase(),
            dataName: b.getAttribute('data-name'),
            ariaLabel: b.getAttribute('aria-label'),
            title: b.getAttribute('title'),
            text: (b.innerText || '').trim().slice(0, 80),
            role: b.getAttribute('role'),
            iconHref: iconHref,
            outerHTMLSnippet: (b.outerHTML || '').slice(0, 180),
            xy: { x: Math.round(rect.x), y: Math.round(rect.y),
                  w: Math.round(rect.width), h: Math.round(rect.height) },
            visible: !!(b.offsetWidth || b.offsetHeight),
            disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
        });
    });

    root.querySelectorAll('input, [contenteditable="true"]').forEach(inp => {
        out.inputs.push({
            tag: inp.tagName.toLowerCase(),
            type: inp.type || null,
            name: inp.name || null,
            dataName: inp.getAttribute('data-name'),
            ariaLabel: inp.getAttribute('aria-label'),
            placeholder: inp.placeholder || null,
            value: (inp.value || inp.textContent || '').slice(0, 60),
        });
    });

    // Also catalog elements that look like controls but aren't <button>:
    // TV occasionally uses <div data-name="..."> with click handlers.
    root.querySelectorAll('[data-name]').forEach(el => {
        if (el.matches('button, input')) return;
        const name = el.getAttribute('data-name');
        if (!name) return;
        // Skip container-ish names to keep noise low.
        if (name.length < 3) return;
        out.other.push({
            tag: el.tagName.toLowerCase(),
            dataName: name,
            ariaLabel: el.getAttribute('aria-label'),
            title: el.getAttribute('title'),
            text: (el.innerText || '').trim().slice(0, 60),
            visible: !!(el.offsetWidth || el.offsetHeight),
        });
    });

    return out;
}"""


async def _catalog(page, scope: str | None) -> dict:
    return await page.evaluate(_CATALOG_JS, scope)


async def _find_replay_toggle(page):
    """Return the locator for TV's Bar Replay toggle button in the top
    toolbar. Probes the usual stable anchors first; falls back to text
    search if TV renamed them. Returns None if nothing plausible."""
    # TradingView's current markup: `button[aria-label="Bar replay"]`
    # (lowercase "replay") in the chart top-toolbar. No data-name anchor
    # — the aria-label is the only stable hook. Two instances often
    # render (responsive-layout variants); .first + .is_visible() picks
    # whichever is on screen.
    candidates = [
        'button[aria-label="Bar replay"]',
        'button[aria-label*="replay" i]',
        'button[aria-label*="Replay" i]',
        '[data-name="replay"]',
        '[data-name="bar-replay"]',
        'button[title*="Replay" i]',
    ]
    # TV renders two DOM copies of the Replay button (narrow + wide
    # responsive variants); only one is visible at a time. `.first`
    # would pick the hidden duplicate when it comes earlier in DOM
    # order — so walk all matches and return the first that's actually
    # visible.
    for sel in candidates:
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(n):
            item = loc.nth(i)
            try:
                if await item.is_visible():
                    return item, sel
            except Exception:
                continue
    return None, None


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(1500)

        snapshot: dict = {
            "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "url": page.url,
            "pre_activation": {},
            "post_activation": {},
            "activation_selector": None,
            "notes": [],
        }

        # Pass 1 — find the Replay button in the top toolbar and catalog
        # the whole top-toolbar cluster so we have a backup if the usual
        # data-name anchor is missing.
        loc, used_sel = await _find_replay_toggle(page)
        snapshot["activation_selector"] = used_sel

        # Body-wide: every element whose data-name / aria-label / title /
        # innerText mentions "replay" (case-insensitive). Plus every
        # button that lives in the top 80px of the viewport — that's
        # where the chart toolbar sits regardless of which wrapper class
        # TV is using this week.
        snapshot["pre_activation"]["replay_refs_bodywide"] = await page.evaluate(
            r"""() => {
                const out = [];
                document.querySelectorAll('*').forEach(el => {
                    const dn = el.getAttribute && el.getAttribute('data-name');
                    const al = el.getAttribute && el.getAttribute('aria-label');
                    const tt = el.getAttribute && el.getAttribute('title');
                    const txt = (el.innerText || '').trim();
                    const hit = (s) => s && /replay|bar.?replay|playback/i.test(s);
                    if (hit(dn) || hit(al) || hit(tt)
                        || (txt.length < 30 && hit(txt))) {
                        const rect = el.getBoundingClientRect();
                        out.push({
                            tag: el.tagName.toLowerCase(),
                            dataName: dn, ariaLabel: al, title: tt,
                            text: txt.slice(0, 60),
                            visible: !!(el.offsetWidth || el.offsetHeight),
                            xy: { x: Math.round(rect.x), y: Math.round(rect.y),
                                  w: Math.round(rect.width), h: Math.round(rect.height) },
                        });
                    }
                });
                return out;
            }"""
        )
        snapshot["pre_activation"]["top_strip_buttons"] = await page.evaluate(
            r"""() => {
                const out = [];
                document.querySelectorAll('button, [role="button"]').forEach(b => {
                    const rect = b.getBoundingClientRect();
                    // Top 80px: that's where the chart toolbar lives.
                    if (rect.y < 0 || rect.y > 80) return;
                    if (rect.width === 0 || rect.height === 0) return;
                    out.push({
                        tag: b.tagName.toLowerCase(),
                        dataName: b.getAttribute('data-name'),
                        ariaLabel: b.getAttribute('aria-label'),
                        title: b.getAttribute('title'),
                        text: (b.innerText || '').trim().slice(0, 60),
                        xy: { x: Math.round(rect.x), y: Math.round(rect.y),
                              w: Math.round(rect.width), h: Math.round(rect.height) },
                    });
                });
                out.sort((a, b) => a.xy.x - b.xy.x);
                return out;
            }"""
        )

        if not loc:
            snapshot["notes"].append(
                "Could not find a Replay toggle button via the usual "
                "anchors — inspect pre_activation.replay_refs_bodywide "
                "and top_strip_buttons for candidates."
            )
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            out_path = SNAPSHOT_DIR / f"replay-{ts}.json"
            out_path.write_text(json.dumps(snapshot, indent=2))
            print(f"[partial] Wrote snapshot to {out_path}", flush=True)
            print(flush=True)

            refs = snapshot["pre_activation"].get("replay_refs_bodywide", [])
            visible_refs = [r for r in refs if r.get("visible")]
            print(f"Elements mentioning 'replay' ({len(visible_refs)} visible):",
                  flush=True)
            for r in visible_refs[:20]:
                print(
                    f"  {r['tag']:8s}  data-name={r.get('dataName')!r:32s}  "
                    f"aria={r.get('ariaLabel')!r:28s}  text={r.get('text')!r}",
                    flush=True,
                )
            print(flush=True)

            top = snapshot["pre_activation"].get("top_strip_buttons", [])
            print(f"Top-strip buttons ({len(top)}):", flush=True)
            for b in top[:60]:
                print(
                    f"  x={b['xy']['x']:>4}  "
                    f"data-name={b.get('dataName')!r:28s}  "
                    f"aria={b.get('ariaLabel')!r:28s}  text={b.get('text')!r}",
                    flush=True,
                )
            return 1

        # Activate Replay. TV shows a ghost-bar overlay on the chart; the
        # playback strip (play/pause/step/exit) docks at the bottom.
        try:
            await loc.click(timeout=3000)
        except Exception as e:
            snapshot["notes"].append(f"activation click failed: {type(e).__name__}: {e}")
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            out_path = SNAPSHOT_DIR / f"replay-{ts}.json"
            out_path.write_text(json.dumps(snapshot, indent=2))
            print(f"[partial] Wrote snapshot to {out_path}", flush=True)
            return 1

        # Give the playback strip time to mount.
        await page.wait_for_timeout(1500)

        # Pass 2 — catalog the playback strip. TV's replay controls have
        # lived under a few different parent names across versions; probe
        # several scopes so we catch whichever is current.
        scopes = [
            '[data-name="replay-bottom-toolbar"]',  # current (2026-04)
            '[data-name="replay-tools"]',
            '[data-name="replay-controller"]',
            '[class*="replay" i]',
            '[class*="bar-replay" i]',
            '[data-name="bottom-toolbar"]',
        ]
        snapshot["post_activation"]["by_scope"] = {}
        for scope in scopes:
            cat = await _catalog(page, scope)
            if cat.get("found") and (cat["buttons"] or cat["other"]):
                snapshot["post_activation"]["by_scope"][scope] = cat

        # Full DFS walk of the replay-bottom-toolbar — regardless of tag.
        # TV often uses <div> with a click handler instead of <button>,
        # so a button-only query misses the play/pause/step targets.
        snapshot["post_activation"]["strip_tree"] = await page.evaluate(
            r"""() => {
                const root = document.querySelector('[data-name="replay-bottom-toolbar"]');
                if (!root) return { found: false, nodes: [] };
                const nodes = [];
                root.querySelectorAll('*').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    // Skip text-only / invisible / layout-wrapper nodes.
                    if (rect.width === 0 || rect.height === 0) return;
                    const use = el.querySelector('use, symbol');
                    const iconHref = use ? (use.getAttribute('href')
                                          || use.getAttribute('xlink:href')) : null;
                    const style = getComputedStyle(el);
                    nodes.push({
                        tag: el.tagName.toLowerCase(),
                        dataName: el.getAttribute('data-name'),
                        ariaLabel: el.getAttribute('aria-label'),
                        title: el.getAttribute('title'),
                        role: el.getAttribute('role'),
                        text: (el.innerText || '').trim().slice(0, 60),
                        cls: (el.getAttribute('class') || '').slice(0, 120),
                        iconHref,
                        cursor: style.cursor,
                        xy: { x: Math.round(rect.x), y: Math.round(rect.y),
                              w: Math.round(rect.width), h: Math.round(rect.height) },
                        outerHTMLSnippet: (el.outerHTML || '').slice(0, 240),
                    });
                });
                return { found: true, nodes };
            }"""
        )

        # Body-wide sweep of anything whose data-name or aria mentions
        # "replay" — catches controls rendered outside the expected
        # parent (TV sometimes docks pieces in the chart overlay).
        snapshot["post_activation"]["body_wide_replay_refs"] = await page.evaluate(
            r"""() => {
                const out = [];
                document.querySelectorAll('*').forEach(el => {
                    const dn = el.getAttribute && el.getAttribute('data-name');
                    const al = el.getAttribute && el.getAttribute('aria-label');
                    const tt = el.getAttribute && el.getAttribute('title');
                    const hit = (s) => s && /replay|bar.?replay|playback/i.test(s);
                    if (hit(dn) || hit(al) || hit(tt)) {
                        out.push({
                            tag: el.tagName.toLowerCase(),
                            dataName: dn, ariaLabel: al, title: tt,
                            text: (el.innerText || '').trim().slice(0, 60),
                            visible: !!(el.offsetWidth || el.offsetHeight),
                        });
                    }
                });
                return out;
            }"""
        )

        # Deactivate — click the same toggle again (TV's Replay button is
        # a toggle) to leave the chart in the state we found it.
        try:
            await loc.click(timeout=3000)
            snapshot["notes"].append("deactivated via toggle click")
        except Exception as e:
            snapshot["notes"].append(
                f"deactivation failed — chart may still be in Replay mode: "
                f"{type(e).__name__}: {e}"
            )

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"replay-{ts}.json"
        out_path.write_text(json.dumps(snapshot, indent=2))
        print(f"Wrote snapshot to {out_path}", flush=True)
        print(flush=True)

        # Summary to console — the useful stuff first so the tail is
        # legible without opening the JSON.
        print(f"Activation selector: {snapshot['activation_selector']!r}", flush=True)
        print(flush=True)

        body_refs = snapshot["post_activation"].get("body_wide_replay_refs", [])
        visible = [r for r in body_refs if r.get("visible")]
        print(f"Replay-tagged elements visible in body ({len(visible)}):", flush=True)
        for r in visible[:40]:
            print(
                f"  {r['tag']:8s}  data-name={r.get('dataName')!r:32s}  "
                f"aria={r.get('ariaLabel')!r:28s}  text={r.get('text')!r}",
                flush=True,
            )
        print(flush=True)

        for scope, cat in snapshot["post_activation"].get("by_scope", {}).items():
            btns = [b for b in cat.get("buttons", []) if b.get("visible")]
            if not btns:
                continue
            print(f"Under {scope!r} ({len(btns)} visible buttons):", flush=True)
            for b in btns[:20]:
                print(
                    f"  data-name={b.get('dataName')!r:30s}  "
                    f"aria={b.get('ariaLabel')!r:28s}  text={b.get('text')!r}",
                    flush=True,
                )
            print(flush=True)

        for note in snapshot["notes"]:
            print(f"NOTE: {note}", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
