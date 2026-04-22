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
//   * Open price (gray) — labelled with open_type so you know the expected opening behavior
//   * Close target band (green dashed) — TP1/TP2 labels with the action at each
//   * Stop level — morning low (up bias) or morning high (down bias), locks at 10:00 ET
//   * Time-window background tints — opening, midday GOAT, afternoon drive
//   * Phase-transition event labels at 09:30 / 10:00 / 12:00 / 14:00 anchoring the plan
//   * Money Print time markers — 10 BLUE · 12 RED · 14 GREEN · 16 YELLOW vertical lines
//   * NOW marker — thin dotted vertical at current bar for quick locate on dense charts
//   * RTH-anchored VWAP + ±1σ bands — orange, resets 09:30 each day
//   * Prior-day H / L / C — classic intraday pivots
//   * Initial Balance (09:30–10:30) H / L — first-hour range
//   * Dynamic trigger labels — RECLAIM / FAIL / INVALIDATED / TARGET HIT / TARGET FAKE
//   * Manipulation detectors — STOP HUNT (sweep + reclaim of stop), VOL climax bars
//   * Confirmation signals — ✓/✗ follow-through (ATR-gated), MR BREAK ↑/↓, VWAP RECLAIM/REJECT
//   * Status table top-right — bias, levels, current phase, ACTION hint,
//                              → to stop / → to target / CVD / Confirmations ●●●●○
//   * Alerts — STOP HUNT, MR BREAK, VWAP aligned, TARGET HIT, INVALIDATED, TARGET FAKE
//
// All time gates use explicit America/New_York anchors (via timestamp()) so the
// indicator behaves correctly regardless of chart-vs-exchange-timezone config.

indicator("IOS Forecast Overlay {{DATE}}", overlay=true,
     max_lines_count=30, max_labels_count=100)

// ---------------------------------------------------------------------------
// Forecast inputs (defaults pinned to {{DATE}} pre-session forecast)
// ---------------------------------------------------------------------------
fyear  = input.int({{YEAR}}, "Forecast year",  group="Forecast")
fmonth = input.int({{MONTH}}, "Forecast month", group="Forecast", minval=1, maxval=12)
fday   = input.int({{DAY}}, "Forecast day",   group="Forecast", minval=1, maxval=31)

direction       = input.string("{{DIRECTION}}",       "Direction",       options=["up","down"], group="Forecast")
confidence      = input.string("{{CONFIDENCE}}",      "Confidence",      options=["low","med","high"], group="Forecast")
net_pct_lo      = input.float({{NET_PCT_LO}},         "Net % lo (open→close)", step=0.05, group="Forecast")
net_pct_hi      = input.float({{NET_PCT_HI}},         "Net % hi (open→close)", step=0.05, group="Forecast")
goat_label      = input.string("{{GOAT_LABEL}}",      "GOAT window",     group="Forecast")
open_type       = input.string("{{OPEN_TYPE}}",       "Open type",       group="Forecast")
tactical_bias   = input.string("{{TACTICAL_BIAS}}",   "Tactical bias",   group="Forecast")
afternoon_drive = input.string("{{AFTERNOON_DRIVE}}", "Afternoon drive", group="Forecast")
invalidation    = input.string("{{INVALIDATION}}",    "Invalidation",    group="Forecast")

// Detector tuning — tuned for 1m–15m. Bump lookback on seconds/tick charts.
vol_lookback   = input.int(20, "Volume lookback (bars)", minval=5, maxval=500,
     group="Detectors", tooltip="Bars for volume-spike baseline. 20 works for 1m–15m. Use 60+ for seconds/tick charts.")
vol_spike_mult = input.float(2.0, "Volume spike ×", minval=1.2, step=0.1,
     group="Detectors", tooltip="Bar volume must exceed lookback SMA × this multiple to flag a climax.")
atr_len        = input.int(14, "ATR length (follow-through floor)", minval=1, maxval=100,
     group="Detectors", tooltip="ATR window used to gate ✓/✗ follow-through labels. Smaller = more confirmations.")
followthrough_mult = input.float(0.25, "Follow-through min (× ATR)", minval=0.0, step=0.05,
     group="Detectors", tooltip="Next-bar move must exceed ATR × this fraction to count as a confirmation. 0 disables the floor.")

