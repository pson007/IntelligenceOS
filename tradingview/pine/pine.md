# Pine — IntelligenceOS reference

Canonical context for Pine script work in this repo. Living doc — update whenever
the Pine architecture shifts, whenever you learn a new v6 gotcha, whenever you
add a detector or input group.

**Read this before editing any `.pine` file or `forecast_pine.py`.**

---

## Purpose

All Pine scripts in this repo are **single-user, single-chart** helpers for
day-trading MNQ1! on the attached Chrome / TradingView session. Not Pine
Publish material. Not configured for multi-symbol use. Correctness for
*Phirun's MNQ RTH workflow* matters more than generality.

The flagship is the **Forecast Overlay** — an indicator that renders a
pre-session forecast (from `forecasts/*.json`) as live-tracking levels,
phase labels, manipulation detectors, and a status table. Everything else
is support.

---

## File layout

```
tradingview/pine/
├── pine.md                          # THIS FILE — canonical Pine reference
├── generated/                       # render_pine() output (LLM-generated + template-generated)
│   ├── forecast_overlay_YYYY-MM-DD.pine
│   ├── MNQ1__analysis_YYYYMMDD-HHMMSS.pine     # single-TF / deep analyze Pine
│   └── vwap.pine                    # hand-written utilities
├── applied/                         # snapshots of Pine actually applied via apply_pine.py
├── captures/                        # screenshots captured post-apply
├── drawings/                        # chart-drawing state dumps
├── parse_failures/                  # full LLM responses when Pine extraction fails
├── bar_date_readout.pine            # tiny utility — prints YYYY-MM-DD of cursor bar
├── webhook_alert.pine               # alert-firing helper
└── forecast_overlay_2026-04-21.pine # the ORIGINAL hand-written prototype (kept as reference)

tradingview/tv_automation/
└── forecast_pine.py                 # PINE_TEMPLATE + render_pine() — source of truth for the overlay
```

**Rule**: never hand-edit `pine/generated/forecast_overlay_*.pine` directly.
Edit the `PINE_TEMPLATE` string in `forecast_pine.py` and regenerate. The
generated file is downstream of the template.

The hand-written `pine/forecast_overlay_2026-04-21.pine` is the historical
prototype — the template was derived from it. Keep it for archaeology.

---

## Architecture — how Pine gets to the chart

```
forecasts/MNQ1_YYYY-MM-DD_pre_session.json       (ChatGPT-generated forecast)
    │
    ▼
tv_automation/forecast_pine.py :: render_pine()  (template + .replace() substitution)
    │
    ▼
pine/generated/forecast_overlay_YYYY-MM-DD.pine  (final Pine source)
    │
    ▼
apply_pine.py (subprocess)                        (CDP-attach → TV Pine Editor → Save → Add-to-chart)
    │
    ▼
TradingView chart                                 (overlay is now live)
```

Regeneration command (run from `tradingview/`):

```bash
.venv/bin/python -c "
import json
from pathlib import Path
from tv_automation.forecast_pine import render_pine
data = json.loads(Path('forecasts/MNQ1_2026-04-22_pre_session.json').read_text())
Path('pine/generated/forecast_overlay_2026-04-22.pine').write_text(render_pine(data))
"
```

UI also does this automatically via the "Generate Pine" button (see
`POST /api/forecasts/{symbol}/{date}/{stage}/pine/generate` in `ui_server.py`).

---

## Pine version

**Always v6.** `//@version=6` is mandatory. Pine v4/v5 are not accepted by
this repo. If an external source provides v5 code, upgrade it before pasting.
Key v6 differences that matter:

- Tuple destructuring with `[...]` on the left of `=`.
- `ta.vwap(source, anchor, stdev_mult)` tuple-return form (was separate calls in v5).
- `request.security(..., lookahead=barmerge.lookahead_off)` required flag.
- `barstate.isconfirmed` is the standard anti-repaint guard.
- String format in `str.tostring` accepts `+#.##;-#.##` for signed numbers.

