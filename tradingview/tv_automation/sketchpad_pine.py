"""Compose a Pine v6 Sketchpad indicator from a list of accepted visuals.

The Sketchpad is the AI Visual Coach's output channel: a single .pine
file holding N visuals (level / vline / cross_alert) the trader has
accepted from LLM proposals. Re-rendered on every accept/remove and
re-applied to the chart.

Source of truth is the JSON list (`tradingview/sketchpad/<sym>_<date>.json`).
This module is a pure function — JSON in, Pine source out. No I/O.

Visual schema:
    {
      "id":      "v_abcd1234",                 # 10-char id, server-assigned
      "type":    "level" | "vline" | "cross_alert",
      "label":   str,                          # short, displayed on chart
      "color":   "red" | "green" | "yellow" | "blue" | "aqua" |
                 "orange" | "purple" | "white" | "gray",
      "rationale": str,                        # LLM's why; not rendered
      "confidence": "low" | "med" | "high",   # not rendered
      # type-specific:
      "price":          float,                 # level, cross_alert
      "alert_on_cross": bool,                  # level only
      "time_et":        "HH:MM",               # vline only
      "direction":      "above" | "below",    # cross_alert only
    }

Conventions match `forecast_pine.py`:
  * Pine v6, indicator(overlay=true)
  * NY-anchored timestamps for any wall-clock gates (vlines)
  * `barstate.isconfirmed` on cross detectors so they don't repaint
  * Per-visual `input.bool` show toggle so the trader can hide one
    without removing it from the sketchpad JSON
  * Per-visual `input.float` for prices — tweakable from TV's settings
    pane without re-running the coach
"""

from __future__ import annotations

from typing import Any


_VALID_COLORS = {
    "red", "green", "yellow", "blue", "aqua",
    "orange", "purple", "white", "gray",
}
_VALID_TYPES = {"level", "vline", "cross_alert"}
_VALID_DIRECTIONS = {"above", "below"}


def _safe_color(c: str | None) -> str:
    """Coerce to a Pine `color.<name>` token. Falls back to white for
    unknown values rather than emitting invalid Pine source."""
    name = (c or "white").strip().lower()
    if name not in _VALID_COLORS:
        name = "white"
    return f"color.{name}"


def _esc(s: str | None) -> str:
    """Escape a string for embedding in a Pine `"..."` literal."""
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _short_label(s: str | None, *, limit: int = 60) -> str:
    """Trim long labels so they fit the on-chart label widget."""
    text = (s or "").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _render_level(v: dict, idx: int) -> str:
    """Horizontal price level. Optionally fires an alert on cross.

    Always drawn as a `plot(price, style_line)` rather than `hline()`
    because plot accepts the conditional `show ? price : na` pattern
    cleanly while hline's `display=` toggle requires a const expression
    that would force a recompile when toggled."""
    vid     = v["id"]
    label   = _short_label(v.get("label") or "level")
    color   = _safe_color(v.get("color"))
    price   = float(v.get("price") or 0.0)
    alertx  = bool(v.get("alert_on_cross"))
    label_e = _esc(label)
    short_e = _esc(label[:30])
    long_e  = _esc(label[:60])

    # Per-visual inputs grouped under a per-visual inline so the TV
    # settings pane shows them on a single row — keeps long sketchpads
    # navigable.
    block = f"""// === Visual {idx + 1}: {vid} (level) — {label_e} ===
{vid}_on    = input.bool(true,   "{label_e}", group="Visuals · {vid}", inline="{vid}_a")
{vid}_price = input.float({price:.2f}, "",         step=0.25, group="Visuals · {vid}", inline="{vid}_a")
plot({vid}_on ? {vid}_price : na, "{label_e}",
     color=color.new({color}, 30), linewidth=2, style=plot.style_line)

var label {vid}_lbl = na
if barstate.islast and {vid}_on
    label.delete({vid}_lbl)
    {vid}_lbl := label.new(bar_index + 5, {vid}_price,
         text="{label_e} · " + str.tostring({vid}_price, "#,##0.00"),
         color=color.new({color}, 40), textcolor=color.white,
         style=label.style_label_left, size=size.small)
"""

    if alertx:
        # TV alert templates use double-braces ({{close}} etc.) which
        # need quadruple braces in an f-string to render literally.
        block += f"""
// alert on either-direction cross
{vid}_cross = ta.cross(close, {vid}_price) and barstate.isconfirmed and {vid}_on
alertcondition({vid}_cross, title="cross {short_e} ({vid})",
     message="MNQ1 closed across {long_e} ({{{{close}}}})")
"""
    return block


def _render_vline(v: dict, idx: int) -> str:
    """Vertical time marker at HH:MM ET on the target day.

    NY-anchored timestamp (per Pine v6 gotcha — see pine.md). Drawn
    once when the session first crosses the marker time, with
    `extend.both` so it spans the whole price axis."""
    vid   = v["id"]
    label = _short_label(v.get("label") or "marker")
    color = _safe_color(v.get("color"))
    time_et = (v.get("time_et") or "12:00").strip()

    # Robust HH:MM parse; bad input falls back to noon. Keeps a malformed
    # LLM proposal from breaking the whole sketchpad render.
    try:
        hh_s, mm_s = time_et.split(":", 1)
        hh, mm = int(hh_s), int(mm_s)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("out of range")
    except (ValueError, AttributeError):
        hh, mm = 12, 0

    return f"""// === Visual {idx + 1}: {vid} (vline) — {_esc(label)} @ {hh:02d}:{mm:02d} ET ===
{vid}_on = input.bool(true, "vline · {_esc(label)} · {hh:02d}:{mm:02d}", group="Visuals · {vid}")
{vid}_t  = timestamp("America/New_York", fyear, fmonth, fday, {hh}, {mm}, 0)
var bool {vid}_drawn = false
if in_target_day and time >= {vid}_t and not {vid}_drawn and {vid}_on
    {vid}_drawn := true
    line.new(bar_index, low, bar_index, high,
         color=color.new({color}, 35), width=1, style=line.style_dashed,
         extend=extend.both)
    label.new(bar_index, high, text="{_esc(label)} · {hh:02d}:{mm:02d}",
         color=color.new({color}, 30), textcolor=color.white,
         style=label.style_label_down, size=size.small)
"""


