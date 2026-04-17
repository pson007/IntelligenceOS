# tv_automation

Browser automation library for TradingView. Drives the Chromium-Automation
profile over CDP to perform any action a user could perform in the TV UI.

**You do one thing**: make sure the Chromium-Automation window is open and
signed in to TradingView. Everything else — navigation, orders, Pine edits,
screenshots — happens by running CLI commands in this package.

## Precondition

One manual step: ensure the Chromium-Automation profile is signed in.

```bash
./start_chrome_cdp.sh          # relaunches Chromium with CDP on :9222
# → sign in to tradingview.com in that Chromium window ONCE
# → activate Paper Trading in the Account Manager ONCE
```

Cookies persist in the profile between runs. Re-sign-in is only needed if
TradingView actively invalidates the session (rare — cookies last weeks).

## Invocation

Two ways to run:

**`tv` shim** (works from any directory):
```bash
/Users/pson/Desktop/IntelligenceOS/tradingview/tv chart metadata
/Users/pson/Desktop/IntelligenceOS/tradingview/tv trading place-order NVDA buy 1
# or symlink into your $PATH:
ln -s /Users/pson/Desktop/IntelligenceOS/tradingview/tv ~/bin/tv
tv chart metadata
```

**Direct `python -m`** (must run from the tradingview/ directory):
```bash
cd tradingview
.venv/bin/python -m tv_automation.chart metadata
```

## CLI surface (Tier 1 — built)

All commands print JSON on stdout and use typed exit codes on failure.
Every invocation mints a 8-char `request_id` printed in the result and
logged on every audit event from that call — use it to correlate
`.start` / `.complete` / `.failed` entries in the audit log.

### chart

```bash
python -m tv_automation.chart metadata
python -m tv_automation.chart set-symbol NVDA --tf 60
python -m tv_automation.chart screenshot AAPL 1D -o /tmp/aapl.png
```

### trading (paper-only, safety-gated, order-verified)

```bash
tv trading positions
tv trading place-order AAPL buy 1 --dry-run       # commit qty, skip click
tv trading place-order AAPL buy 1                 # place + verify via delta
tv trading close-position AAPL --dry-run          # plan only
tv trading close-position AAPL                    # actually close
```

`place-order` reads the positions table before the click, fires, then
polls for up to 6s waiting for the qty delta to match expectations.
Returns `verified: true` on match, or `verified: false` with a warning
if the delta didn't materialize — **do NOT retry blindly on
`verified: false`**; check the Orders tab manually first.

### orders (limit / stop / bracket + cancel)

Pending-order lifecycle via TradingView's persistent right-side "order
panel" (`[data-name="order-panel"]`). Same safety stack as `trading`.

```bash
tv orders list                                         # pending orders (Working)
tv orders place-limit AAPL buy 1 170.50 --dry-run      # configure form, verify preview, skip submit
tv orders place-limit AAPL buy 1 170.50                 # place + poll orders table
tv orders place-stop NVDA sell 1 165.00
tv orders place-bracket QQQ buy 1 --entry 400.00 \
    --take-profit 450.00 --stop-loss 395.00             # single entry + child TP/SL
tv orders cancel <order_id>                             # find row, click cancel
tv orders cancel-all
```

`place-limit` / `place-stop` / `place-bracket` all:
1. Navigate to the symbol, auto-open the order panel if collapsed.
2. Click the correct type tab (Market/Limit/Stop) and side (Buy/Sell).
3. Fill qty + price inputs; toggle and fill TP/SL when supplied.
4. Read the submit button's **self-computed preview text** (e.g.
   `"Buy 1 AAPL @ 170.50 LIMIT"`) and verify it matches intent
   BEFORE clicking. Any mismatch raises `VerificationFailedError`.
5. Click submit; poll Orders → Working sub-tab up to 16s for the new
   order_id. `verified: true` means row confirmed; `verified: false`
   means the click fired but no row appeared in time — **do NOT retry
   blindly**, run `tv orders list` first.

`place-bracket` submits as one atomic action but creates **3 rows** in
the orders table: the parent entry + one TP exit + one SL exit. Each
has its own order_id. `cancel <parent_id>` does NOT cascade to children
— use `cancel-all` or cancel each child explicitly.