---

## Current Pine inventory

### `forecast_overlay_YYYY-MM-DD.pine` (the main overlay)

Generated from `forecast_pine.py::PINE_TEMPLATE`. Current ~635 lines. Structure:

1. **Inputs** — forecast inputs (year/month/day, direction, %-range, GOAT, etc.) +
   detector-tuning inputs (`vol_lookback`, `atr_len`, 9 `show_*` toggles).
2. **Date / session detection** — `t_0930`, `t_1000`, `t_1030`, `t_1200`, `t_1400`, `t_1600`
   NY-timezone anchors via `timestamp("America/New_York", fyear, fmonth, fday, H, M, 0)`.
3. **State tracking** — `var` declarations for open_price, morning_low/high, CVD, ib_high/low,
   pending-confirmation state, all `_fired` flags.
4. **Open / target / stop derivation** — computed once on first in_today_rth bar.
5. **CVD accumulator** — `close > open ? +volume : -volume`, summed during RTH.
6. **Session tints** — `bgcolor()` for opening / GOAT / afternoon drive windows.
7. **VWAP + bands** — `ta.vwap(hlc3, rth_just_opened, 1.0)` tuple-return; plotted
   only on target-day RTH.
8. **Prior-day H/L/C** — `request.security(syminfo.tickerid, "D", X[1], lookahead=off)`.
9. **IB H/L plots** — step-lines from the `ib_high`/`ib_low` tracked during 09:30–10:30.
10. **ATR** — `ta.atr(atr_len)` for follow-through magnitude gating.
11. **Right-edge zone lines + labels** — OPEN / TP1 / TP2 / STOP, redrawn on
    `barstate.islast` with `line.delete` then `line.new`.
12. **Phase labels** — 09:30 OPEN, 10:00 STOP LOCKED, 12:00 GOAT, 14:00 DRIVE.
    09:30 / 12:00 / 14:00 anchor to an **overhead rail** (close_target_hi + buffer);
    10:00 anchors at the stop line (`style_label_left`).
13. **Time-marker vlines** — 10:00 blue, 12:00 red, 14:00 green, 16:00 yellow.
    Money Print convention.
14. **NOW marker** — single white dotted vline at current bar, redrawn on islast.
15. **Dynamic triggers** — RECLAIM / FAIL / INVALIDATED / TARGET HIT / TARGET FAKE.
16. **Manipulation detectors** — STOP HUNT (sweep + reclaim of stop), VOL climax.
17. **Confirmation layer** — ✓/✗ follow-through (ATR-gated), MR BREAK ↑/↓,
    VWAP RECLAIM/REJECT.
18. **Status table** — `table.new(position.top_right, 2, 13)`. Rows 0–12:
    header / direction / open / close target / morning low-or-high / GOAT /
    status / action / bias / → to stop / → to target / CVD / Confirmations.
19. **Alertconditions** — 7 `alertcondition()` declarations at end.

### Other Pine scripts

- **`bar_date_readout.pine`** — tiny utility. Displays `YYYY-MM-DD` on chart,
  used in the Replay workflow to verify which bar the cursor is on.
- **`webhook_alert.pine`** — fires TV alerts that hit the Cloudflare Worker
  (`tv-worker/`). Paired with the worker's webhook ingest.
- **`MNQ1__analysis_*.pine`** — LLM-generated Pine from single-TF analyze and
  deep-analyze flows. Annotations only (not strategies). Generated ad-hoc.
- **`vwap.pine`** — hand-written VWAP reference with bands. Deprecated in
  favor of the VWAP block inside `forecast_pine.py`, but kept for standalone use.

---

## Pine v6 gotchas (learned the hard way — don't forget these)

### Timezone

