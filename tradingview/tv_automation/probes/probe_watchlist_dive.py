"""Second-pass watchlist probe — targets the row structure inside
`[data-name="tree"]` and re-captures the watchlists-button popup
without filtering multi-line items (named watchlists may be there).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from preflight import ensure_automation_chromium
from session import tv_context

from ..lib.context import find_or_open_chart

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await find_or_open_chart(ctx)
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(800)

        # Make sure the watchlist sidebar is open.
        base_btn = page.locator('[data-name="base"]').first
        if await base_btn.count() > 0:
            tree_loc = page.locator('[data-name="tree"]').first
            if await tree_loc.count() == 0 or not await tree_loc.is_visible():
                await base_btn.click()
                await page.wait_for_timeout(800)

        # 1. Row structure inside [data-name="tree"].
        rows = await page.evaluate(r"""() => {
            const tree = document.querySelector('[data-name="tree"]');
            if (!tree) return {found: false};
            // Walk every direct + indirect child and collect candidates
            // that are clearly "rows": short, full-width, with text.
            const all = Array.from(tree.querySelectorAll('*')).filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 100 && r.height > 12 && r.height < 80;
            });
            // Group by tag+class signature so we see the row pattern.
            const sample = [];
            const seenSig = new Map();
            all.forEach(el => {
                const cls = (el.className || '').toString();
                const sig = el.tagName + '|' + cls.split(' ').filter(c => c).slice(0, 3).join('.');
                if (!seenSig.has(sig)) seenSig.set(sig, 0);
                seenSig.set(sig, seenSig.get(sig) + 1);
                if (seenSig.get(sig) <= 2) {
                    const attrs = {};
                    Array.from(el.attributes).forEach(a => {
                        attrs[a.name] = a.value;
                    });
                    sample.push({
                        sig,
                        tag: el.tagName,
                        attrs,
                        rect: {
                            x: Math.round(el.getBoundingClientRect().x),
                            y: Math.round(el.getBoundingClientRect().y),
                            w: Math.round(el.getBoundingClientRect().width),
                            h: Math.round(el.getBoundingClientRect().height),
                        },
                        text: (el.innerText || '').trim().slice(0, 100).replace(/\s+/g, ' '),
                    });
                }
            });
            return {found: true, signatures: Array.from(seenSig.entries()), sample};
        }""")

        # 2. Re-open the watchlists-button popup. Don't filter on
        # newlines this time.
        await page.locator('[data-name="watchlists-button"]').first.click()
        await page.wait_for_timeout(700)
        list_popup = await page.evaluate(r"""() => {
            const popups = Array.from(document.querySelectorAll(
                '[class*="menuBox-"], div[role="menu"]'
            )).filter(p => {
                const r = p.getBoundingClientRect();
                return r.width > 80 && r.height > 40;
            });
            if (!popups.length) return {found: false};
            const popup = popups[popups.length - 1];
            // Walk every visible descendant; capture rich attributes.
            const out = [];
            popup.querySelectorAll('*').forEach(it => {
                const r = it.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                const t = (it.innerText || '').trim();
                if (!t || t.length > 200) return;
                const attrs = {};
                ['data-name', 'data-id', 'aria-label', 'role', 'class'].forEach(a => {
                    const v = it.getAttribute(a);
                    if (v) attrs[a] = v.slice(0, 80);
                });
                out.push({
                    tag: it.tagName,
                    attrs,
                    text: t.replace(/\s+/g, ' ').slice(0, 100),
                });
            });
            return {found: true, popupClass: popup.className.slice(0, 80), items: out};
        }""")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # 3. Add-symbol input — opens a search dialog. Capture its DOM.
        await page.locator('[data-name="add-symbol-button"]').first.click()
        await page.wait_for_timeout(800)
        add_dialog = await page.evaluate(r"""() => {
            const dlgs = Array.from(document.querySelectorAll(
                'div[class*="dialog-"], [data-dialog-name]'
            )).filter(d => {
                const r = d.getBoundingClientRect();
                return r.width > 200 && r.height > 100;
            });
            if (!dlgs.length) return {found: false};
            const dlg = dlgs[dlgs.length - 1];
            const inputs = [];
            dlg.querySelectorAll('input').forEach(i => {
                const r = i.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) return;
                inputs.push({
                    placeholder: i.placeholder,
                    ariaLabel: i.getAttribute('aria-label'),
                    dataName: i.getAttribute('data-name'),
                    classes: (i.className || '').slice(0, 80),
                });
            });
            return {
                found: true,
                dialogClass: dlg.className.slice(0, 100),
                dialogName: dlg.getAttribute('data-dialog-name'),
                inputs,
            };
        }""")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"watchlist-dive-{ts}.json"
        out_path.write_text(json.dumps({
            "rows": rows, "list_popup": list_popup, "add_dialog": add_dialog,
        }, indent=2))

        print(f"Wrote snapshot to {out_path}", flush=True)
        print(flush=True)
        if rows.get("found"):
            print("Row signatures (count):", flush=True)
            for sig, cnt in rows["signatures"][:20]:
                print(f"  [{cnt:2d}x]  {sig}", flush=True)
            print(flush=True)
            print(f"Sample rows ({min(15, len(rows['sample']))} of {len(rows['sample'])}):", flush=True)
            for s in rows["sample"][:15]:
                attrs_compact = {k: v for k, v in s["attrs"].items()
                                 if k.startswith("data-") or k in ("role", "id")}
                print(f"  {s['tag']} h={s['rect']['h']} text={s['text']!r}", flush=True)
                if attrs_compact:
                    print(f"    attrs: {attrs_compact}", flush=True)
        print(flush=True)
        if list_popup.get("found"):
            print(f"Watchlists popup items ({len(list_popup['items'])}):", flush=True)
            for it in list_popup["items"][:30]:
                print(f"  {it['tag']:5s}  attrs={it['attrs']}  text={it['text']!r}", flush=True)
        print(flush=True)
        if add_dialog.get("found"):
            print(f"Add-symbol dialog name={add_dialog.get('dialogName')!r}", flush=True)
            print(f"  inputs: {add_dialog['inputs']}", flush=True)

    return 0


if __name__ == "__main__":
    asyncio.run(main())