// Per-detector visibility toggles.
show_vwap          = input.bool(true, "Show RTH VWAP",           group="Detectors — toggles")
show_vwap_bands    = input.bool(true, "Show VWAP ±1σ bands",     group="Detectors — toggles")
show_prior_levels  = input.bool(true, "Show prior-day H/L/C",    group="Detectors — toggles")
show_ib            = input.bool(true, "Show Initial Balance (09:30–10:30)", group="Detectors — toggles")
show_stop_hunt     = input.bool(true, "Show STOP HUNT label",    group="Detectors — toggles")
show_target_fake   = input.bool(true, "Show TARGET FAKE label",  group="Detectors — toggles")
show_vol_climax    = input.bool(true, "Show VOL climax labels",  group="Detectors — toggles")
show_followthrough = input.bool(true, "Show ✓/✗ follow-through", group="Detectors — toggles")
show_mr_break      = input.bool(true, "Show MR BREAK label",     group="Detectors — toggles")
show_vwap_event    = input.bool(true, "Show VWAP RECLAIM/REJECT label", group="Detectors — toggles")

is_long = direction == "up"

// ---------------------------------------------------------------------------
// Date / session detection — explicit America/New_York anchors.
// Avoids the classic Pine gotcha where `hour`/`minute` reflect the EXCHANGE
// timezone (Chicago for CME), which would skew every wall-clock gate by 1h.
// ---------------------------------------------------------------------------
in_target_day = year == fyear and month == fmonth and dayofmonth == fday

t_0930 = timestamp("America/New_York", fyear, fmonth, fday, 9,  30, 0)
t_1000 = timestamp("America/New_York", fyear, fmonth, fday, 10, 0,  0)
t_1030 = timestamp("America/New_York", fyear, fmonth, fday, 10, 30, 0)
t_1200 = timestamp("America/New_York", fyear, fmonth, fday, 12, 0,  0)
t_1400 = timestamp("America/New_York", fyear, fmonth, fday, 14, 0,  0)
t_1600 = timestamp("America/New_York", fyear, fmonth, fday, 16, 0,  0)

in_rth       = time >= t_0930 and time < t_1600
in_today_rth = in_target_day and in_rth

// ---------------------------------------------------------------------------
// State tracking — captured per-bar, persistent across the session via `var`
// ---------------------------------------------------------------------------
var float open_price        = na
var float morning_low       = na
var float morning_high      = na
var float close_target_lo   = na
var float close_target_hi   = na
var bool  morning_lock      = false
var bool  opened_below_open = false
var bool  opened_above_open = false
var bool  reclaim_fired     = false
var bool  fail_fired        = false
var bool  target_fired      = false
var bool  inval_fired       = false
var bool  stop_hunt_fired   = false
var bool  target_fake_fired = false
var float cvd               = 0.0
var int   last_climax_bar   = -999
// Confirmation state — follow-through + structural confirmations of the forecast.
// pending_* arms a next-bar check; confirm_score counts aligned-with-bias events.
var int    pending_bar       = -1
var string pending_kind      = ""
var bool   pending_up        = false
var float  pending_ref       = na
var int    confirm_score     = 0
var bool   mr_break_up_fired = false
var bool   mr_break_dn_fired = false
var bool   vwap_event_fired  = false
// Initial Balance — classic first-60-min range (09:30–10:30). Complements
// morning_low/high (09:30–10:00). IB levels often act as intraday pivots.
var float ib_high = na
var float ib_low  = na

if in_today_rth and na(open_price)
    open_price       := open
    close_target_lo  := open_price * (1 + net_pct_lo / 100)
    close_target_hi  := open_price * (1 + net_pct_hi / 100)

opening_window = in_today_rth and time < t_1000
if opening_window
    morning_low  := na(morning_low)  ? low  : math.min(morning_low, low)
    morning_high := na(morning_high) ? high : math.max(morning_high, high)
    if not na(open_price) and low < open_price
        opened_below_open := true
    if not na(open_price) and high > open_price
        opened_above_open := true

// IB builds across the first hour (09:30–10:30).
if in_today_rth and time < t_1030
    ib_high := na(ib_high) ? high : math.max(ib_high, high)
    ib_low  := na(ib_low)  ? low  : math.min(ib_low,  low)

if in_today_rth and time >= t_1000 and not morning_lock
    morning_lock := true

