"""Pivot Pine overlay generator.

Renders a companion Pine v6 indicator from a pivot-forecast JSON. The
generated script plots:
  * A vertical dashed line + label at the pivot wall-clock time
  * Horizontal lines for the pivot's new levels (REVERSAL entry/stop/target,
    or SHAKEOUT reclaim threshold) — only after the pivot timestamp
  * A mini status table (top-left) with classification, revised bias,
    confidence, and meta-invalidation

The original pre-session forecast overlay stays on the chart untouched —
this runs as a SECOND indicator the user adds on top so both plans are
visible, with the pivot clearly anchored at its fire time.
"""

from __future__ import annotations

import re
from datetime import datetime


PIVOT_PINE_TEMPLATE = """\
//@version=6
indicator("Pivot · {{DATE}} @ {{PIVOT_HHMM}} ET", overlay=true)

// ---------------------------------------------------------------------------
// Inputs — editable in TV after applying.
// ---------------------------------------------------------------------------
classification = input.string("{{CLASSIFICATION}}", "Classification",
     options=["REVERSAL","FLAT","SHAKEOUT"], group="Pivot")
revised_bias = input.string("{{REVISED_BIAS}}", "Revised bias", group="Pivot")
revised_invalidation = input.string("{{REVISED_INVALIDATION}}",
     "Revised invalidation", group="Pivot")
pivot_confidence = input.string("{{PIVOT_CONFIDENCE}}", "Pivot confidence",
     options=["low","med","high"], group="Pivot")
table_pos_str = input.string("top_right", "Status table position",
     options=["top_right","top_left","middle_right","bottom_right"],
     group="Pivot",
     tooltip="Pivot status table location. Right side keeps the top-left free for TradingView's own bars info.")

rev_direction = input.string("{{REV_DIRECTION}}", "REVERSAL direction",
     options=["long","short","none"], group="REVERSAL")
rev_entry  = input.float({{REV_ENTRY}},  "REVERSAL entry trigger", group="REVERSAL")
rev_stop   = input.float({{REV_STOP}},   "REVERSAL stop",          group="REVERSAL")
rev_target = input.float({{REV_TARGET}}, "REVERSAL first target",  group="REVERSAL")

reclaim_level = input.float({{RECLAIM_LEVEL}}, "SHAKEOUT reclaim threshold", group="SHAKEOUT")

flat_cond_1 = input.string("{{FLAT_COND_1}}", "FLAT condition 1", group="FLAT")
flat_cond_2 = input.string("{{FLAT_COND_2}}", "FLAT condition 2", group="FLAT")

// ---------------------------------------------------------------------------
// Time anchors — target day in ET.
// ---------------------------------------------------------------------------
t_pivot = timestamp("America/New_York", {{YEAR}}, {{MONTH}}, {{DAY}},
     {{PIVOT_HOUR}}, {{PIVOT_MIN}}, 0)
t_0930  = timestamp("America/New_York", {{YEAR}}, {{MONTH}}, {{DAY}},  9, 30, 0)
t_1600  = timestamp("America/New_York", {{YEAR}}, {{MONTH}}, {{DAY}}, 16,  0, 0)
in_today_rth = time >= t_0930 and time < t_1600
after_pivot  = in_today_rth and time >= t_pivot

is_reversal = classification == "REVERSAL"
is_shakeout = classification == "SHAKEOUT"
is_flat     = classification == "FLAT"

// ---------------------------------------------------------------------------
// Horizontal levels — only after the pivot timestamp, only when the
// classification uses that level type.
// ---------------------------------------------------------------------------
// Drawn as `line.new` with `extend=extend.right` plus a right-edge label
// so each level is clearly identified ("entry 26,960", "STOP 27,015",
// "TP 26,881") at the live price axis, not just as an anonymous line.
// Labels re-anchor to the rightmost bar each update so they stay visible
// as time advances. Sentinels (-1.0) for missing levels are skipped.
var line   rev_entry_line  = na
var label  rev_entry_lbl   = na
var line   rev_stop_line   = na
var label  rev_stop_lbl    = na
var line   rev_target_line = na
var label  rev_target_lbl  = na
var line   reclaim_line    = na
var label  reclaim_lbl     = na

f_level(_x, _y, _txt, _col) =>
    _ln = line.new(_x, _y, _x + 1, _y, xloc=xloc.bar_index,
         color=_col, width=2, extend=extend.right)
    _lb = label.new(_x, _y, _txt,
         xloc=xloc.bar_index, yloc=yloc.price,
         color=color.new(_col, 25), textcolor=color.white,
         style=label.style_label_left, size=size.small)
    [_ln, _lb]

if in_today_rth and time >= t_pivot and is_reversal
    if na(rev_entry_line) and rev_entry > 0
        [_l, _b] = f_level(bar_index, rev_entry,
             "↳ " + str.upper(rev_direction) + " entry  " + str.tostring(rev_entry, "#,##0.00"),
             color.orange)
        rev_entry_line := _l
        rev_entry_lbl  := _b
    if na(rev_stop_line) and rev_stop > 0
        [_l, _b] = f_level(bar_index, rev_stop,
             "✕ STOP  " + str.tostring(rev_stop, "#,##0.00"),
             color.red)
        rev_stop_line := _l
        rev_stop_lbl  := _b
    if na(rev_target_line) and rev_target > 0
        [_l, _b] = f_level(bar_index, rev_target,
             "◎ TP  " + str.tostring(rev_target, "#,##0.00"),
             color.green)
        rev_target_line := _l
        rev_target_lbl  := _b

if in_today_rth and time >= t_pivot and is_shakeout and na(reclaim_line) and reclaim_level > 0
    [_l, _b] = f_level(bar_index, reclaim_level,
         "↺ reclaim  " + str.tostring(reclaim_level, "#,##0.00"),
         color.aqua)
    reclaim_line := _l
    reclaim_lbl  := _b

// Keep right-edge labels pinned to the current bar so they never scroll
// off the visible window. The lines themselves extend via extend.right.
if barstate.islast
    if not na(rev_entry_lbl)
        label.set_x(rev_entry_lbl, bar_index)
    if not na(rev_stop_lbl)
        label.set_x(rev_stop_lbl, bar_index)
    if not na(rev_target_lbl)
        label.set_x(rev_target_lbl, bar_index)
    if not na(reclaim_lbl)
        label.set_x(reclaim_lbl, bar_index)

// ---------------------------------------------------------------------------
// Vertical pivot marker + label — drawn once on the first bar at/past
// the pivot timestamp. The label text shape adapts to classification.
// ---------------------------------------------------------------------------
var bool marker_drawn = false
f_pivot_label_text() =>
    string s = "PIVOT · " + classification
    if is_reversal
        s := s + " · " + str.upper(rev_direction) + "\\n"
        if rev_entry > 0
            s := s + "entry " + str.tostring(rev_entry, "#,##0.00") + " / "
        if rev_stop > 0
            s := s + "stop " + str.tostring(rev_stop, "#,##0.00")
        if rev_target > 0
            s := s + " / tp " + str.tostring(rev_target, "#,##0.00")
    else if is_shakeout
        s := s + "\\nreclaim " + str.tostring(reclaim_level, "#,##0.00")
    else if is_flat
        s := s + "\\n" + flat_cond_1 +
             (flat_cond_2 == "" ? "" : "\\n" + flat_cond_2)
    s

if in_today_rth and time >= t_pivot and not marker_drawn and not na(close)
    marker_drawn := true
    line.new(bar_index, high * 1.002, bar_index, low * 0.998,
         xloc=xloc.bar_index, extend=extend.both,
         color=color.new(color.orange, 40), width=2, style=line.style_dashed)
    _col = is_reversal ? color.red : is_shakeout ? color.aqua : color.yellow
    label.new(bar_index, high, f_pivot_label_text(),
         yloc=yloc.abovebar,
         color=color.new(_col, 10),
         textcolor=color.white,
         style=label.style_label_down,
         size=size.normal)

// ---------------------------------------------------------------------------
// Status mini-table (top-left). Compact, high-contrast — the chart's
// primary forecast table stays top-right, this one owns top-left so
// the two don't collide.
// ---------------------------------------------------------------------------
// Row layout: header, bias (with confidence), up to 3 level rows, then
// invalidation text. Level rows are conditional on classification so the
// table stays tight — we don't show "entry/stop/tp" rows for a SHAKEOUT,
// and FLAT shows standaside-conditions instead of levels.
// Using `switch` rather than chained ternaries — Pine v6's line-
// continuation rules require continuations to indent deeper than the
// expression's first line; switch-arms sidestep that entirely.
f_pos_from_str(_s) =>
    switch _s
        "top_right"    => position.top_right
        "top_left"     => position.top_left
        "middle_right" => position.middle_right
        "bottom_right" => position.bottom_right
        => position.top_right

var table tbl = na
if barstate.isfirst
    tbl := table.new(f_pos_from_str(table_pos_str), 2, 7,
         bgcolor=color.new(color.black, 70),
         border_width=1, border_color=color.new(color.gray, 60))

if barstate.islast and not na(tbl)
    class_col = is_reversal ? color.red : is_shakeout ? color.aqua : color.yellow

    // Header — single merged row: "PIVOT · REVERSAL · 13:32 ET"
    header_text = "PIVOT · " + classification + " · {{PIVOT_HHMM}} ET"
    tbl.cell(0, 0, header_text,
         bgcolor=color.new(class_col, 35),
         text_color=color.white, text_size=size.small)
    tbl.merge_cells(0, 0, 1, 0)

    // Bias row — "Bias / sell failure · med"
    tbl.cell(0, 1, "Bias", text_color=color.new(color.white, 20), text_size=size.tiny)
    bias_combined = str.replace_all(revised_bias, "_", " ") + " · " + pivot_confidence
    tbl.cell(1, 1, bias_combined, text_color=color.aqua, text_size=size.tiny)

    // Level rows (classification-dependent). Pine v6 has no augmented
    // assignment (`+=`), so we use `:=` explicitly and keep the row
    // counter as a re-assignable local.
    if is_reversal
        int row = 2
        if rev_entry > 0
            tbl.cell(0, row, "Entry", text_color=color.new(color.white, 20), text_size=size.tiny)
            tbl.cell(1, row, str.tostring(rev_entry, "#,##0.00"),
                 text_color=color.orange, text_size=size.tiny)
            row := row + 1
        if rev_stop > 0
            tbl.cell(0, row, "Stop", text_color=color.new(color.white, 20), text_size=size.tiny)
            tbl.cell(1, row, str.tostring(rev_stop, "#,##0.00"),
                 text_color=color.red, text_size=size.tiny)
            row := row + 1
        if rev_target > 0
            tbl.cell(0, row, "Target", text_color=color.new(color.white, 20), text_size=size.tiny)
            tbl.cell(1, row, str.tostring(rev_target, "#,##0.00"),
                 text_color=color.green, text_size=size.tiny)
    else if is_shakeout and reclaim_level > 0
        tbl.cell(0, 2, "Reclaim", text_color=color.new(color.white, 20), text_size=size.tiny)
        tbl.cell(1, 2, str.tostring(reclaim_level, "#,##0.00"),
             text_color=color.aqua, text_size=size.tiny)
    else if is_flat
        if flat_cond_1 != ""
            tbl.cell(0, 2, "If", text_color=color.new(color.white, 20), text_size=size.tiny)
            tbl.cell(1, 2, flat_cond_1, text_color=color.yellow, text_size=size.tiny)
        if flat_cond_2 != ""
            tbl.cell(0, 3, "Or", text_color=color.new(color.white, 20), text_size=size.tiny)
            tbl.cell(1, 3, flat_cond_2, text_color=color.yellow, text_size=size.tiny)

    // Invalidation — last row, full-width merged, smaller text size so
    // the prose stays readable without ballooning the table height.
    tbl.cell(0, 6, "Invalid if — " + revised_invalidation,
         text_color=color.new(color.white, 20), text_size=size.tiny,
         text_halign=text.align_left)
    tbl.merge_cells(0, 6, 1, 6)
"""


