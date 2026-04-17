"""Probe the Trading Panel's Positions tab.

Purpose: generate a JSON catalog of every [data-name], aria-label,
class name, and role inside the positions table so we can wire stable
selectors for trading.positions() and trading.close_position().

Usage (run after signing in to TradingView and activating Paper Trading):
    .venv/bin/python -m tv_automation.probes.probe_positions

Output: tv_automation/probes/snapshots/positions-YYYYMMDD-HHMMSS.json
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

        # Try to click the Positions tab at the bottom. Multiple candidates.
        candidates = [
            'button[data-name="positions"]',
            'button:has-text("Positions")',
            '[data-name="bottom-panel"] button:has-text("Positions")',
        ]
        clicked = False
        for sel in candidates:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                try:
                    await loc.click(timeout=3000)
                    clicked = True
                    break
                except Exception:
                    continue
        if not clicked:
            print("WARN: could not find a Positions tab. "
                  "Is Paper Trading activated and is there a Trading Panel?", flush=True)

        await page.wait_for_timeout(1500)

        # Dump every interesting attribute within the bottom panel area.
        data = await page.evaluate("""() => {
            const container = document.querySelector(
                '[data-name="bottom-panel"], [class*="bottomWidgetBar"], [class*="tradingPanel"]'
            ) || document.body;
            const out = [];
            container.querySelectorAll('*').forEach(n => {
                const dn = n.getAttribute('data-name');
                const al = n.getAttribute('aria-label');
                const dbroker = n.getAttribute('data-broker-name');
                if (!dn && !al && !dbroker) return;
                out.push({
                    tag: n.tagName.toLowerCase(),
                    dataName: dn,
                    ariaLabel: al,
                    dataBrokerName: dbroker,
                    className: typeof n.className === 'string'
                        ? n.className.slice(0, 80) : null,
                    text: (n.innerText || '').trim().slice(0, 80),
                    visible: !!(n.offsetWidth || n.offsetHeight),
                });
            });
            return out;
        }""")

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOT_DIR / f"positions-{ts}.json"
        out_path.write_text(json.dumps(data, indent=2))

        print(f"Wrote {len(data)} entries to {out_path}", flush=True)
        print(flush=True)
        print("Likely position-row selectors:", flush=True)
        for r in data:
            if r.get("dataName") and "position" in r["dataName"].lower():
                print(f"  {r['tag']:8s} data-name={r['dataName']!r:40s}  aria={r['ariaLabel']!r}", flush=True)
        print(flush=True)
        print("Likely positions-tab button:", flush=True)
        for r in data:
            if (r.get("dataName") == "positions" or
                (r.get("ariaLabel") and "position" in r["ariaLabel"].lower())):
                print(f"  {r['tag']:8s} data-name={r['dataName']!r:40s}  aria={r['ariaLabel']!r}", flush=True)
        print(flush=True)
        print("Likely broker chip:", flush=True)
        for r in data:
            if r.get("dataBrokerName") or (r.get("ariaLabel") and r["ariaLabel"].lower().startswith("broker")):
                print(f"  {r['tag']:8s} data-broker={r['dataBrokerName']!r}  aria={r['ariaLabel']!r}  text={r['text']!r}", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