// Prior-day H/L/C (from daily TF). lookahead=off means we see ONLY data that
// was available at real-time on the target day — no look-ahead bias.
prior_close = request.security(syminfo.tickerid, "D", close[1], lookahead=barmerge.lookahead_off)
prior_high  = request.security(syminfo.tickerid, "D", high[1],  lookahead=barmerge.lookahead_off)
prior_low   = request.security(syminfo.tickerid, "D", low[1],   lookahead=barmerge.lookahead_off)

invalidation_level = is_long ? morning_low : morning_high
stop_side_text     = is_long ? "below" : "above"
tp_hi_action       = is_long ? "trim longs" : "cover shorts"
tp_lo_action       = is_long ? "long entry base" : "short entry base"

// Volume baseline + CVD (session-anchored approximated delta).
// CVD approximates net buy/sell pressure using close-vs-open sign × bar volume.
// True tick delta is not available in Pine — this is the standard proxy.
vol_avg = ta.sma(volume, vol_lookback)
if in_today_rth
    cvd := cvd + (close > open ? volume : close < open ? -volume : 0.0)

// ---------------------------------------------------------------------------
// Time-window background tints (opening window is 09:30–10:00)
// ---------------------------------------------------------------------------
in_opening = in_today_rth and time < t_1000
in_goat    = in_today_rth and time >= t_1200 and time < t_1400
in_drive   = in_today_rth and time >= t_1400 and time < t_1600

bgcolor(in_opening ? color.new(color.yellow, 92) : na, title="Opening")
bgcolor(in_goat    ? color.new(color.aqua,   90) : na, title="GOAT midday")
bgcolor(in_drive   ? color.new(color.green,  93) : na, title="Afternoon drive")

// RTH-anchored VWAP with ±1σ bands — resets at 09:30 each day. The tuple form
// of ta.vwap returns the mean + both deviation bands in a single pass.
rth_just_opened = in_today_rth and not in_today_rth[1]
[vwap_val, vwap_up1, vwap_dn1] = ta.vwap(hlc3, rth_just_opened, 1.0)
plot(show_vwap and in_today_rth ? vwap_val : na,
     "VWAP", color=color.new(color.orange, 20), linewidth=1)
plot(show_vwap and show_vwap_bands and in_today_rth ? vwap_up1 : na,
     "VWAP +1σ", color=color.new(color.orange, 65), linewidth=1)
plot(show_vwap and show_vwap_bands and in_today_rth ? vwap_dn1 : na,
     "VWAP -1σ", color=color.new(color.orange, 65), linewidth=1)

// Prior-day H/L/C — classic intraday pivots. Drawn as step lines so each level
// holds flat across the session (constant values).
plot(show_prior_levels and in_today_rth ? prior_high  : na,
     "Prior High",  color=color.new(color.blue,  30), linewidth=1, style=plot.style_stepline)
plot(show_prior_levels and in_today_rth ? prior_low   : na,
     "Prior Low",   color=color.new(color.blue,  30), linewidth=1, style=plot.style_stepline)
plot(show_prior_levels and in_today_rth ? prior_close : na,
     "Prior Close", color=color.new(color.white, 40), linewidth=1, style=plot.style_stepline)

// Initial Balance high/low — populates during 09:30–10:30, then flat.
plot(show_ib and in_today_rth and not na(ib_high) ? ib_high : na,
     "IB High", color=color.new(color.purple, 35), linewidth=1, style=plot.style_stepline)
plot(show_ib and in_today_rth and not na(ib_low) ? ib_low : na,
     "IB Low",  color=color.new(color.purple, 35), linewidth=1, style=plot.style_stepline)

// ATR for follow-through magnitude gating.
atr_val = ta.atr(atr_len)

// ---------------------------------------------------------------------------
// Persistent zone lines + action labels — redrawn on last bar at right edge
// ---------------------------------------------------------------------------
var line  ln_open       = na
var line  ln_target_lo  = na
var line  ln_target_hi  = na
var line  ln_inval      = na
var label lbl_open      = na
var label lbl_target_lo = na
var label lbl_target_hi = na
var label lbl_inval     = na