- `hour` and `minute` return the bar's time in **exchange timezone** by default.
  For CME symbols like MNQ, that's `America/Chicago`. A check like `hour == 9`
  fires at 10:00 ET, not 09:30 ET — silently off by one hour.
- **Fix**: always compare `time` against explicit `timestamp("America/New_York", ...)`
  anchors. Never use raw `hour`/`minute` for wall-clock gates.

### Variable scoping in functions

- Variables assigned inside a user-defined function are **local to that function**.
  You cannot mutate a `var` from outside the function's scope.
- Concrete: `f_arm_confirm() => pending_bar := bar_index` creates a **local**
  `pending_bar`, doesn't touch the global.
- **Fix**: inline state-mutation logic. Repeat three lines if needed — don't
  try to DRY with a helper that assigns globals.

### `barstate.isconfirmed` vs raw bar evaluation

- Detectors that fire mid-bar can flicker on and off as ticks arrive. A "STOP
  HUNT" label can fire at 10:15:32 then disappear at 10:15:58 when the bar closes
  above the stop.
- **Fix**: always gate real-time detectors with `barstate.isconfirmed`. Costs up
  to one-bar latency; prevents false alarms.

### `ta.vwap` signature forms

- `ta.vwap(source)` — single series, session-anchored (CME default = 18:00 prior day).
- `ta.vwap(source, anchor)` — single series, custom anchor (our 09:30 RTH reset).
- `ta.vwap(source, anchor, stdev_mult)` — **tuple** `[vwap, upper, lower]`. Passing
  the 3rd arg is what switches the return type.

### `request.security` lookahead

- `request.security(syminfo.tickerid, "D", close[1])` **without** `lookahead=off`
  can leak today's daily close into historical bars, causing the indicator to
  repaint on page-refresh. Always pass `lookahead=barmerge.lookahead_off`.

### `alertcondition` vs `_fired` flags

- `alertcondition()` is a *declaration*, evaluated every bar. Its condition should
  be the **raw trigger** (`stop_hunt_now and barstate.isconfirmed`), not the
  `_fired` flag (which mutates inside an if-block mid-bar and creates evaluation-
  order dependencies).
- TV's "Only Once" alert option handles deduplication at schedule time.

### `str.tostring` format chars

- Pine's format syntax recognizes `#`, `0`, `.`, `-`, `+`. Other letters are
  *sometimes* literals, sometimes unpredictable. Don't rely on `"+#.#k"` to
  append a "k" suffix — concat explicitly: `str.tostring(x, "+#.#;-#.#") + "k"`.

### Multi-line expressions

- Continuation works when the continuation line is *more deeply indented* than
  the first line. No explicit `\\` needed.
- Ternaries chained across 3+ lines are edge-case territory; use parens and
  indent consistently.

### `var` initialization timing

- `var x = NA` only runs once on the first historical bar. On subsequent bars,
  `x` retains its last value. This is useful for accumulators (CVD, ib_high)
  and one-shot flags — but easy to misuse.
- **Never** assume `var` resets per session. It resets once, ever. Handle
  session resets explicitly (e.g. `if rth_just_opened: x := 0`).

### Extend.both on vertical lines

- `line.new(bar_index, low, bar_index, high, extend=extend.both)` with x1 == x2
  creates a vertical line that extends infinitely up and down. Cleaner than
  computing "safe" y-bounds from session range.

### Pine label/line budget

- Default limits (set via `indicator(max_lines_count=N, max_labels_count=N)`):
  current overlay uses `max_lines_count=30, max_labels_count=100`. A multi-month
  historical chart with many target-day signals won't hit this because the
  overlay is single-date.

---

## Layout + visual conventions

### Label vertical anchoring

- **Phase labels** (09:30 / 12:00 / 14:00) → overhead rail
  (`close_target_hi + (hi - lo) * 0.4`) with `style_label_down`. Keeps them above
  price action on trending days.
- **10:00 STOP LOCKED** → anchored at `invalidation_level` with `style_label_left`.
  Sits directly on the stop line.
