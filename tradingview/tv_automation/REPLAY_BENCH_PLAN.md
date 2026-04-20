# Replay-driven backtest harness — design + handoff

Context written 2026-04-19 so this build can resume in a remote session
without replaying the full conversation. Scope: building a TradingView
Bar Replay → Analyze → grade loop to validate model prediction quality
against real historical bars, with outcomes written to the existing
`decision_log.py` store so calibration math at `/api/decisions/calibration`
works over backtest data, not just live trades.

---

## Goal

Run many Analyze samples against historical MNQ1! data using
TradingView's Bar Replay feature, grade each prediction's outcome by
walking the subsequent bars for first-touch of stop vs TP, and write
`(prediction, confidence, outcome, realized_r)` rows into `decisions.db`.
The point is to answer "at what confidence threshold does the model
actually produce positive expectancy," with enough samples to get real
statistical signal — instead of waiting months of live trades to
accumulate it.

---

## v1 design decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Analyze mode | **Single-TF** (not Deep) | ~3× throughput (15–20s vs 45–60s per sample); matches the mode actually used for live entries; simpler grading model (one tuple per sample, not a multi-fire strategy) |
| Grading | **Precise bar-walk** (first-touch of stop vs TP) | Crude close-after-N-bars hides the stop-tag-by-a-tick asymmetry that kills strategies in practice |
| Provider | **`claude_web` + Sonnet 4.6** | Repo default; subscription-only cost; 3× sample count vs pressure-testing three providers at same wall-clock |
| Symbol / TF | **MNQ1! on 5m** | Matches live primary; TV Replay supports 5m with deep history |
| Window | **Last 90 days, RTH-only, sample every 4 trading hours** | ~100 samples assumes RTH 09:30–16:15 ET only (~2 T₀s/day × ~63 trading days). All-hours (CME 23/5) at 4h step produces ~360 T₀s — use `--rth-only` (default) vs `--all-hours` to control. |
| Grading horizon | **40 bars forward (~3.3hr on 5m)** | Matches actual day-trade hold times; 200-bar would wash out day-trade signal with swing P&L |

Don't pressure-test from day one. Run the same 50-sample fixture across
providers *after* the harness works; multiplies noise if done up front.

---

## What exists now

### Probe: [probes/probe_replay.py](probes/probe_replay.py)

Working. Attaches to live Chrome via `tv_context()`, activates Replay,
catalogs every control in the playback strip, deactivates, writes JSON
snapshot to `probes/snapshots/replay-*.json`. Leaves the chart in the
state it found it.

Run:
```bash
cd /Users/pson/Desktop/IntelligenceOS/tradingview
.venv/bin/python -m tv_automation.probes.probe_replay
```

Prereqs: Chrome running with CDP on `localhost:9222`, TV chart tab
open and signed in.

### Selector map (stable anchors, survive TV build rotations)

Top toolbar:
```
button[aria-label="Bar replay"]   # toggle activate/deactivate
```
Multiple DOM copies render (responsive-layout variants). MUST walk matches
and pick the visible one — `.first` can pick the hidden duplicate.

Playback strip (visible only when Replay is active):
```
div[data-name="replay-bottom-toolbar"]                              # container
div[data-role="button"][title="Select date"]                        # opens date picker
div[data-role="button"][data-qa-id="select-date-bar-mode-menu"]     # starting-point mode
div[data-role="button"][title="Replay speed"]                       # speed selector
div[data-role="button"][title="Update interval"]                    # TF interval
div[data-role="button"][title="Jump to real-time chart"]            # return to live
div[data-role="button"][title="Exit Bar Replay"]                    # exit
```

### Selectors we DO NOT have

Play/pause (x≈1004) and step-forward (x≈1042) buttons have **no title
and no aria-label** — only hashed class names (`-IWka22iN` suffix
rotates) and a `data-tooltip-hotkey` attribute. Targeting these by DOM
is fragile.

**Recommended workaround**: use TradingView's keyboard shortcuts.
- `Shift + →` = step forward 1 bar
- `Shift + ←` = step backward 1 bar
- (space bar or similar for play/pause — confirm during `replay.py` build)

Keyboard is both simpler and more durable than icon-only-div clicking.

### Not yet probed

The **date picker modal** that opens when "Select date" is clicked.
Need to catalog its input format and confirm button before the harness
can programmatically jump to a T₀. This is the next probe if we want
DOM-level date entry; alternative is typing into the input field
directly with Playwright's keyboard.