if barstate.islast and not na(open_price)
    line.delete(ln_open)
    ln_open := line.new(bar_index - 100, open_price, bar_index + 5, open_price,
         color=color.gray, width=1, extend=extend.right)
    label.delete(lbl_open)
    lbl_open := label.new(bar_index + 5, open_price,
         text="OPEN " + str.tostring(open_price, "#.##") + "  —  " + open_type,
         color=color.new(color.gray, 40), textcolor=color.white,
         style=label.style_label_left, size=size.small)

    line.delete(ln_target_lo)
    ln_target_lo := line.new(bar_index - 100, close_target_lo,
         bar_index + 5, close_target_lo,
         color=color.new(color.green, 20), width=1, style=line.style_dashed,
         extend=extend.right)
    label.delete(lbl_target_lo)
    lbl_target_lo := label.new(bar_index + 5, close_target_lo,
         text="TP1 " + str.tostring(close_target_lo, "#.##") + "  —  " + tp_lo_action,
         color=color.new(color.green, 70), textcolor=color.white,
         style=label.style_label_left, size=size.small)

    line.delete(ln_target_hi)
    ln_target_hi := line.new(bar_index - 100, close_target_hi,
         bar_index + 5, close_target_hi,
         color=color.new(color.green, 20), width=1, style=line.style_dashed,
         extend=extend.right)
    label.delete(lbl_target_hi)
    lbl_target_hi := label.new(bar_index + 5, close_target_hi,
         text="TP2 " + str.tostring(close_target_hi, "#.##") + "  —  " + tp_hi_action,
         color=color.new(color.green, 40), textcolor=color.white,
         style=label.style_label_left, size=size.small)

if barstate.islast and not na(invalidation_level)
    line.delete(ln_inval)
    ln_inval := line.new(bar_index - 100, invalidation_level,
         bar_index + 5, invalidation_level,
         color=color.red, width=2, style=line.style_dotted,
         extend=extend.right)
    label.delete(lbl_inval)
    lbl_inval := label.new(bar_index + 5, invalidation_level,
         text=(morning_lock ? "STOP " : "stop forming ")
              + str.tostring(invalidation_level, "#.##")
              + "  —  close " + stop_side_text + " = OUT",
         color=color.new(color.red, 40), textcolor=color.white,
         style=label.style_label_left, size=size.small)

// ---------------------------------------------------------------------------
// Phase-transition event labels — drawn once per day on the transitioning bar.
// Phase labels (09:30/12:00/14:00) anchor to an overhead rail above the close
// target so they don't collide with price action on trending days. The 10:00
// STOP LOCKED label anchors directly on the stop line (style_label_left).
// ---------------------------------------------------------------------------
var bool phase_open_drawn  = false
var bool phase_lock_drawn  = false
var bool phase_goat_drawn  = false
var bool phase_drive_drawn = false

f_overhead_y() =>
    float _rng  = na(close_target_hi) or na(close_target_lo) ? 50.0 : math.max(close_target_hi - close_target_lo, 20.0)
    float _base = na(close_target_hi) ? close : close_target_hi
    _base + _rng * 0.4

f_rail_label(_text, _col) =>
    label.new(bar_index, f_overhead_y(), text=_text,
         color=color.new(_col, 20), textcolor=color.white,
         style=label.style_label_down, size=size.normal, yloc=yloc.price)

if in_target_day and time >= t_0930 and time < t_1000 and not phase_open_drawn and not na(close_target_hi)
    phase_open_drawn := true
    f_rail_label("09:30 OPEN  ·  watch: " + open_type, color.yellow)

if in_target_day and time >= t_1000 and not phase_lock_drawn and not na(invalidation_level)
    phase_lock_drawn := true
    label.new(bar_index, invalidation_level,
         text="10:00 STOP LOCKED @ " + str.tostring(invalidation_level, "#.##"),
         color=color.new(color.red, 20), textcolor=color.white,
         style=label.style_label_left, size=size.small, yloc=yloc.price)

if in_target_day and time >= t_1200 and not phase_goat_drawn and not na(close_target_hi)
    phase_goat_drawn := true
    f_rail_label("12:00 GOAT  ·  " + goat_label, color.aqua)

if in_target_day and time >= t_1400 and not phase_drive_drawn and not na(close_target_hi)
    phase_drive_drawn := true
    f_rail_label("14:00 DRIVE  ·  " + afternoon_drive, color.green)