_PLACEHOLDER_NUM = -1.0  # sentinel for missing numeric levels


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _parse_hhmm(made_at: str | None, fallback: str = "1200") -> tuple[int, int, str]:
    """Return (hour, minute, hhmm_string) from an ISO timestamp or fallback."""
    if made_at:
        try:
            dt = datetime.fromisoformat(made_at)
            return dt.hour, dt.minute, f"{dt.hour:02d}{dt.minute:02d}"
        except (ValueError, TypeError):
            pass
    h = int(fallback[:2]) if len(fallback) >= 4 else 12
    m = int(fallback[2:4]) if len(fallback) >= 4 else 0
    return h, m, fallback


def render_pivot_pine(pivot: dict) -> str:
    """Render a pivot-forecast JSON as a Pine v6 overlay indicator script.

    Missing numeric fields default to -1 (rendered but off-chart); the
    user can edit them in the indicator inputs if the LLM didn't produce
    a concrete level.
    """
    date = pivot.get("date", "1970-01-01")
    year, month, day = date.split("-")

    # Pivot time comes from the stage name (e.g. "invalidation_1305") when
    # available — that's the ET wall-clock at fire time. Falls back to
    # the made_at ISO if the stage is unusual.
    stage = pivot.get("stage") or ""
    m = re.match(r"^invalidation_(\d{2})(\d{2})$", stage)
    if m:
        pivot_hour = int(m.group(1))
        pivot_min = int(m.group(2))
        pivot_hhmm = f"{pivot_hour:02d}:{pivot_min:02d}"
    else:
        pivot_hour, pivot_min, hhmm_raw = _parse_hhmm(pivot.get("made_at"))
        pivot_hhmm = f"{pivot_hour:02d}:{pivot_min:02d}"

    classification = (pivot.get("pivot_classification") or "FLAT").upper()
    if classification not in ("REVERSAL", "FLAT", "SHAKEOUT"):
        classification = "FLAT"

    revised = pivot.get("revised_tactical_bias") or {}
    revised_bias = revised.get("bias") or "stand_aside"
    revised_inval = revised.get("invalidation") or "see notes"
    # Tight trim for the status-table cell — long prose balloons the
    # table's width on-chart. First sentence + 120-char cap is a readable
    # headline; full text is still in the JSON + vertical-marker label.
    first_sentence = revised_inval.split(". ")[0].strip()
    if first_sentence and len(first_sentence) < len(revised_inval):
        first_sentence += "."
    revised_inval = first_sentence or revised_inval
    if len(revised_inval) > 120:
        revised_inval = revised_inval[:117] + "..."

    pivot_conf = pivot.get("pivot_confidence") or "med"
    if pivot_conf not in ("low", "med", "high"):
        pivot_conf = "med"

    rev = pivot.get("reversal") or {}
    rev_direction = (rev.get("direction") or "none") if rev else "none"
    if rev_direction not in ("long", "short", "none"):
        rev_direction = "none"

    def _fnum(v) -> str:
        try:
            return f"{float(v):.2f}" if v is not None else str(_PLACEHOLDER_NUM)
        except (ValueError, TypeError):
            return str(_PLACEHOLDER_NUM)

    def _num_from_prose(v) -> float | None:
        """Extract the LAST price-magnitude number from a prose string.
        The LLM often writes things like "Sell a failed bounce that cannot
        reclaim 26,964, ideally after a stall in the 26,930-26,960 area" —
        the final "26,960" is usually the concrete entry zone."""
        if not isinstance(v, str):
            return None
        matches = re.findall(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,6}(?:\.\d+)?)", v)
        if not matches:
            return None
        try:
            return float(matches[-1].replace(",", ""))
        except ValueError:
            return None

    # Entry is often prose — extract a numeric fallback from the text.
    raw_entry = rev.get("entry_trigger")
    if isinstance(raw_entry, (int, float)):
        rev_entry = _fnum(raw_entry)
    else:
        num = _num_from_prose(raw_entry)
        rev_entry = _fnum(num) if num is not None else str(_PLACEHOLDER_NUM)
    rev_stop = _fnum(rev.get("stop"))
    rev_target = _fnum(rev.get("first_target"))

    shakeout = pivot.get("shakeout_reclaim") or {}
    reclaim_level = _fnum(shakeout.get("threshold"))

    flat_conds = pivot.get("flat_conditions") or []
    flat_c1 = flat_conds[0] if len(flat_conds) > 0 else ""
    flat_c2 = flat_conds[1] if len(flat_conds) > 1 else ""

    return (PIVOT_PINE_TEMPLATE
        .replace("{{DATE}}", date)
        .replace("{{YEAR}}", year)
        .replace("{{MONTH}}", str(int(month)))
        .replace("{{DAY}}", str(int(day)))
        .replace("{{PIVOT_HHMM}}", pivot_hhmm)
        .replace("{{PIVOT_HOUR}}", str(pivot_hour))
        .replace("{{PIVOT_MIN}}", str(pivot_min))
        .replace("{{CLASSIFICATION}}", classification)
        .replace("{{REVISED_BIAS}}", _esc(revised_bias))
        .replace("{{REVISED_INVALIDATION}}", _esc(revised_inval))
        .replace("{{PIVOT_CONFIDENCE}}", pivot_conf)
        .replace("{{REV_DIRECTION}}", rev_direction)
        .replace("{{REV_ENTRY}}", rev_entry)
        .replace("{{REV_STOP}}", rev_stop)
        .replace("{{REV_TARGET}}", rev_target)
        .replace("{{RECLAIM_LEVEL}}", reclaim_level)
        .replace("{{FLAT_COND_1}}", _esc(flat_c1))
        .replace("{{FLAT_COND_2}}", _esc(flat_c2))
    )