---

## Proposed module: `tv_automation/replay.py`

Public surface (async, all take `page` from `tv_context()`):

```python
async def enter_replay(page) -> None
async def exit_replay(page) -> None
async def is_active(page) -> bool                            # checks for strip container

async def select_start_date(page, when: datetime) -> None    # click "Select date", type, confirm
async def step_forward(page, bars: int = 1) -> None          # Shift+→ × N via keyboard
async def step_backward(page, bars: int = 1) -> None         # Shift+← × N
async def set_speed(page, speed: str) -> None                # "1x" | "3x" | "10x"

# Read the current replay cursor's timestamp from the strip —
# needed because after step_forward(N), we want to know what bar
# we're now on.
async def current_replay_ts(page) -> datetime
```

Must use the "walk locator matches, pick visible" helper — `.first`
will silently select the hidden responsive duplicate. Extract this
pattern into `lib/` (likely a new helper `lib/visible_locator.py` or
add to `lib/selectors.py`) since every Replay call needs it.

Wrap every action with `audit.log("replay.*", ...)` per repo convention
so the bench run streams progress through `/api/audit/tail`.

---

## Harness: `tv_automation/replay_bench.py`

CLI shape:
```
python -m tv_automation.replay_bench \
  --symbol MNQ1! --tf 5m \
  --start 2026-01-19 --end 2026-04-19 \
  --step 4h --horizon 40 \
  --provider claude_web --model sonnet
```

Loop body (per sample):

```
1. Chart.set_symbol(MNQ1!, 5m) if needed
2. replay.enter_replay()
3. replay.select_start_date(T₀)
4. Set audit.current_request_id contextvar to a fresh uuid for this sample
   analyze_mtf.analyze_chart(symbol, tf=5m, provider, model)
   → returns a DICT: {signal, confidence, entry, stop, tp, rationale, ...}
   → analyze_chart() itself already calls decision_log.log_decision()
     using the contextvar's request_id — bench does NOT write the row
5. For i in 1..40:
     replay.step_forward(1)
     read current bar's high/low from crosshair HUD or chart data
     if signal==Long:
       if low ≤ stop  → outcome=hit_stop,  realized_r = -1.0; break
       if high ≥ tp   → outcome=hit_tp,    realized_r = +|tp-entry|/|stop-entry|; break
     elif signal==Short: (mirror)
   else (no touch after 40 bars):
     outcome=expired; realized_r = mark-to-market close pnl in R
6. decision_log.set_outcome(request_id, outcome, realized_r)
7. replay.exit_replay()
8. Advance T₀ by --step (4h of trading time, skip weekends/overnight gaps)
```

Don't run during market hours — chart contention with live trading.
The harness should refuse to start if `now()` is inside CME RTH unless
`--force` is passed.

**Resume semantics**: 100-sample runs will fail partway eventually
(network blip, TV re-auth prompt, selector drift). Cheap mitigation:
append each attempted T₀ + its request_id to a checkpoint file
(e.g. `tradingview/benchmarks/replay_bench_<run_id>.jsonl`). On
`--resume <run_id>`, skip T₀s already present in the checkpoint AND
already graded in `decisions.db` (outcome IS NOT NULL). A crashed
sample with no outcome gets re-run.

**State restoration**: wrap the whole loop in `try/finally` that
ensures `replay.exit_replay()` runs and restores pre-run symbol/TF,
even on crash. A bench that dies mid-sample must not leave the user's
morning chart stuck in Replay mode.

Leverage existing infra:
- [analyze_mtf.py](analyze_mtf.py) — `analyze_chart()` unchanged (but pass `provider="claude_web"`)
- [decision_log.py](decision_log.py) — `log_decision()` is already called inside `analyze_chart()`; bench only needs `set_outcome(request_id, outcome, realized_r)` at the end of each sample
- [lib/audit.py](lib/audit.py) — log `replay_bench.sample_start/done/fail` with `request_id` contextvar so UI can tail
- [chart.py](chart.py) — symbol/TF nav

---

## Unknowns / flagged before starting

1. **Reading bar OHLC during Replay**. Three options:
   - (a) Hover crosshair over each bar, read the HUD label. Slow, fragile.
   - (b) Scrape TV's internal chart data via DevTools JS evaluation
         (likely possible since the data is in memory — needs probing).
   - (c) Fetch OHLCV from an external source (yfinance / polygon / CME).
         Cleanest separation but adds a dependency.
   - **Recommendation**: start with (a) — slow but works today, ~300
     lines. Migrate to (b) or (c) only if the 100-sample run is
     unworkably slow.