// ---------------------------------------------------------------------------
// Time-marker vertical lines (Money Print convention)
//   10:00 BLUE  ·  12:00 RED  ·  14:00 GREEN  ·  16:00 YELLOW
// Drawn once each when the session first crosses the marker hour.
// ---------------------------------------------------------------------------
var bool vline_10_drawn = false
var bool vline_12_drawn = false
var bool vline_14_drawn = false
var bool vline_16_drawn = false

f_vline(_col) =>
    line.new(bar_index, low, bar_index, high,
         color=color.new(_col, 55), width=1, style=line.style_dashed,
         extend=extend.both)

if in_target_day and time >= t_1000 and not vline_10_drawn
    vline_10_drawn := true
    f_vline(color.blue)
if in_target_day and time >= t_1200 and not vline_12_drawn
    vline_12_drawn := true
    f_vline(color.red)
if in_target_day and time >= t_1400 and not vline_14_drawn
    vline_14_drawn := true
    f_vline(color.green)
if in_target_day and time >= t_1600 and not vline_16_drawn
    vline_16_drawn := true
    f_vline(color.yellow)

// ---------------------------------------------------------------------------
// NOW marker — thin vertical line at current bar, helps locate cursor on dense charts
// ---------------------------------------------------------------------------
var line ln_now = na
if barstate.islast and in_target_day
    line.delete(ln_now)
    ln_now := line.new(bar_index, low, bar_index, high,
         color=color.new(color.white, 70), width=1, style=line.style_dotted,
         extend=extend.both)

// ---------------------------------------------------------------------------
// Dynamic trigger labels — fire once when a signal condition is confirmed
// ---------------------------------------------------------------------------
if in_opening and is_long and opened_below_open and not reclaim_fired and not na(open_price) and close > open_price
    reclaim_fired := true
    pending_bar   := bar_index
    pending_kind  := "RECLAIM"
    pending_up    := true
    pending_ref   := close
    label.new(bar_index, high,
         text="RECLAIM  ·  long trigger",
         color=color.new(color.green, 10), textcolor=color.white,
         style=label.style_label_down, size=size.normal)

if in_opening and not is_long and opened_above_open and not fail_fired and not na(open_price) and close < open_price
    fail_fired   := true
    pending_bar  := bar_index
    pending_kind := "FAIL"
    pending_up   := false
    pending_ref  := close
    label.new(bar_index, low,
         text="FAIL  ·  short trigger",
         color=color.new(color.red, 10), textcolor=color.white,
         style=label.style_label_up, size=size.normal)

stop_broken = morning_lock and not na(invalidation_level) and (is_long ? close < invalidation_level : close > invalidation_level)
if in_today_rth and stop_broken and not inval_fired
    inval_fired   := true
    confirm_score := 0  // setup invalidated — zero the score rather than lie about the past
    label.new(bar_index, is_long ? low : high,
         text="INVALIDATED  ·  exit",
         color=color.new(color.red, 0), textcolor=color.white,
         style=is_long ? label.style_label_up : label.style_label_down,
         size=size.normal)

// Target-fakeout: poke through target, close back inside. Classic "trap the
// chase-buyer" pattern. Must be evaluated BEFORE target_hit so we can suppress
// the plain-vanilla HIT label when the same bar is actually a rejection.
target_fake_now = not na(close_target_hi) and not na(close_target_lo) and
     (is_long ? (high > close_target_hi and close < close_target_hi)
              : (low  < close_target_lo and close > close_target_lo))
if in_today_rth and target_fake_now and not target_fake_fired and barstate.isconfirmed and show_target_fake
    target_fake_fired := true
    label.new(bar_index, is_long ? high : low,
         text="TARGET FAKE  ·  rejected " + str.tostring(is_long ? close_target_hi : close_target_lo, "#.##"),
         color=color.new(color.orange, 10), textcolor=color.white,
         style=is_long ? label.style_label_down : label.style_label_up,
         size=size.large)

target_hit = is_long ? (not na(close_target_hi) and high >= close_target_hi) : (not na(close_target_lo) and low <= close_target_lo)
if in_today_rth and target_hit and not target_fired and not target_fake_now
    target_fired := true
    label.new(bar_index, is_long ? high : low,
         text="TARGET HIT  ·  " + tp_hi_action,
         color=color.new(color.green, 0), textcolor=color.white,
         style=is_long ? label.style_label_down : label.style_label_up,
         size=size.normal)

