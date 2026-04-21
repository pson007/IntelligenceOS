"""Generate a Pine v6 forecast-overlay indicator from a pre-session forecast JSON.

The hand-written `pine/forecast_overlay_2026-04-21.pine` was the prototype.
This module turns its structure into a template and fills in per-forecast
values (date, direction, %-range, GOAT window) from the saved forecast JSON.

Usage:
    from tv_automation.forecast_pine import render_pine
    text = render_pine(json.loads(Path("forecasts/MNQ1_2026-04-21_pre_session.json").read_text()))
    Path(f"pine/forecast_overlay_{date}.pine").write_text(text)

Placeholders use `{{NAME}}` (double-brace) to avoid colliding with Pine's
own `str.format("{0}")` syntax — `.replace()` substitution rather than
Python's `.format()` keeps the template Pine-syntax-safe even if we add
literal `{}`-using format calls later.
"""

from __future__ import annotations


PINE_TEMPLATE = """//@version=6
// Forecast Overlay — MNQ1! {{DATE}} ({{DOW}})
// Auto-generated from {{DATE}} pre-session forecast.
//
// Renders the pre-session forecast as live-tracking levels + a status panel:
//   * Open price (gray) — anchor for the forecast %
//   * Close target band (green dashed) — open × (1 + net_pct_lo) … open × (1 + net_pct_hi)
//   * Morning low / invalidation (red dotted, locks at 10:00 ET)
//   * Time-window background tints — opening, midday GOAT, afternoon drive
//   * Status table top-right — bias, levels, current phase, distance to invalidation

indicator("IOS Forecast Overlay {{DATE}}", overlay=true,
     max_lines_count=20, max_labels_count=20)

// ---------------------------------------------------------------------------
// Forecast inputs (defaults pinned to {{DATE}} pre-session forecast)
// ---------------------------------------------------------------------------
fyear  = input.int({{YEAR}}, "Forecast year",  group="Forecast")
fmonth = input.int({{MONTH}}, "Forecast month", group="Forecast", minval=1, maxval=12)
fday   = input.int({{DAY}}, "Forecast day",   group="Forecast", minval=1, maxval=31)

direction  = input.string("{{DIRECTION}}", "Direction",  options=["up","down"], group="Forecast")
confidence = input.string("{{CONFIDENCE}}","Confidence", options=["low","med","high"], group="Forecast")
net_pct_lo = input.float({{NET_PCT_LO}}, "Net % lo (open→close)", step=0.05, group="Forecast")
net_pct_hi = input.float({{NET_PCT_HI}}, "Net % hi (open→close)", step=0.05, group="Forecast")
goat_label = input.string("{{GOAT_LABEL}}", "GOAT window", group="Forecast")

// ---------------------------------------------------------------------------
// Date / session detection
// ---------------------------------------------------------------------------
in_target_day = year == fyear and month == fmonth and dayofmonth == fday
// MNQ1 RTH (CME index futures): 09:30–16:15 ET. Use hour/minute directly so
// the indicator works whether the chart is on RTH-only or 24h session.
in_rth = (hour > 9 or (hour == 9 and minute >= 30)) and hour < 16
in_today_rth = in_target_day and in_rth

// ---------------------------------------------------------------------------
// State tracking — captured per-bar, persistent across the session via `var`
// ---------------------------------------------------------------------------
var float open_price       = na
var float morning_low      = na
var float close_target_lo  = na
var float close_target_hi  = na
var bool  morning_low_lock = false

if in_today_rth and na(open_price)
    open_price       := open
    close_target_lo  := open_price * (1 + net_pct_lo / 100)
    close_target_hi  := open_price * (1 + net_pct_hi / 100)

if in_today_rth and hour == 9 and minute >= 30
    morning_low := na(morning_low) ? low : math.min(morning_low, low)
if in_today_rth and hour == 10 and minute == 0
    morning_low_lock := true

// ---------------------------------------------------------------------------
// Horizontal-line drawings
// ---------------------------------------------------------------------------
var line  ln_open      = na
var line  ln_target_lo = na
var line  ln_target_hi = na
var line  ln_inval     = na
var label lbl_target   = na
var label lbl_inval    = na

if barstate.islast and not na(open_price)
    line.delete(ln_open)
    ln_open := line.new(bar_index - 100, open_price, bar_index + 5, open_price,
         color=color.gray, width=1, extend=extend.right)

    line.delete(ln_target_lo)
    line.delete(ln_target_hi)
    ln_target_lo := line.new(bar_index - 100, close_target_lo,
         bar_index + 5, close_target_lo,
         color=color.new(color.green, 20), width=1, style=line.style_dashed,
         extend=extend.right)
    ln_target_hi := line.new(bar_index - 100, close_target_hi,
         bar_index + 5, close_target_hi,
         color=color.new(color.green, 20), width=1, style=line.style_dashed,
         extend=extend.right)

    label.delete(lbl_target)
    lbl_target := label.new(bar_index + 5, close_target_hi,
         text="Close target " + str.tostring(close_target_lo, "#.##")
              + " — " + str.tostring(close_target_hi, "#.##"),
         color=color.new(color.green, 60), textcolor=color.white,
         style=label.style_label_left, size=size.small)

if barstate.islast and not na(morning_low)
    line.delete(ln_inval)
    ln_inval := line.new(bar_index - 100, morning_low,
         bar_index + 5, morning_low,
         color=color.red, width=2, style=line.style_dotted,
         extend=extend.right)
    label.delete(lbl_inval)
    lbl_inval := label.new(bar_index + 5, morning_low,
         text=(morning_low_lock ? "INVALIDATION " : "morning low (forming) ")
              + str.tostring(morning_low, "#.##"),
         color=color.new(color.red, 60), textcolor=color.white,
         style=label.style_label_left, size=size.small)

// ---------------------------------------------------------------------------
// Time-window background tints
// ---------------------------------------------------------------------------
in_opening = in_today_rth and hour == 9
in_goat    = in_today_rth and hour >= 12 and hour < 14
in_drive   = in_today_rth and hour >= 14 and hour < 16

bgcolor(in_opening ? color.new(color.yellow, 92) : na, title="Opening")
bgcolor(in_goat    ? color.new(color.aqua,   90) : na, title="GOAT midday")
bgcolor(in_drive   ? color.new(color.green,  93) : na, title="Afternoon drive")

// ---------------------------------------------------------------------------
// Status table (top-right)
// ---------------------------------------------------------------------------
var table tbl = table.new(position.top_right, 2, 8,
     bgcolor=color.new(color.black, 75), border_width=1,
     border_color=color.new(color.gray, 50))

f_status() =>
    string s = "PRE-OPEN"
    if in_today_rth
        s := hour < 10 ? "OPENING (09:30–10:00)" :
             hour < 12 ? "TREND-UP WATCH (10:00–12:00)" :
             hour < 14 ? "MIDDAY GOAT WINDOW (12:00–14:00)" :
             hour < 16 ? "AFTERNOON DRIVE (14:00–16:00)" :
             "CLOSE"
    if morning_low_lock and not na(morning_low) and close < morning_low
        s := "INVALIDATED — closed below morning low"
    s

if barstate.islast and in_target_day
    bias_color = direction == "up" ? color.green : color.red
    status     = f_status()
    status_col = str.contains(status, "INVALID") ? color.red :
                 str.contains(status, "GOAT")    ? color.aqua : color.yellow

    tbl.cell(0, 0, "Forecast — {{DOW}} {{DATE}}",
         text_color=color.white, bgcolor=color.new(color.navy, 20),
         text_halign=text.align_center)
    tbl.merge_cells(0, 0, 1, 0)

    tbl.cell(0, 1, "Direction", text_color=color.white)
    tbl.cell(1, 1, str.upper(direction) + " (" + confidence + ")",
         text_color=bias_color)

    tbl.cell(0, 2, "Open", text_color=color.white)
    tbl.cell(1, 2, na(open_price) ? "—" : str.tostring(open_price, "#.##"),
         text_color=color.white)

    tbl.cell(0, 3, "Close target", text_color=color.white)
    tbl.cell(1, 3, na(close_target_lo) ? "—" :
         str.tostring(close_target_lo, "#.##") + " — "
         + str.tostring(close_target_hi, "#.##"),
         text_color=color.green)

    tbl.cell(0, 4, "Morning low", text_color=color.white)
    tbl.cell(1, 4, na(morning_low) ? "—" : str.tostring(morning_low, "#.##"),
         text_color=color.red)

    tbl.cell(0, 5, "GOAT window", text_color=color.white)
    tbl.cell(1, 5, goat_label, text_color=color.aqua)

    tbl.cell(0, 6, "Status", text_color=color.white)
    tbl.cell(1, 6, status, text_color=status_col)

    if not na(morning_low) and not na(close)
        d = close - morning_low
        tbl.cell(0, 7, "→ to inval", text_color=color.white)
        tbl.cell(1, 7, str.tostring(d, "+#.##;-#.##") + " pts",
             text_color=d > 0 ? color.green : color.red)
"""