2. **Date picker input format**. Not yet probed. Likely accepts
   text input like `2026-01-19 09:30` — needs the "Select date" click
   flow to be inspected. 30-min probe.

3. **Play/pause hotkey**. `Shift+→` for step-forward is documented.
   Toggle play/pause shortcut not confirmed — may need to DOM-click
   the unlabeled x=1004 button as a fallback. For our harness the
   step-forward primitive is sufficient; play/pause is a nice-to-have.

4. **Replay data depth on 5m**. TradingView's Replay historical depth
   differs by plan tier. User has Pro+ → should have plenty of 5m
   history, but hasn't been verified. First sample attempt at
   `--start 90d ago` confirms or fails fast.

5. **Non-determinism crosscheck**. `claude_web` non-deterministic on the
   same image. For headline results, consider re-sampling k=3 per T₀
   and taking majority signal + mean confidence. Not v1 — v1 runs k=1
   and we see if the signal is loud enough without.

6. **`current_replay_ts` readback**. "Select date" button exists in the
   strip, but it's unverified whether its visible text reflects the
   cursor's *current* bar after `Shift+→` steps, or only the originally
   picked date. If the latter, the bar-walk loop can't self-report
   progress — need either a different source (hover HUD, DevTools JS
   eval) or to track cursor position client-side (T₀ + N × bar_seconds).
   15-min probe.

---

## Files and paths to keep in view

Existing:
- [CLAUDE.md](../../CLAUDE.md) — project-wide rules, provider tradeoffs,
  conventions. Read first on resume.
- [analyze_mtf.py](analyze_mtf.py) — `analyze_chart()` single-TF entry point.
- [decision_log.py](decision_log.py) — SQLite schema, write/update API.
- [reconcile.py](reconcile.py) — CLI for manual outcome reconciliation;
  shares the same `set_outcome()` call we'll use from the harness.
- [chart.py](chart.py) — symbol/TF navigation, `_TIMEFRAME_MAP`.
- [lib/audit.py](lib/audit.py), [lib/guards.py](lib/guards.py).
- [probes/probe_replay.py](probes/probe_replay.py) — reference pattern
  for any future probe passes.
- [probes/snapshots/replay-*.json](probes/snapshots/) — last capture.

To build:
- `tv_automation/replay.py` — module. Surface above.
- `tv_automation/replay_bench.py` — CLI harness.
- `lib/visible_locator.py` (or add to `lib/selectors.py`) — the
  "walk matches, pick visible" helper.
- (Maybe) `probes/probe_replay_datepicker.py` — if we go DOM-level on
  the date picker instead of keyboard-typing.

Results land in:
- `decisions.db` (existing) — outcomes visible via `/api/decisions/*`
  endpoints and the existing calibration surface.
- `audit/YYYY-MM-DD.jsonl` — per-sample progress.

---

## Commands to resume

```bash
# 1. Verify probe still works (selectors might have drifted if TV shipped)
cd /Users/pson/Desktop/IntelligenceOS/tradingview
.venv/bin/python -m tv_automation.probes.probe_replay

# 2. Inspect the latest snapshot if selectors differ
ls -t tv_automation/probes/snapshots/replay-*.json | head -1 | xargs cat | jq .

# 3. Probe the date picker (next probe task — not yet written)
#    Click "Select date", catalog the modal, snapshot.
```

---

## Delta from this conversation

Already done during the planning convo:
- Removed 1M TF pill, added 30s/45s pills (UI + `_TIMEFRAME_MAP` + `TV_INTERVAL_TO_PILL`).
- Updated `DEFAULT_DEEP_TIMEFRAMES` to the 10 UI pills; updated `_DEEP_SYSTEM_PROMPT`, docstring, and all "9 TFs" references.
- Added `POST /api/analyze/{task_id}/cancel` endpoint + Stop button in the analyze progress strip.
- Wrote + ran [probes/probe_replay.py](probes/probe_replay.py); captured the selector map above.

Not yet:
- Any code in `tv_automation/replay.py`.
- Any code in `tv_automation/replay_bench.py`.
- Date-picker probe.
- Bar OHLC extraction technique chosen.
- Anything committed — all changes currently uncommitted on `main`.