// ---------------------------------------------------------------------------
// Real-time detectors — manipulation / anomaly signals keyed on bar geometry
//
//   STOP HUNT   : sweep of invalidation_level that reclaims (close back inside)
//                 — most common algo-driven stop-out pattern.
//   VOL climax  : bar volume > vol_lookback SMA × vol_spike_mult
//                 — institutional activity marker; 3-bar cooldown to suppress clusters.
//
// All detectors use barstate.isconfirmed so signals don't flicker on/off as
// the current bar ticks — they fire only when the bar closes.
// ---------------------------------------------------------------------------
stop_hunt_now = morning_lock and not na(invalidation_level) and
     (is_long ? (low  < invalidation_level and close > invalidation_level)
              : (high > invalidation_level and close < invalidation_level))
if in_today_rth and stop_hunt_now and not stop_hunt_fired and barstate.isconfirmed and show_stop_hunt
    stop_hunt_fired := true
    pending_bar     := bar_index
    pending_kind    := "STOP HUNT"
    pending_up      := is_long
    pending_ref     := close
    label.new(bar_index, is_long ? low : high,
         text="STOP HUNT  ·  reclaimed " + str.tostring(invalidation_level, "#.##"),
         color=color.new(color.yellow, 10), textcolor=color.black,
         style=is_long ? label.style_label_up : label.style_label_down,
         size=size.large)

vol_climax = not na(vol_avg) and vol_avg > 0 and volume > vol_avg * vol_spike_mult
if in_today_rth and vol_climax and barstate.isconfirmed and (bar_index - last_climax_bar) >= 3 and show_vol_climax
    last_climax_bar := bar_index
    label.new(bar_index, close > open ? high : low,
         text="VOL " + str.tostring(volume / vol_avg, "#.#") + "×",
         color=color.new(color.purple, 30), textcolor=color.white,
         style=close > open ? label.style_label_down : label.style_label_up,
         size=size.tiny)

// ---------------------------------------------------------------------------
// Confirmation signals
//
//   Follow-through  : on bar N+1 after RECLAIM / FAIL / STOP HUNT fires,
//                     draw ✓ (close moved further in signaled direction)
//                     or ✗ (close reversed). Small label; real-time trust gauge.
//   MR BREAK ↑ / ↓  : first post-10:00 close beyond morning_high / morning_low.
//                     Structural confirmation the forecast direction has traction.
//   VWAP RECLAIM /  : first RTH close crossing VWAP in the bias direction.
//   VWAP REJECT      One-shot; strong mean-reversion confirmation.
//
//   confirm_score counts events aligned with the forecast direction (max 4).
//   Shown in the status table as filled dots.
// ---------------------------------------------------------------------------

// Follow-through check on the bar AFTER a trigger fired. The ATR-based
// magnitude floor prevents "confirmed" from firing on trivial 0.25pt drifts.
if pending_bar >= 0 and bar_index == pending_bar + 1 and barstate.isconfirmed and in_today_rth
    float move       = pending_up ? close - pending_ref : pending_ref - close
    float min_move   = na(atr_val) ? 0.0 : atr_val * followthrough_mult
    bool  confirmed  = move > min_move
    if show_followthrough
        label.new(bar_index, pending_up ? high : low,
             text=(confirmed ? "✓ " : "✗ ") + pending_kind,
             color=color.new(confirmed ? color.lime : color.red, 20),
             textcolor=color.black,
             style=pending_up ? label.style_label_down : label.style_label_up,
             size=size.small)
    if confirmed
        confirm_score := confirm_score + 1
    pending_bar := -1

// Morning Range break — structural confirmation of bias direction
if in_today_rth and morning_lock and not na(morning_high) and not mr_break_up_fired and close > morning_high and barstate.isconfirmed
    mr_break_up_fired := true
    if show_mr_break
        label.new(bar_index, high,
             text="MR BREAK ↑ " + str.tostring(morning_high, "#.##"),
             color=color.new(color.green, 0), textcolor=color.white,
             style=label.style_label_down, size=size.normal)
    if is_long
        confirm_score := confirm_score + 1

