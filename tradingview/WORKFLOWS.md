# TradingView Replay Workflows

Two operator workflows built on TV Bar Replay mode. Both produce
structured `.md`+`.json` artifacts, view in the IntelligenceOS Console
UI at `http://127.0.0.1:8788`.

| Workflow | Looks backward / forward? | Cursor | CLI | UI tab |
|---|---|---|---|---|
| **Replay Analysis Daily Profile** | Backward (describe completed day) | Session close | `python -m tv_automation.daily_profile YYYY-MM-DD [--through YYYY-MM-DD]` | Profiles |
| **Replay Forecast** | Forward (predict rest of day, grade at close) | 10:00 → 12:00 → 14:00 → 16:00 | `python -m tv_automation.daily_forecast YYYY-MM-DD` | Forecasts |

---

## Replay Analysis Daily Profile Workflow

**Goal:** build a reference-day DB by profiling a completed RTH session's
narrative, pivots, labels, and time-marker behavior. Each profile becomes
a comparable for future sessions.

**Pipeline:**
1. `replay.enter_replay(page)` — activate Bar Replay.
2. `replay.select_start_date(page, datetime(Y, M, D, 17, 0))` — pick 17:00 to
   land near the 16:00 close (picker drifts ~1hr backward).
3. Frame the full RTH view — wheel-down on the time-axis strip anchored
   at x≈200 (left), then a small zoom-in at center to hide previous-day
   slivers.
4. `profile_gate.verify_full_session(screenshot_path)` — Fast Instant
   ChatGPT reads leftmost/rightmost x-axis labels; gate passes if
   `first ≤ 10:15` and `last ≥ 15:30`.
5. `chatgpt_web.analyze_via_chatgpt_web(..., model="Thinking", ...)` —
   profiles the day with Money Print layout semantics embedded in the
   system prompt (⭐GOAT, red/green circles, orange/blue banks, time-
   marker colors).
6. Save `profiles/{SYMBOL}_{YYYY-MM-DD}.{md,json}`.

**Outputs:**
```
tradingview/profiles/MNQ1_2026-03-16.md   ← narrative with frontmatter
tradingview/profiles/MNQ1_2026-03-16.json ← tags, pivots, labels, time-markers
```

**CLI:**
```bash
cd tradingview
.venv/bin/python -m tv_automation.daily_profile 2026-04-06
.venv/bin/python -m tv_automation.daily_profile 2026-04-06 --through 2026-04-10  # profile a full week
```
Options:
- `--symbol MNQ1` — filename prefix (default)
- `--through YYYY-MM-DD` — profile each weekday in the inclusive range
  (skips Sat/Sun; does NOT skip US market holidays)
- `--resume` — skip dates whose `.json` already exists on disk

Per-day work ≈ 3-5 min (framing + gate + Thinking call).

---

## Replay Forecast Workflow

**Goal:** predict rest of an RTH session from partial cursors at 10:00,
12:00, and 14:00 ET, then grade predictions at 16:00 against the actual
outcome.

**CLI:**
```bash
cd tradingview
.venv/bin/python -m tv_automation.daily_forecast 2026-03-18
```
Options:
- `--symbol MNQ1` — filename prefix (default)
- `--resume` — skip stages whose `.json` already exists (recovers mid-run crashes from filesystem state alone)

Run time: ~15-20 min per day (4× ChatGPT Thinking calls + 4× framing +
~360 keyboard `Shift+ArrowRight` presses). Progress visible in
`audit/YYYY-MM-DD.jsonl`.

**Stages:**
1. **F1 @ 10:00** — 30 bars of RTH data, early-session forecast.
2. **F2 @ 12:00** — 150 bars, lunch-pivot context added.
3. **F3 @ 14:00** — 270 bars, final afternoon-drive forecast.
4. **Reconciliation @ 16:00** — grades each forecast on direction, close
   range, HOD/LOD capture, structural tags, tactical bias profitability.
   Uses matching `profiles/{SYMBOL}_{DATE}.json` as ground truth if
   present; else grades from the 16:00 screenshot alone.

**Outputs (in `tradingview/forecasts/`):**
```
MNQ1_2026-03-18_1000.{md,json}            ← F1
MNQ1_2026-03-18_1200.{md,json}            ← F2
MNQ1_2026-03-18_1400.{md,json}            ← F3
MNQ1_2026-03-18_reconciliation.{md,json}  ← grades
```

---

## Shared Infrastructure

