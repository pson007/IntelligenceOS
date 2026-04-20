"""Probe the Bar Replay date picker modal.

Activates Replay, clicks the `Select date` button, catalogs every
input / button / dialog that appears, then dismisses the modal and
exits Replay. Purpose: resolve UNKNOWN #2 in REPLAY_BENCH_PLAN.md —
we need the input format (text? separate date+time fields? calendar
grid? "Go to" button?) before `replay.select_start_date()` can be
reliably programmed.

Also addresses UNKNOWN #6: reads the `Select date` button text once
*before* picking and once *after* a date is programmatically entered
and the cursor is stepped forward, so we can tell whether the label
tracks the cursor or is frozen at the pick.

Run:
    cd tradingview && .venv/bin/python -m tv_automation.probes.probe_replay_datepicker
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from preflight import ensure_automation_chromium
from session import tv_context

from ..chart import _find_or_open_chart
from ..lib.visible_locator import pick_visible, wait_visible
from ..replay import (
    _EXIT,
    _SELECT_DATE,
    _STRIP,
    _TOGGLE,
)

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


# Catalogs every visible interactive element *outside* the main replay
# strip. When the date-picker modal is open this yields its inputs,
# buttons, and dialog containers. When nothing modal is open it yields
# background controls, which is fine — the diff shows us what the modal
# added.
_CATALOG_JS = r"""() => {
    const out = { dialogs: [], inputs: [], buttons: [], calendars: [] };

    document.querySelectorAll('[role="dialog"], [class*="dialog" i], [class*="modal" i], [class*="popup" i]').forEach(d => {
        const rect = d.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        out.dialogs.push({
            tag: d.tagName.toLowerCase(),
            role: d.getAttribute('role'),
            dataName: d.getAttribute('data-name'),
            ariaLabel: d.getAttribute('aria-label'),
            cls: (d.getAttribute('class') || '').slice(0, 160),
            text: (d.innerText || '').trim().slice(0, 200),
            xy: {x: Math.round(rect.x), y: Math.round(rect.y),
                 w: Math.round(rect.width), h: Math.round(rect.height)},
        });
    });

    document.querySelectorAll('input, [contenteditable="true"]').forEach(inp => {
        const rect = inp.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        out.inputs.push({
            tag: inp.tagName.toLowerCase(),
            type: inp.getAttribute('type'),
            name: inp.getAttribute('name'),
            dataName: inp.getAttribute('data-name'),
            ariaLabel: inp.getAttribute('aria-label'),
            placeholder: inp.getAttribute('placeholder'),
            value: (inp.value || inp.textContent || '').slice(0, 80),
            cls: (inp.getAttribute('class') || '').slice(0, 160),
            xy: {x: Math.round(rect.x), y: Math.round(rect.y),
                 w: Math.round(rect.width), h: Math.round(rect.height)},
        });
    });

    document.querySelectorAll('button, [role="button"]').forEach(b => {
        const rect = b.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        // Skip buttons inside the replay strip — we already catalogued those.
        if (b.closest('[data-name="replay-bottom-toolbar"]')) return;
        // Skip buttons in the top toolbar too (noisy, not modal-related).
        if (rect.y < 40 && rect.y >= 0) return;
        const txt = (b.innerText || '').trim();
        if (!txt && !b.getAttribute('aria-label') && !b.getAttribute('title')) return;
        out.buttons.push({
            tag: b.tagName.toLowerCase(),
            role: b.getAttribute('role'),
            dataName: b.getAttribute('data-name'),
            ariaLabel: b.getAttribute('aria-label'),
            title: b.getAttribute('title'),
            text: txt.slice(0, 60),
            cls: (b.getAttribute('class') || '').slice(0, 160),
            xy: {x: Math.round(rect.x), y: Math.round(rect.y),
                 w: Math.round(rect.width), h: Math.round(rect.height)},
        });
    });

    // Calendar grids (date pickers usually use a table of day cells).
    document.querySelectorAll('[role="grid"], [class*="calendar" i], [class*="datepicker" i]').forEach(c => {
        const rect = c.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        out.calendars.push({
            tag: c.tagName.toLowerCase(),
            role: c.getAttribute('role'),
            dataName: c.getAttribute('data-name'),
            cls: (c.getAttribute('class') || '').slice(0, 160),
            outerSnippet: (c.outerHTML || '').slice(0, 500),
            xy: {x: Math.round(rect.x), y: Math.round(rect.y),
                 w: Math.round(rect.width), h: Math.round(rect.height)},
        });
    });

    return out;
}"""


async def main() -> int:
    await ensure_automation_chromium()
    async with tv_context() as ctx:
        page = await _find_or_open_chart(ctx)
        await page.wait_for_selector("canvas", state="visible", timeout=30_000)
        await page.wait_for_timeout(1000)

        snapshot: dict = {
            "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "url": page.url,
            "phases": {},
            "notes": [],
        }

        started_in_replay = await pick_visible(page, _STRIP) is not None

        # Phase A — enter Replay if needed and capture the `Select date`
        # button's text BEFORE any date is picked.
        if not started_in_replay:
            toggle = await pick_visible(page, _TOGGLE)
            if toggle is None:
                snapshot["notes"].append("Replay toggle not found — aborting")
                _write(snapshot)
                return 1
            await toggle.click()
            await wait_visible(page, _STRIP, timeout_ms=5000)
            await page.wait_for_timeout(500)

        select_date_btn = await pick_visible(page, _SELECT_DATE)
        pre_pick_text = None
        if select_date_btn is not None:
            try:
                pre_pick_text = (await select_date_btn.inner_text()).strip()
            except Exception:
                pass
        snapshot["phases"]["A_before_open"] = {
            "select_date_button_text": pre_pick_text,
        }

        # Phase B — click Select date, wait for the modal, catalog.
        if select_date_btn is None:
            snapshot["notes"].append("Select date button not visible")
            _write(snapshot)
            return 1
        await select_date_btn.click()
        await page.wait_for_timeout(800)
        snapshot["phases"]["B_modal_open"] = await page.evaluate(_CATALOG_JS)

        # Phase C — dismiss. Press Escape; this also doubles as a test
        # that the modal is dismissable without applying a date.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
        snapshot["phases"]["C_after_escape"] = await page.evaluate(_CATALOG_JS)

        # Phase D — exit Replay (only if we activated it ourselves).
        if not started_in_replay:
            exit_btn = await pick_visible(page, _EXIT)
            if exit_btn is not None:
                try:
                    await exit_btn.click()
                except Exception as e:
                    snapshot["notes"].append(
                        f"exit click failed: {type(e).__name__}: {e}"
                    )
            else:
                toggle = await pick_visible(page, _TOGGLE)
                if toggle is not None:
                    await toggle.click()
            await page.wait_for_timeout(500)
            snapshot["notes"].append(
                "exited Replay mode (we activated it in this probe)"
            )
        else:
            snapshot["notes"].append(
                "Replay was already active on entry — left it active"
            )

        _write(snapshot)

        # Console summary — enough to eyeball the important bits.
        print(
            f"Select date button BEFORE pick: "
            f"{snapshot['phases']['A_before_open']['select_date_button_text']!r}",
            flush=True,
        )
        print(flush=True)

        modal = snapshot["phases"]["B_modal_open"]
        print(f"Dialogs ({len(modal['dialogs'])}):", flush=True)
        for d in modal["dialogs"][:6]:
            print(
                f"  {d['tag']:6s} role={d.get('role')!r:10s} "
                f"cls={d['cls'][:60]!r}", flush=True,
            )
            if d.get("text"):
                print(f"    text: {d['text'][:100]!r}", flush=True)

        print(f"\nInputs ({len(modal['inputs'])}):", flush=True)
        for inp in modal["inputs"][:12]:
            print(
                f"  {inp['tag']:6s} type={inp.get('type')!r:10s} "
                f"name={inp.get('name')!r:12s} "
                f"placeholder={inp.get('placeholder')!r:24s} "
                f"value={inp.get('value')!r}",
                flush=True,
            )

        print(f"\nButtons visible ({len(modal['buttons'])}):", flush=True)
        for b in modal["buttons"][:30]:
            print(
                f"  {b['tag']:6s} text={b.get('text')!r:28s} "
                f"aria={b.get('ariaLabel')!r:20s} title={b.get('title')!r}",
                flush=True,
            )

        print(f"\nCalendars ({len(modal['calendars'])}):", flush=True)
        for c in modal["calendars"][:4]:
            print(
                f"  {c['tag']:6s} role={c.get('role')!r} "
                f"cls={c['cls'][:70]!r}", flush=True,
            )

        print(flush=True)
        for note in snapshot["notes"]:
            print(f"NOTE: {note}", flush=True)
    return 0


def _write(snapshot: dict) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = SNAPSHOT_DIR / f"replay-datepicker-{ts}.json"
    out_path.write_text(json.dumps(snapshot, indent=2))
    print(f"Wrote snapshot to {out_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