if in_today_rth and morning_lock and not na(morning_low) and not mr_break_dn_fired and close < morning_low and barstate.isconfirmed
    mr_break_dn_fired := true
    if show_mr_break
        label.new(bar_index, low,
             text="MR BREAK ↓ " + str.tostring(morning_low, "#.##"),
             color=color.new(color.red, 0), textcolor=color.white,
             style=label.style_label_up, size=size.normal)
    if not is_long
        confirm_score := confirm_score + 1

// VWAP cross aligned with bias
vwap_cross_up = in_today_rth and not na(vwap_val) and not na(vwap_val[1]) and close > vwap_val and close[1] <= vwap_val[1]
vwap_cross_dn = in_today_rth and not na(vwap_val) and not na(vwap_val[1]) and close < vwap_val and close[1] >= vwap_val[1]
vwap_aligned  = (is_long and vwap_cross_up) or (not is_long and vwap_cross_dn)
if vwap_aligned and not vwap_event_fired and barstate.isconfirmed
    vwap_event_fired := true
    confirm_score    := confirm_score + 1
    if show_vwap_event
        label.new(bar_index, is_long ? low : high,
             text="VWAP " + (is_long ? "RECLAIM ↑" : "REJECT ↓"),
             color=color.new(color.orange, 20), textcolor=color.white,
             style=is_long ? label.style_label_up : label.style_label_down,
             size=size.small)

// ---------------------------------------------------------------------------
// Status table (top-right) — levels, phase, current action hint
// ---------------------------------------------------------------------------
var table tbl = table.new(position.top_right, 2, 13,
     bgcolor=color.new(color.black, 75), border_width=1,
     border_color=color.new(color.gray, 50))

// Confirmation-score dots — e.g. score=3 returns "●●●○"
f_dots(_score, _max) =>
    string s = ""
    for i = 0 to _max - 1
        s := s + (i < _score ? "●" : "○")
    s

f_status() =>
    string s = "PRE-OPEN"
    if in_today_rth
        s := time < t_1000 ? "OPENING (09:30–10:00)" :
             time < t_1200 ? "POST-OPEN WATCH (10:00–12:00)" :
             time < t_1400 ? "MIDDAY GOAT (12:00–14:00)" :
             time < t_1600 ? "AFTERNOON DRIVE (14:00–16:00)" :
             "CLOSE"
    if stop_broken
        s := "INVALIDATED — broke " + (is_long ? "morning low" : "morning high")
    s

f_action() =>
    string a = "Wait for open"
    if in_today_rth
        a := time < t_1000 ? ("Watch: " + open_type) :
             time < t_1200 ? ("Stop @ " + str.tostring(invalidation_level, "#.##") + " · " + tactical_bias) :
             time < t_1400 ? ("GOAT: primary " + direction + " entry — " + goat_label) :
             time < t_1600 ? ("Drive: " + afternoon_drive) :
             "Close positions"
    a