| Module                             | Purpose                                    |
|------------------------------------|--------------------------------------------|
| `tv_automation/chatgpt_web.py`     | Drive chatgpt.com via attached Chrome      |
| `tv_automation/profile_gate.py`    | Pre-dispatch framing gate (Instant-tier)   |
| `tv_automation/replay.py`          | Replay primitives (enter, select_date, step_forward) |
| `tv_automation/daily_forecast.py`  | Forecast orchestrator + CLI                |
| `tv_automation/daily_profile.py`   | Profile orchestrator + CLI                 |
| `pine/bar_date_readout.pine`       | Cursor-time indicator (legend-scrapable)   |

**Key primitive**: `page.keyboard.press("Shift+ArrowRight")` advances the
replay cursor exactly one bar. TV removed stable `title`/`data-name`
attributes on the step-forward button — the keyboard shortcut is the only
reliable surface. Verified: 1 press = 1 bar, scales linearly past 120.

---

## UI Surfaces

Console at `127.0.0.1:8788`:

- **▦ Profiles tab** — list of profiled days with direction badges and
  shape sentences. Detail view: screenshot + tag pills + rendered
  narrative. "Capture" button grabs today's chart for side-by-side.
- **◆ Forecasts tab** — list of forecasted days; clicking a day loads
  all 4 stage cards (F1/F2/F3/reconciliation) with screenshots +
  narratives.

**Endpoints:**
```
GET /api/profiles                                  → summary list
GET /api/profiles/{key}                            → json + markdown
GET /api/profiles/{key}/screenshot                 → PNG

GET /api/forecasts                                 → days grouped
GET /api/forecasts/{symbol}/{date}/{stage}         → stage json + md
GET /api/forecasts/{symbol}/{date}/{stage}/screenshot → PNG
```
Stage values: `1000` | `1200` | `1400` | `reconciliation`.

---

## Prerequisites

- Chrome running with CDP (`tradingview/start_chrome_cdp.sh`)
- TradingView signed in, Money Print layout active on MNQ1! 1m chart
- `chatgpt.com` signed in (same Chrome) — `chatgpt_web` drives it via
  the subscription, not the API
- UI server running (`tradingview/run-ui.sh`) if using the UI tabs

---

## Known Issues

1. **TV replay date picker drifts ~1h earlier than requested** — workaround:
   pick `17:00` to aim for `16:00`, verify via BarDate, step-adjust. Sometimes
   the drift is larger (observed jumps to previous day); re-run `select_start_date`
   or exit/re-enter replay if it lands wrong.
2. **BarDate Pine indicator drifts after bar stepping** — the `barstate.islast`
   context doesn't always track the cursor. Trust step-count arithmetic
   (`120 bars = 120 minutes on 1m`) over BarDate text for subsequent positions.
3. **Watchlist sidebar can auto-open during navigation** — pollutes screenshots.
   Press `Escape` before capture; a future fix is to use the existing
   `/api/chart/screenshot` helper with `area="chart"` to crop out sidebar drift.
4. **Forecasts systematically underestimate trend-day range** — the 2026-03-18
   reconciliation caught this: direction/structure read well, but all 3
   forecasts underpriced the downside by 130-190 pts. Mitigation baked into
   `_FORECAST_SYSTEM` ("widen ranges aggressively on trend days"); tighten
   further as more reconciliations accumulate.

---

## File Layout

```
tradingview/
├── tv_automation/
│   ├── chatgpt_web.py         # ChatGPT web driver (shared)
│   ├── profile_gate.py        # pre-dispatch framing gate
│   ├── replay.py              # replay primitives
│   ├── daily_forecast.py      # forecast orchestrator + CLI
│   └── daily_profile.py       # profile orchestrator + CLI
├── pine/
│   └── bar_date_readout.pine  # cursor-time readout indicator
├── profiles/                  # profile artifacts (md + json)
├── forecasts/                 # forecast artifacts (md + json)
├── ui/                        # Profiles + Forecasts tab frontend
└── ui_server.py               # backend endpoints for both tabs
```

---

## Cross-Workflow Usage

The two workflows compose:
- Run **forecast** on a past day → reconciliation grades against whatever
  ground truth exists.
- If that day has a **profile** on disk (`profiles/{SYMBOL}_{DATE}.json`),
  reconciliation uses it as structured ground truth (better grading
  fidelity than from screenshot alone).
- Best calibration loop: profile a day first, then run the forecast on it
  — reconciliation now has authoritative actual tags to grade against,
  and you get immediate signal on where the forecast prompt is weak.