- **RECLAIM / FAIL** → at that bar's high/low.
- **STOP HUNT / TARGET FAKE** → at wick extremum (`low` for long stop-hunt,
  `high` for long target-fake) with `style_label_up`/`down` inverse.
- **VOL climax** → bar's extreme with `size.tiny`.
- **Follow-through ✓/✗** → same side as the trigger (inherits `pending_up`).

### Line conventions

- **Horizontal zone lines** (OPEN / TP1 / TP2 / STOP): `line.new(bar_index - 100,
  y, bar_index + 5, y, extend=extend.right)`. The `-100` / `+5` is mostly aesthetic.
- **Vertical time markers**: `line.new(bar_index, low, bar_index, high,
  extend=extend.both)` — vertical, extends to infinity up/down.
- **NOW marker**: same pattern, thinner + white dotted.
- **Horizontal step-lines** (prior-day H/L/C, IB): use `plot(..., style=plot.style_stepline)`.

### Color map

| Color | Used for |
|-------|---------|
| yellow | 09:30 open, opening window tint, STOP HUNT label |
| red | stop, INVALIDATED, FAIL, MR BREAK ↓, 12:00 vline |
| green | close target, RECLAIM, MR BREAK ↑, 14:00 vline |
| orange | TARGET FAKE, VWAP line + bands, VWAP RECLAIM/REJECT |
| aqua | GOAT midday, GOAT label, → to target row |
| blue | 10:00 vline, prior-day H/L |
| purple | VOL climax label, IB lines |
| white | prior-day close, NOW marker, table labels |
| gray | OPEN level (background), CVD when zero |

### Label size guidance

- `size.large` → rare, high-signal events (STOP HUNT, TARGET FAKE)
- `size.normal` → phase labels, MR BREAK, trigger labels (RECLAIM/FAIL/INVALIDATED/TARGET HIT)
- `size.small` → right-edge zone labels (OPEN/TP1/TP2/STOP), VWAP events, follow-through ✓/✗
- `size.tiny` → VOL climax (happens many times per session)

---

## Recipes

### Add a new input/toggle

1. In `forecast_pine.py::PINE_TEMPLATE`, under the **Detector tuning** or
   **Detectors — toggles** group, add an `input.bool`/`input.float`/`input.int`.
2. Gate the detector's firing block with `and show_your_thing` (for bool toggles).
3. Regenerate. Apply. Check the TV Settings pane shows the new input.

### Add a new detector

1. Decide if it's rare (1-2×/session) or frequent. Rare → `_fired` flag for
   one-shot. Frequent → cooldown (`bar_index - last_X_bar >= N`).
2. Add state vars near existing `_fired` flags.
3. Define the detector condition as a named bool above the detector block:
   `my_thing_now = ... and barstate.isconfirmed`.
4. Draw label inside the detector block, gated by a new `show_my_thing` toggle.
5. If it's a confirmation signal: increment `confirm_score` and add to the
   5-max score semantics (currently 4 event-driven + 1 CVD).
6. Add `alertcondition()` at the end of the template using the raw `my_thing_now`
   expression (not the `_fired` flag).

### Add a new status-table row

1. Bump `table.new(position.top_right, 2, N)` — increment N by 1.
2. Add two `tbl.cell()` calls at row index N-1 (the new bottom row).
3. If the value is computed, add `var`/local vars above. Keep the
   computation inside the `if barstate.islast and in_target_day` block
   so it only runs once per bar.
4. Color the value by semantic meaning (green = good, red = warning,
   aqua = neutral info, gray = stale/not-yet).

### Add a new phase label

1. Add the wall-clock anchor: `t_HHMM = timestamp("America/New_York", fyear,
   fmonth, fday, H, M, 0)` near the other `t_*` anchors.
