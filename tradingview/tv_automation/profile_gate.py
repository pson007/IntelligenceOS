"""Pre-profile framing gate.

Before sending a chart screenshot to the daily-profile LLM, verify the
viewport actually contains the full RTH session of the cursor's trading
day. Without this gate, a bad frame silently produces a low-quality
profile that misses morning or close context — we already hit this on
the first 2026-03-18 attempt.

Approach: dispatch a fast vision call to read just the leftmost and
rightmost time labels on the x-axis. Parse as HH:MM. Gate on:
  * leftmost ≤ required_open   (morning is in frame)
  * rightmost ≥ required_close (close / cursor is in frame)

The main profile call stays unchanged — this is a pre-flight only.
If the gate fails, caller re-frames and retries BEFORE paying for the
expensive multi-minute profile call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import time as dtime

from .chatgpt_web import analyze_via_chatgpt_web
from .lib import audit


_GATE_SYSTEM = """You are a chart-framing verifier for a TradingView chart in Bar Replay mode. The chart shows a single RTH trading day around the cursor, plus sometimes small slivers of the previous or next day at the edges. There is a blue "BarDate" label on the current cursor bar showing its date.

Your job: find the x-axis TIME labels that belong to the CURSOR'S trading day, specifically the earliest and latest time labels for that day. Previous-day or next-day content may appear on the edges — those should be ignored, but reported so the caller knows.

A "date-change marker" on the x-axis is a short tick like "18", "19", "20", "Mar 18" — these mark the boundary between trading days. Time labels to the LEFT of the first date marker belong to the previous day; time labels to the RIGHT of a second date marker belong to the next day. Time labels BETWEEN two date markers (or between a date marker and the cursor) belong to the cursor's day.

Return ONLY a compact JSON object. No prose, no code fences, no preamble.

Response shape:
{"session_first_time": "09:30", "session_last_time": "16:00", "prev_day_sliver": true, "next_day_sliver": false}

Rules:
- session_first_time: earliest time label on the x-axis that belongs to the cursor's trading day (24-hour HH:MM)
- session_last_time: latest time label on the x-axis that belongs to the cursor's trading day (24-hour HH:MM)
- prev_day_sliver: true if there's any content on the chart that is BEFORE the cursor's trading day
- next_day_sliver: true if there's any content on the chart that is AFTER the cursor's trading day
- Ignore the bottom-status-bar clock (e.g. "08:14 PM UTC-4") — that's system time, not chart axis
- Use null for a time field only if no time labels of the cursor's day are visible at all
- Return ONLY the JSON object, nothing else"""


@dataclass
class GateResult:
    ok: bool
    reason: str
    session_first: dtime | None = None
    session_last: dtime | None = None
    prev_day_sliver: bool = False
    next_day_sliver: bool = False
    raw: dict | None = None


_RTH_OPEN = dtime(9, 30)
_RTH_CLOSE = dtime(16, 0)


def _parse_time(s: str | None) -> dtime | None:
    """Parse 'HH:MM' → time. Returns None on 'DATE', null, or unparseable."""
    if not s or s == "DATE":
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", s.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return dtime(h, mi)


async def verify_full_session(
    screenshot_path: str,
    *,
    required_open: dtime = dtime(10, 15),
    required_close: dtime = dtime(15, 30),
    cursor_time: dtime | None = None,
    model: str = "Instant",
    timeout_s: int = 60,
) -> GateResult:
    """Verify `screenshot_path` frames a full RTH session.

    Args:
        screenshot_path: Path to the chart PNG to verify.
        required_open: Latest acceptable first-session time (default 10:15). This is
            generous because the Instant-tier vision model often reads the first
            PROMINENT half-hour tick (10:00) and misses a small "09:30" tick — we'd
            rather accept a slightly-cropped open than false-fail a good frame. The
            gate still catches dramatic misses (e.g. noon-start = 12:15 > 10:15).
        required_close: Earliest acceptable last-session time (default 15:30).
        cursor_time: If the replay cursor is before session close, set required_close
            to the cursor time instead — a cursor at 13:28 only needs labels out to
            13:28, not 15:30.
        model: ChatGPT subscription tier. "Instant" is fast; "Thinking" is slower but
            more accurate on small ticks.

    Returns:
        GateResult. Pass iff leftmost ≤ required_open AND rightmost ≥ effective_close.
    """
    effective_close = cursor_time if cursor_time and cursor_time < required_close else required_close

    with audit.timed("profile_gate.verify",
                     screenshot=screenshot_path,
                     required_open=str(required_open),
                     effective_close=str(effective_close)) as ac:
        text, _, _ = await analyze_via_chatgpt_web(
            image_path=screenshot_path,
            system_prompt=_GATE_SYSTEM,
            user_text="Return the JSON.",
            model=model,
            timeout_s=timeout_s,
        )

        # Extract JSON — the model sometimes adds a trailing newline or stray chars.
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if not m:
            ac["result"] = "parse_fail"
            ac["raw"] = text[:200]
            return GateResult(ok=False, reason="parse_fail_no_json", raw={"raw": text[:200]})
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            ac["result"] = "json_fail"
            ac["raw"] = m.group(0)[:200]
            return GateResult(ok=False, reason="parse_fail_bad_json", raw={"raw": m.group(0)[:200]})

        first = _parse_time(d.get("session_first_time"))
        last = _parse_time(d.get("session_last_time"))
        prev_sliver = bool(d.get("prev_day_sliver"))
        next_sliver = bool(d.get("next_day_sliver"))
        ac["first_raw"] = d.get("session_first_time")
        ac["last_raw"] = d.get("session_last_time")
        ac["prev_sliver"] = prev_sliver
        ac["next_sliver"] = next_sliver

        common = dict(session_first=first, session_last=last,
                      prev_day_sliver=prev_sliver, next_day_sliver=next_sliver, raw=d)

        if first is None:
            ac["result"] = "no_session_first"
            return GateResult(ok=False, reason="session_first_unreadable", **common)
        if last is None:
            ac["result"] = "no_session_last"
            return GateResult(ok=False, reason="session_last_unreadable", **common)

        if first > required_open:
            ac["result"] = "morning_cut"
            return GateResult(ok=False,
                              reason=f"morning_cut (session_first={first}, required≤{required_open})",
                              **common)
        if last < effective_close:
            ac["result"] = "close_cut"
            return GateResult(ok=False,
                              reason=f"close_cut (session_last={last}, required≥{effective_close})",
                              **common)

        ac["result"] = "pass"
        return GateResult(ok=True, reason="ok", **common)