Sub-tab quirk: TV's Orders view added sub-filters (All / Working /
Inactive / Filled / Cancelled / Rejected) in a recent build. "Working"
is the only reliable view for pending orders; clicking it alone
doesn't always refresh stale DOM, so `_ensure_orders_tab_active` does
All → Working as a double-click workaround.

### alerts (price alerts + webhooks, Pro+)

Create, list, pause, resume, and delete TradingView alerts via the
right-sidebar panel. Closes the autonomous Pine→webhook→bridge loop
that `tv-worker/` + `bridge.py` already scaffold.

```bash
tv alerts list
tv alerts create-price MNQ1! crossing 27000 --dry-run
tv alerts create-price MNQ1! crossing-up 27000
tv alerts delete "MNQ1! Crossing 27"      # substring of description
tv alerts pause  "MNQ1! Crossing 27"
tv alerts resume "MNQ1! Crossing 27"
```

**Scope (Tier 2a MVP):**
- Price-crossing alerts with operator `crossing` / `crossing-up` /
  `crossing-down` (TV's Price condition exposes only these three).
- Trigger frequency `once-only` (default) or `every-time`.
- Alerts inherit TV's default notification settings — webhook URL,
  email, app push are NOT configured programmatically in the MVP
  (requires driving the Edit Notifications sub-modal; see deferred
  note below).

**Row-action quirk** (resolved): per-row hover buttons are exposed as
`[data-name="alert-stop-button"]` on Active alerts and
`[data-name="alert-restart-button"]` on Paused ones (TV renames by
state). `_click_row_action` accepts a list of data-names and clicks
the first present.

**Delete confirmation**: TV shows a `popupDialog-B02UUUN3` confirm
with a `Delete` / `No` pair. `_confirm_destructive` polls up to 3s
for the dialog and clicks the positive button via JS exact-text
match (`has-text` is substring and would catch "Delete All Inactive").

**Name / message / webhook URL customization — BUILT 2026-04-17** ✓
```bash
tv alerts create-price MNQ1! crossing 27000 \
    --name "MNQ breakout" \
    --message '{"action":"buy","symbol":"{{ticker}}","price":"{{close}}"}' \
    --webhook "https://your-worker.example.com/hook"
```
Drives two sub-modals: **Edit Message** (fills `input#alert-name` +
`textarea#alert-message`, both with stable ids) and **Edit
Notifications** (toggles checkboxes by label text, fills
`input#webhook-url`). `{{ticker}}`, `{{close}}`, `{{strategy.order.action}}`
etc. are Pine template placeholders — TV substitutes them at alert
fire time in the outgoing webhook payload.

**Deferred**:
- Indicator-based alerts (condition type "Indicator") — separate
  condition-builder surface.
- `resume` has a status-refresh lag: the click succeeds but reading
  the row's status column immediately after can still show
  "Stopped manually" for a second or two. The state DOES flip — a
  follow-up list call shows Active. Post-click poll needed.

### layouts (save/load/rename chart layouts)

Manage named chart layouts — each is a saved state of symbol,
interval, indicators, drawings, order-panel visibility, etc. The
chart URL `/chart/<layout_id>/` references the layout.

```bash
tv layouts list                       # all saved layouts (virtualized picker)
tv layouts current                    # active layout name + id
tv layouts load "Money Print"         # switch to a saved layout
tv layouts rename "New Name"          # rename the active layout
tv layouts save                       # save dirty changes to current
```

**What works live-verified**:
- `list` — reads `<a data-name="load-chart-dialog-item">` anchors
  from the Open Layout… picker dialog
- `current` — finds the layout name by position (header row, left
  of the `save-load-menu` gear)
- `load` — **navigates via the row anchor's `href`** rather than
  clicking. TV's SPA sometimes swallows programmatic clicks on
  `<a>` tags, but `page.goto(href)` is semantically identical to a
  user click and always works.
- `rename` — drives TV's Rename… dialog (with Unicode U+2026
  ellipsis in the menu label — `"Rename\u2026"`, not three dots)