if barstate.islast and in_target_day
    bias_color = is_long ? color.green : color.red
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

    tbl.cell(0, 4, is_long ? "Morning low" : "Morning high", text_color=color.white)
    tbl.cell(1, 4, na(invalidation_level) ? "—" : str.tostring(invalidation_level, "#.##"),
         text_color=color.red)

    tbl.cell(0, 5, "GOAT", text_color=color.white)
    tbl.cell(1, 5, goat_label, text_color=color.aqua)

    tbl.cell(0, 6, "Status", text_color=color.white)
    tbl.cell(1, 6, status, text_color=status_col)

    tbl.cell(0, 7, "Action", text_color=color.white)
    tbl.cell(1, 7, f_action(), text_color=color.orange, text_halign=text.align_left)

    tbl.cell(0, 8, "Bias", text_color=color.white)
    tbl.cell(1, 8, tactical_bias, text_color=color.white, text_halign=text.align_left)

    if not na(invalidation_level) and not na(close)
        d = is_long ? close - invalidation_level : invalidation_level - close
        tbl.cell(0, 9, "→ to stop", text_color=color.white)
        tbl.cell(1, 9, str.tostring(d, "+#.##;-#.##") + " pts",
             text_color=d > 0 ? color.green : color.red)

    if not na(close_target_hi) and not na(close_target_lo) and not na(close)
        t_tgt = is_long ? close_target_hi : close_target_lo
        d_tgt = is_long ? t_tgt - close : close - t_tgt
        tbl.cell(0, 10, "→ to target", text_color=color.white)
        tbl.cell(1, 10, str.tostring(d_tgt, "+#.##;-#.##") + " pts",
             text_color=color.aqua, text_halign=text.align_right)

    // CVD — directionally-weighted cumulative volume. Proxy for tick delta.
    cvd_col = cvd > 0 ? color.green : cvd < 0 ? color.red : color.gray
    tbl.cell(0, 11, "CVD", text_color=color.white)
    tbl.cell(1, 11, str.tostring(cvd / 1000.0, "+#.#;-#.#") + "k",
         text_color=cvd_col, text_halign=text.align_right)

    // Confirmations — 4 event-driven + 1 live (CVD aligned with bias).
    // Events (confirm_score): follow-through ✓, STOP HUNT follow-through, MR BREAK
    // aligned, VWAP reclaim aligned. CVD is continuous and contributes live.
    bool  cvd_aligned   = (is_long and cvd > 0) or (not is_long and cvd < 0)
    int   event_score   = math.min(confirm_score, 4)
    int   live_score    = event_score + (cvd_aligned ? 1 : 0)
    int   max_confirm   = 5
    color dots_col      = live_score >= 4 ? color.lime :
                          live_score >= 3 ? color.yellow :
                          live_score >= 2 ? color.orange :
                          live_score >= 1 ? color.gray : color.new(color.gray, 50)
    tbl.cell(0, 12, "Confirmations", text_color=color.white)
    tbl.cell(1, 12, f_dots(live_score, max_confirm)
         + "  " + str.tostring(live_score) + "/" + str.tostring(max_confirm),
         text_color=dots_col, text_halign=text.align_right)

// ---------------------------------------------------------------------------
// Alerts — set these up in TV's Alert dialog (dropdown lists these conditions).
// Each uses the raw trigger condition (pre-fired-flag) so TV's "Only Once"
// option handles deduplication at the alert-scheduling layer.
// ---------------------------------------------------------------------------
alertcondition(in_today_rth and stop_hunt_now and barstate.isconfirmed,
     title="STOP HUNT",
     message="MNQ1 STOP HUNT: {{close}} swept and reclaimed stop")
alertcondition(in_today_rth and morning_lock and not na(morning_high) and close > morning_high and barstate.isconfirmed,
     title="MR BREAK ↑",
     message="MNQ1 closed above morning high — bullish structural confirmation")
alertcondition(in_today_rth and morning_lock and not na(morning_low) and close < morning_low and barstate.isconfirmed,
     title="MR BREAK ↓",
     message="MNQ1 closed below morning low — bearish structural confirmation")
alertcondition(vwap_aligned and barstate.isconfirmed,
     title="VWAP aligned",
     message="MNQ1 VWAP reclaim/reject aligned with forecast bias")
alertcondition(in_today_rth and target_hit and barstate.isconfirmed,
     title="TARGET HIT",
     message="MNQ1 reached forecast target")
alertcondition(in_today_rth and stop_broken and barstate.isconfirmed,
     title="INVALIDATED",
     message="MNQ1 broke invalidation level — setup dead")
alertcondition(in_today_rth and target_fake_now and barstate.isconfirmed,
     title="TARGET FAKE",
     message="MNQ1 poked through target and rejected")
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
    tags = forecast.get("prediction_tags", {}) or {}
    bias = forecast.get("tactical_bias", {}) or {}

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

    open_type = pred.get("open_type") or tags.get("open_type") or "normal_open"
    tactical_bias = bias.get("bias") or "follow_forecast"
    afternoon_drive = tags.get("afternoon_drive") or "follow_bias"
    # Invalidation text can be long prose — trim so it fits the input box + chart label.
    invalidation = (bias.get("invalidation") or "see forecast").strip()
    if len(invalidation) > 180:
        invalidation = invalidation[:177] + "..."

    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

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
        .replace("{{GOAT_LABEL}}", _esc(goat_label))
        .replace("{{OPEN_TYPE}}", _esc(open_type))
        .replace("{{TACTICAL_BIAS}}", _esc(tactical_bias))
        .replace("{{AFTERNOON_DRIVE}}", _esc(afternoon_drive))
        .replace("{{INVALIDATION}}", _esc(invalidation))
    )
