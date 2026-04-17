"""Probe the Strategy Tester panel.

Purpose: catalog selectors for panel toggle, tabs (Performance Summary,
List of Trades, Properties), the main tables, and controls.

Prerequisite: a strategy is applied to the chart. Without one, the
Strategy Tester panel exists but shows "no strategy selected" and
there's nothing useful to probe. To run, either:
  - Have a strategy on the chart already, or
  - Apply pine/webhook_alert.pine first (it's a minimal SMA crossover
    strategy suitable for probing):
        python -m tv_automation.pine_editor apply pine/webhook_alert.pine

Then:
    python -m tv_automation.probes.probe_strategy_tester
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


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(2000)

        # Try to open Strategy Tester.
        candidates = [
            'button[data-name="backtesting"]',
            'button:has-text("Strategy Tester")',
            '[data-name="bottom-panel"] button:has-text("Strategy Tester")',
        ]
        for sel in candidates:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                try:
                    await loc.click(timeout=3000)
                    break
                except Exception:
                    continue

        await page.wait_for_timeout(2000)

        data = await page.evaluate("""() => {
            const container = document.querySelector(
                '[data-name="backtesting-panel"], [class*="strategyTester"], [data-name="bottom-panel"]'
            ) || document.body;
            const out = {
                buttons: [],
                tabs: [],
                tables: [],
                inputs: [],
            };
            container.querySelectorAll('button').forEach(b => {
                out.buttons.push({
                    dataName: b.getAttribute('data-name'),
                    ariaLabel: b.getAttribute('aria-label'),
                    text: (b.innerText || '').trim().slice(0, 60),
                    visible: !!(b.offsetWidth || b.offsetHeight),
                });
            });
            container.querySelectorAll('[role="tab"], [class*="tab-"]').forEach(t => {
                out.tabs.push({
                    dataName: t.getAttribute('data-name'),
                    ariaLabel: t.getAttribute('aria-label'),
                    text: (t.innerText || '').trim().slice(0, 60),
                });
            });
            container.querySelectorAll('table').forEach((tbl, i) => {
                const headers = Array.from(tbl.querySelectorAll('th')).map(h => (h.innerText || '').trim());
                const rowCount = tbl.querySelectorAll('tr').length;
                out.tables.push({ index: i, headers, rowCount });
            });
            container.querySelectorAll('input').forEach(inp => {
                out.inputs.push({
                    type: inp.type,
                    name: inp.name,
                    dataName: inp.getAttribute('data-name'),
                    placeholder: inp.placeholder,
                    ariaLabel: inp.getAttribute('aria-label'),
                });
            });
            return out;
        }""")

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"strategy-tester-{ts}.json"
        out_path.write_text(json.dumps(data, indent=2))

        print(f"Wrote snapshot to {out_path}", flush=True)
        print(flush=True)
        print(f"Buttons ({len(data['buttons'])}):", flush=True)
        for b in data["buttons"][:25]:
            if b["visible"]:
                print(f"  data-name={b['dataName']!r:40s}  text={b['text']!r}", flush=True)
        print(flush=True)
        print(f"Tabs ({len(data['tabs'])}):", flush=True)
        for t in data["tabs"][:15]:
            print(f"  data-name={t['dataName']!r:40s}  text={t['text']!r}", flush=True)
        print(flush=True)
        print(f"Tables ({len(data['tables'])}):", flush=True)
        for tbl in data["tables"]:
            print(f"  index={tbl['index']}  rows={tbl['rowCount']}  headers={tbl['headers'][:5]}...", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