**Picker virtualization**: the Open Layout… dialog renders only
~10 rows at a time (scrollHeight can be 4000+px). To find a layout
further down the list, we fill the search input (placeholder
"Search") — the list re-virtualizes to show matches.

**Row-name parse gotcha**: some rows include a leading empty line
from a status-dot emoji. `.split('\n')[0]` alone returns empty
whitespace for those rows — must `.filter(l => l)` first then take
`lines[0]`.

**Deferred**:
- `save-as` / `copy` — implementations exist but finicky. "Create
  new layout…" doesn't reliably switch the URL before subsequent
  rename, so the rename can mis-target the original layout. Avoid
  in automation until re-probed.
- `delete` — TV's dropdown menu has NO "Delete layout" command
  (confirmed via full-menu dump), and picker rows expose no
  hover-reveal delete button. Delete likely requires TV.com's
  chart-management page, which is a separate surface.
- Multi-chart grids (1×2, 2×2) — ROADMAP stretch item.

### indicators (add/remove/configure chart indicators)

Programmatically manage the chart's indicator stack — built-ins like
RSI / MACD / VWAP / EMA, community scripts, and Pine strategies.
Useful pre-setup for a Pine strategy that references `ta.rsi()` or
similar — run `add "RSI"` before applying the strategy file.

```bash
tv indicators list
tv indicators add "RSI"                         # add by fuzzy search
tv indicators add "Relative Strength Index"     # or exact name
tv indicators remove "RSI"
tv indicators configure "RSI" '{"Length": 21}'  # fill settings modal by label
```

**Entry path**: the `/` keyboard shortcut is the only reliable way to
open the Indicators picker. `[data-name="open-indicators-dialog"]`
exists but is responsive-collapsed on many toolbar widths and
frequently fails Playwright's visibility check. `indicators.py`
clicks the chart canvas first (to grab keyboard focus), then
presses `/`.

**Three major UI gotchas**:

1. **Legend drawer is `display: none` by default.** The chart's
   top-left indicator legend appears visible but individual
   `legend-source-item` elements are nested inside a `display: none`
   container when the drawer is collapsed. Clicks fire but no-op.
   `_ensure_legend_expanded` detects the `closed-` class on
   `legend-sources-wrapper` and clicks `legend-toggler` to open.

2. **Canvas intercepts pointer events.** The chart's
   `pane-top-canvas` is stacked above the legend — real mouse clicks
   at legend-button coordinates hit the canvas, not the button.
   Force-click bypasses hit-test but the click still doesn't trigger
   TV's React handler.

3. **React needs the full event cycle.** TV's legend buttons wire
   `pointerdown → mousedown → pointerup → mouseup → click`. A lone
   `element.click()` dispatches but no handler fires. `_fire_click_events`
   dispatches the full synthetic sequence via JS on a marked element,
   which satisfies React without needing pixel-correct hit tests.

