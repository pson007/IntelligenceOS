"""Probe the Pine Editor's console (the bottom log table inside the Pine
Editor panel) to understand row classes for info/Compiling/error rows.

Needed to design the 'wait for Compiling... row' boundary in apply.
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

        # Open Pine Editor.
        open_btn = page.locator('[data-name="pine-dialog-button"]').first
        if await open_btn.count() > 0 and await open_btn.is_visible():
            await open_btn.click()
            await page.wait_for_timeout(1500)

        # Dump every console row's classes + text. Console is a <table>
        # inside the Pine Editor area; each row has a stable class prefix
        # (selectable-, error-, warning-, etc.).
        info = await page.evaluate(r"""() => {
            // Find all <tr>s that look like console log rows (have a
            // selectable- class prefix or sit inside a console-shaped
            // table near the editor).
            const rows = Array.from(document.querySelectorAll('tr'))
                .filter(r => {
                    const cls = (r.className || '').toString();
                    return cls.includes('selectable-')
                        || cls.includes('error-')
                        || cls.includes('warning-')
                        || cls.includes('info-');
                });
            return rows.slice(-20).map(r => ({
                classes: (r.className || '').toString().slice(0, 100),
                text: (r.innerText || '').trim().slice(0, 200).replace(/\s+/g, ' '),
            }));
        }""")

        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"pine-console-{ts}.json"
        out_path.write_text(json.dumps(info, indent=2))
        print(f"Wrote snapshot to {out_path}", flush=True)
        print(f"\nLast {len(info)} console rows:", flush=True)
        for r in info:
            cat = ""
            cls = r["classes"]
            if "error-" in cls:
                cat = "ERROR"
            elif "warning-" in cls:
                cat = "WARN"
            elif "selectable-" in cls or "info-" in cls:
                cat = "INFO"
            print(f"  [{cat:5s}]  {r['text'][:120]}", flush=True)
            print(f"            classes={r['classes'][:80]}", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