def _render_cross_alert(v: dict, idx: int) -> str:
    """Directional close-cross alert with a dashed reference line.

    `ta.crossover` for above, `ta.crossunder` for below. Both gated by
    `barstate.isconfirmed` so the alert doesn't fire mid-bar then
    cancel when the bar closes back through. Also draws an on-chart
    label on the firing bar."""
    vid       = v["id"]
    label     = _short_label(v.get("label") or "alert")
    color     = _safe_color(v.get("color"))
    price     = float(v.get("price") or 0.0)
    direction = (v.get("direction") or "above").strip().lower()
    if direction not in _VALID_DIRECTIONS:
        direction = "above"
    is_above = direction == "above"
    cross_fn = "ta.crossover" if is_above else "ta.crossunder"
    arrow    = "↑" if is_above else "↓"
    label_anchor = "high" if is_above else "low"
    label_style  = "label.style_label_down" if is_above else "label.style_label_up"
    label_e  = _esc(label)
    short_e  = _esc(label[:40])

    return f"""// === Visual {idx + 1}: {vid} (cross_alert {direction}) — {label_e} ===
{vid}_on    = input.bool(true,   "alert {arrow} {label_e}", group="Visuals · {vid}", inline="{vid}_a")
{vid}_price = input.float({price:.2f}, "",                       step=0.25, group="Visuals · {vid}", inline="{vid}_a")
{vid}_event = {vid}_on and {cross_fn}(close, {vid}_price) and barstate.isconfirmed
plot({vid}_on ? {vid}_price : na, "{label_e} ref",
     color=color.new({color}, 50), linewidth=1, style=plot.style_circles)
if {vid}_event
    label.new(bar_index, {label_anchor},
         text="{arrow} " + str.tostring({vid}_price, "#,##0.00") + " · {label_e}",
         color=color.new({color}, 0), textcolor=color.white,
         style={label_style}, size=size.small)
alertcondition({vid}_event,
     title="{arrow} {short_e} ({vid})",
     message="MNQ1 close {direction} {price:.2f} — {label_e}")
"""


_RENDERERS = {
    "level":       _render_level,
    "vline":       _render_vline,
    "cross_alert": _render_cross_alert,
}


def render_sketchpad(visuals: list[dict], symbol: str, date: str) -> str:
    """Render a complete Pine v6 indicator from a list of accepted visuals.

    `date` must be ``YYYY-MM-DD`` — used to anchor any vline timestamps
    on the target day. `symbol` is informational (header comment + the
    indicator's title). Empty `visuals` returns a stub indicator with no
    drawings, which is valid Pine and apply-able — useful for clearing
    the sketchpad without uninstalling the indicator from the chart.
    """
    try:
        year_s, month_s, day_s = date.split("-")
        year, month, day = int(year_s), int(month_s), int(day_s)
    except ValueError as e:
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}") from e

    blocks: list[str] = []
    for idx, v in enumerate(visuals or []):
        vtype = (v.get("type") or "").strip().lower()
        if vtype not in _VALID_TYPES:
            # Skip unknown types rather than failing the whole render —
            # better to surface partial visuals than nothing.
            continue
        if not v.get("id"):
            continue
        blocks.append(_RENDERERS[vtype](v, idx))

    body = "\n".join(blocks) if blocks else (
        "// (no visuals — sketchpad is empty)\n"
    )

    return f"""//@version=6
// Visual Coach Sketchpad — {_esc(symbol)} {date}
// Auto-generated. Do not hand-edit; edit the sketchpad JSON and regenerate.
//
// Holds AI-proposed visuals the trader has accepted: levels, vertical
// time markers, and directional cross alerts. Composes alongside the
// Forecast Overlay (separate indicator) — this is the mid-session
// dynamic layer; the forecast is the morning-locked thesis.

indicator("IOS Sketchpad {date}", overlay=true,
     max_lines_count=50, max_labels_count=100)

// ---------------------------------------------------------------------------
// Date anchor — vlines and any time-of-day gating compare against an explicit
// NY-timezone timestamp built from these inputs. Default is the day this
// sketchpad was rendered for; the trader can shift it to replay the same
// visuals against another day's chart by editing these values.
// ---------------------------------------------------------------------------
fyear  = input.int({year},  "Year",  group="Sketchpad")
fmonth = input.int({month}, "Month", group="Sketchpad", minval=1, maxval=12)
fday   = input.int({day},   "Day",   group="Sketchpad", minval=1, maxval=31)

in_target_day = year == fyear and month == fmonth and dayofmonth == fday

// ---------------------------------------------------------------------------
// Visuals ({len(blocks)} accepted)
// ---------------------------------------------------------------------------
{body}"""