**Name parse**: the `legend-source-item` `innerText` concatenates the
indicator name with its live values (e.g. `"RSI49.53∅44.92∅∅"`). We
split on the first digit or `∅` (TV's "no value" character) to
isolate the display name. Works for all built-ins + most Pine scripts
with alphanumeric names.

**Configure**: `lib/modal.fill_by_label()` handles label→input matching
for indicator settings modals. Pass input values as a JSON dict keyed
by visible label text (case-sensitive). Modals vary per indicator;
labels you can expect on RSI: `"Length"`, `"Source"`, `"Upper Band"`,
`"Lower Band"`.

### pine_editor

```bash
tv pine_editor apply pine/generated/my_ind.pine
tv pine_editor apply --name "My RSI" path.pine
tv pine_editor apply --dry-run path.pine          # validate locally, no browser
tv pine_editor errors                             # current compile errors
tv pine_editor errors --include-warnings
```

`apply` snapshots the Pine console's error rows before the paste and
diffs after, so `errors` in the returned JSON only contains errors
**introduced by THIS apply** — stale rows from earlier broken scripts
show up in `historical_errors` instead.

### strategy_tester

```bash
tv strategy_tester open          # open the Strategy Report overlay
tv strategy_tester metrics       # read Performance Summary → JSON
tv strategy_tester trades        # scrape List of trades
tv strategy_tester close         # dismiss the overlay
```

### status (aggregate read-only snapshot)

Single CLI that holds ONE browser context and reads chart, broker,
positions, Pine editor, and (optionally) Strategy Report in one pass.
Amortizes the ~2s CDP attach cost across all reads.

```bash
tv status                        # chart + broker + positions + pine
tv status --no-pine              # skip Pine editor read
tv status --strategy-report      # also open Strategy Report + scrape metrics
tv status --warnings             # include Pine warnings in addition to errors
```

Per-pane failure isolation: a broken surface (e.g. Pine Editor
unopenable) produces `{"error": "..."}` for that field while the rest
still populate.

### probes (refresh selectors when TV ships UI changes)

```bash
python -m tv_automation.probes.probe_positions
python -m tv_automation.probes.probe_strategy_tester
```

## Safety model

Every mutating trade action runs through these checks, in order, before any
click:

1. **`config.check_symbol()`** — refuses anything not in `limits.yaml`
   allowlist. LLM hallucinations die here.
2. **`config.check_qty()`** — refuses qty > `max_qty`. Same.
3. **`assert_logged_in()`** — confirms `sessionid` cookie present.
4. **`assert_paper_trading()`** — refuses if broker picker is up (no broker
   connected) OR if the broker chip label isn't in
   `limits.required_broker_contains`. If you ever connect a real broker
   to this profile, this guard will abort every trade.
5. **`with_lock("tv_browser")`** — flock on `/tmp/tv-automation/tv_browser.lock`.
   ANY two browser-mutating CLIs (trade, pine edit, indicator toggle,
   navigation) queue instead of racing on the shared UI. One lock name
   across all surfaces — splitting names would let unrelated ops
   interleave keystrokes in the same tab.
6. **Velocity throttle** — `config.check_velocity("order")` enforces
   `limits.yaml → min_seconds_between_orders`. Prevents runaway LLM
   retry loops from hammering TradingView. Stamp file written AFTER
   verified trades; dry-runs bypass.
7. **Order verification via positions + orders delta** — `place_order`
   polls BOTH the positions table (for fills) and the orders table (for
   pending-fill after-hours orders). Returns one of:
   * `final_status: "filled"` — position delta matched
   * `final_status: "pending_fill"` — new pending order in Orders table
   * `final_status: "unknown"` — neither appeared; DO NOT retry blindly

Every action is appended to `tradingview/audit/YYYY-MM-DD.jsonl` with
timestamp, pid, `request_id`, event name, and result fields. Actions
wrapped in `audit.timed()` also log `duration_ms`. That's the single
source of truth for "what did Claude do?"

### Retry on transient errors

Every CLI invocation retries up to 3 times on connection-level
Playwright errors (ECONNRESET, "target closed", "websocket error",
etc.) with exponential backoff (0.5s → 1s → 2s). Typed
`TVAutomationError` exceptions — `NotPaperTradingError`,
`LimitViolationError`, etc. — never retry; they surface immediately.
See [lib/retry.py](lib/retry.py).

## Exit codes

| Code | Error |
|------|-------|
| 0    | Success |
| 1    | Unexpected generic error |
| 2    | `NotLoggedInError` — cookie missing/expired |
| 3    | `NotPaperTradingError` — broker isn't Paper Trading |
| 4    | `SelectorDriftError` — a DOM selector didn't resolve (re-run probe) |
| 5    | `ModalError` — expected modal didn't appear |
| 6    | `VerificationFailedError` — action seemed to succeed but post-check failed |
| 7    | `LimitViolationError` — config limits rejected the request |
| 8    | `ChartNotReadyError` — chart didn't reach usable state |

## Package layout

```
tv_automation/
  __init__.py
  selectors.yaml        # single source of truth for DOM selectors
  limits.yaml           # safety limits (allowlist, max qty)
  config.py             # loads limits.yaml
  chart.py              # Tier 1 — symbol, timeframe, screenshot
  trading.py            # Tier 1 — market orders, positions, close
  orders.py             # Tier 2 — limit/stop/bracket, list, cancel
  alerts.py             # Tier 2 — price alerts, list/pause/resume/delete
  layouts.py            # Tier 2 — list/current/load/rename layouts
  indicators.py         # Tier 2 — add/remove/configure chart indicators
  pine_editor.py        # Tier 1 — apply Pine, read compile errors
  strategy_tester.py    # Tier 1 — run backtest, read performance
  lib/
    errors.py           # typed TVAutomationError taxonomy
    audit.py            # JSONL audit log
    guards.py           # assert_logged_in / _paper_trading / with_lock
    selectors.py        # load selectors.yaml, first_visible()
    modal.py            # generic modal open/fill/confirm
    table.py            # plain + virtualized table scrapers
    keyboard.py         # named TradingView keyboard shortcuts
    cli.py              # CLI runner — maps errors to exit codes
  probes/
    probe_positions.py
    probe_strategy_tester.py
    probe_orders.py
    probe_alerts.py
    probe_layouts.py
    probe_indicators.py
    snapshots/          # JSON dumps from probe runs
```

Each surface module is a thin orchestration layer over `lib/`. No raw
CSS selectors in code — everything goes through `selectors.yaml`.

## Adding a new capability (Tier 2 template)

1. Pick a surface (e.g. `indicators`, `alerts`, `watchlist`).
2. Write `tv_automation/probes/probe_<surface>.py` — navigate to the
   relevant UI state, dump every `[data-name]` / `[aria-label]` /
   `[role]` to JSON.
3. Run the probe, look at the snapshot, add selectors to
   `selectors.yaml` under a new surface key.
4. Write `tv_automation/<surface>.py` with the public async functions,
   using `lib/selectors.first_visible()` instead of raw CSS.
5. Add a CLI `_main()` at the bottom following the pattern in
   `chart.py` / `trading.py`.
6. Smoke-test from Bash. Update this README.

## Tier 2 roadmap (not yet built)

| Surface | Why it matters |
|---|---|
| `watchlist.py` | CRUD watchlist entries; link to layouts |
| `screener.py` | Filter + scrape the Stock/Crypto/Forex screener |
| `drawings.py` | Trend lines / Fib / rectangles via Pine `line.new()` |

### Known unresolved probes

- **Stop-limit orders** — the order panel's tabs are Market / Limit /
  Stop only; there's no obvious Stop-Limit tab. TV may expose this
  through a combo inside the Stop tab (e.g. a "Limit price" subfield)
  or a keyboard shortcut. Probe the Stop tab's secondary controls
  when needed.
- **Order modification** — `orders.py` doesn't support editing a
  pending order's qty / price yet. TV exposes this via the pencil /
  "Protect Position..." button (`[data-name="edit-settings-cell-button"]`)
  in the orders table's settings-column. Wiring it needs a probe of the
  edit modal that opens on click.

Resolved in 2026-04-17 `orders.py` work:
- **Order-table cancel button** — `[data-name="close-settings-cell-button"]`
  with `aria-label="Cancel"` (vs `"Close"` in positions-table). Always
  present in DOM when rows exist; no hover/reveal required. Earlier
  ROADMAP note that it was "empty in static DOM" was against an empty
  table.
- **Close-position button** — same data-name, `aria-label="Close"`,
  in the positions-table. Same fix applies to `trading.close_position`.

## Known limitations

- **List of Trades scraping** — `strategy_tester.trades()` relies on a
  best-guess virtualized-container selector. First real use against a
  strategy with a long trade history will likely need a probe refresh.
- **Close-position button** — best-effort search for the close button
  inside the last-column cell. Once a position is open, run
  `probe_positions` again to catalog the exact selector and tighten
  `selectors.yaml`.
- **Localization** — tab names are matched by English text
  ("Positions", "Orders"). Switch TV to another language and these
  break. Fix: match by position/index instead.

## Migration from legacy scripts

The top-level scripts (`screenshot.py`, `apply_pine.py`,
`analyze_and_apply.py`, `bridge.py`, `capture_chart.py`, etc.) still
work unchanged — they import `session.py` and `preflight.py` which are
the same ones `tv_automation/` uses. Move over as you need; no rush.

The Cloudflare Worker path (`tv-worker/`) and the FastAPI bridge
(`bridge.py`) are unused in the CLI-driven model. Leave dormant for
webhook-style autonomy, or delete when you're ready.