2. Add `var bool phase_X_drawn = false`.
3. Add a firing block: `if in_target_day and time >= t_HHMM and not phase_X_drawn
   and not na(close_target_hi): phase_X_drawn := true; f_rail_label(...)`.

### Adjust the overhead rail

- Rail formula: `close_target_hi + max(close_target_hi - close_target_lo, 20) * 0.4`.
- Tighter rail (labels closer to price): reduce the `0.4` multiplier.
- Looser rail (labels higher up): increase.
- Falls back to `close + 20` if close_target values are NA.

### Adjust IB window

- Change `t_1030 = timestamp("America/New_York", fyear, fmonth, fday, 10, 30, 0)`
  to a different time.
- IB is tracked by the `if in_today_rth and time < t_1030` block — same anchor
  is referenced.

---

## Things NOT to do

- **Don't use `hour`/`minute`** for wall-clock gates. Always use NY-anchored
  `timestamp()` comparisons.
- **Don't edit `pine/generated/*.pine` by hand.** Edit the template, regenerate.
- **Don't call `context.close()` from apply_pine.py.** CDP-attach means that
  kills the user's Chrome. (Not a Pine rule, but relevant — noted here because
  it's adjacent territory.)
- **Don't try to mutate `var` globals from inside a function.** Inline the assignment.
- **Don't rely on `str.tostring` format strings with unusual literal chars.**
  Concatenate the suffix.
- **Don't forget `barstate.isconfirmed`** on real-time detectors. Repainting
  detectors are worse than no detectors.
- **Don't forget `lookahead=barmerge.lookahead_off`** on `request.security` calls.
- **Don't amend `//@version=5`** — Pine v6 only.
- **Don't write a strategy when you want an indicator.** `strategy()` has different
  semantics (equity curve, execution model) and is visually similar but behaviorally
  very different from `indicator()`.

---

## Regen cheat sheet

| Action | Command |
|--------|---------|
| Regenerate today's forecast overlay | UI → Forecasts tab → "Generate Pine" for target date |
| Regenerate via CLI | `cd tradingview && .venv/bin/python -c "from tv_automation.forecast_pine import render_pine; ..."` (see top) |
| Apply to chart | UI → Forecasts tab → "Apply Pine", OR `python apply_pine.py pine/generated/forecast_overlay_YYYY-MM-DD.pine` |
| Server log tail | `tail -f /tmp/ui_server.log` |
| Pine editor close (side dock) | selector `[aria-label="Close"]` on `.tv-script-widget` |
| Pine editor close (bottom dock) | selector `[aria-label="Collapse panel"]` in widget bar |

---

## Session history (append as you work)

Track significant structural edits to `forecast_pine.py::PINE_TEMPLATE` here —
the git log captures *what*, but this captures *why*.

- **2026-04-22** — added manipulation detectors (STOP HUNT, TARGET FAKE, VOL climax),
  RTH-VWAP, CVD. First detector layer.
- **2026-04-22** — added confirmation signals (✓/✗ follow-through, MR BREAK,
  VWAP RECLAIM/REJECT) + Confirmations table row.
- **2026-04-22** — blind-spot audit sweep: converted all `hour`/`minute` gates
  to NY-anchored `timestamp()` comparisons (timezone correctness), added
  `confirm_score` reset on invalidation, per-detector toggles, ATR follow-through
  floor, CVD-in-score, VWAP ±1σ bands, prior-day H/L/C, Initial Balance plots,
  7 `alertcondition()` declarations.

---

## When updating this file

- Add gotchas as you encounter them. Future-you (or Claude) will thank present-you.
- Keep the "Things NOT to do" list appended — don't delete old anti-patterns even
  if they feel obvious now.
- Update "Current Pine inventory" line-count approximations when things grow.
- Append to "Session history" when making structural (not cosmetic) changes.
- Don't let this file become a Pine tutorial — keep it codebase-specific. Gotchas,
  recipes, decisions, history. Generic Pine docs live at tradingview.com.