def render_pine(forecast: dict) -> str:
    """Render a forecast-overlay Pine v6 indicator from a pre-session forecast JSON.

    Expects the standard pre-session forecast JSON shape (see
    `forecasts/MNQ1_YYYY-MM-DD_pre_session.json`). Returns a complete
    Pine source string ready to write to disk or paste into TV's Pine Editor.

    Defaults gracefully when fields are missing — the operator can always
    edit the indicator inputs in TV after applying.
    """
    date = forecast.get("date", "1970-01-01")
    dow = forecast.get("dow", "Day")
    year, month, day = date.split("-")

    pred = forecast.get("predictions", {}) or {}
    goat = forecast.get("probable_goat", {}) or {}

    direction = pred.get("direction", "up")
    if direction not in ("up", "down"):
        direction = "up"
    confidence = pred.get("direction_confidence", "med")
    if confidence not in ("low", "med", "high"):
        confidence = "med"

    net_pct_lo = pred.get("predicted_net_pct_lo", 0.25)
    net_pct_hi = pred.get("predicted_net_pct_hi", 0.85)

    goat_dir = (goat.get("direction") or "long").upper()
    goat_window = goat.get("time_window") or "midday"
    goat_label = f"{goat_window} {goat_dir}"

    return (PINE_TEMPLATE
        .replace("{{DATE}}", date)
        .replace("{{DOW}}", dow)
        .replace("{{YEAR}}", year)
        .replace("{{MONTH}}", str(int(month)))
        .replace("{{DAY}}", str(int(day)))
        .replace("{{DIRECTION}}", direction)
        .replace("{{CONFIDENCE}}", confidence)
        .replace("{{NET_PCT_LO}}", f"{float(net_pct_lo):.2f}")
        .replace("{{NET_PCT_HI}}", f"{float(net_pct_hi):.2f}")
        .replace("{{GOAT_LABEL}}", goat_label)
    )
