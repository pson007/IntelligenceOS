# tv_automation — roadmap & handoff

Last updated 2026-04-17. This doc captures everything a future session (you
or Claude) needs to resume. [README.md](README.md) covers what exists; this
focuses on **what's next** and **why the decisions that got us here were made**.

---

## 1. Current state — the one-paragraph summary

Tier 1 is complete and live-tested: `chart`, `trading`, `pine_editor`,
`strategy_tester`, `status`. Tier 2 landed 2026-04-17: `orders.py`
(limit/stop/bracket/market with offset TP/SL), `alerts.py` (price
alerts with create/list/pause/delete + webhook/message/name
customization), `layouts.py` (list/current/load/rename),
`indicators.py` (add/remove/configure chart indicators),
`watchlist.py` (current/contents/add/clear/create/rename/load/copy),
`drawings.py` (Pine-emitter for horizontal/trend_line/box/label/
vertical via JSON sketch spec), and `screener.py` (open/current/
filters/column-tabs/results against the modern unified stock
screener). Twelve CLIs work against a logged-in Chromium-Automation
profile on CDP port 9222. Foundation (guards, typed errors, audit log with
`request_id` + `duration_ms`, retry on transient Playwright errors,
flock serialization, safety limits with velocity throttle,
tick-alignment validation, layout-preserving URL navigation,
toast-overlay dismissal) is in place. The autonomous
Pine→webhook→bridge loop is now unblocked — `tv alerts create-price`
+ `tv-worker/` + `bridge.py` + `tv orders place-market` form a
complete closed loop (webhook customization is the final deferred
piece).

---

## 2. Immediate cleanup — check before resuming

The two overnight-pending paper orders from 2026-04-16 (AAPL 2981518606,
NVDA 2981553434) are no longer visible — either filled + already
flattened, or cancelled during the 2026-04-17 orders.py smoke test.
`./tv orders list` + `./tv trading positions` show a clean account.

If you need to flatten any leftover state: `./tv orders cancel-all`
and `./tv trading close-position <SYMBOL>` now both work end-to-end.

The compile-error history in the Pine Editor console retains a stale error
from `pine/broken_test.pine` (the deliberately-broken test file). Harmless —
`pine_editor apply`'s error-diff logic already handles this.

---

## 3. Resume checklist

```bash
cd /Users/pson/Desktop/IntelligenceOS/tradingview

# 1. Is the automation Chromium up and signed in?
./tv status                         # one-shot aggregate

# If CDP not reachable:
./start_chrome_cdp.sh
# Sign in to tradingview.com in the launched window if the sessionid
# cookie is gone. That's the only manual step.

# 2. Verify Tier 1 still works end-to-end:
./tv chart metadata                                 # should show saved layout ID preserved
./tv trading positions                              # should return {empty: true, positions: []}
./tv pine_editor apply pine/webhook_alert.pine      # ok: true, errors: []
./tv strategy_tester metrics                        # opens report, returns backtest numbers
./tv strategy_tester close                          # cleanup

# 3. Check nothing drifted:
tail -10 audit/$(date +%Y-%m-%d).jsonl              # recent actions
```

If any of the above fails, run the relevant probe first:

```bash
./tv probes probe_positions        # positions-table surface
./tv probes probe_strategy_tester  # strategy-report surface
```

Then diff the snapshot JSON in `tv_automation/probes/snapshots/` against a
prior run to see what moved.

---

## 4. Tier 2 roadmap — ranked by value

Estimates assume the Tier 1 infrastructure (selectors.yaml, guards, audit,
retry, cli.run) is reused — no bespoke foundation per module.

### 4a. orders.py — **BUILT 2026-04-17** ✓

Shipped: `list`, `place-limit`, `place-stop`, `place-bracket`, `cancel`,
`cancel-all`, each with `--dry-run`. Driven through the persistent
right-side `[data-name="order-panel"]` (not a modal — a stateful form).
Submit button's self-computed preview text is read and verified against
caller intent before clicking.

Not shipped (deferred):
- `place-stop-limit` — order panel shows Market/Limit/Stop tabs only; no
  obvious stop-limit path. Probe when needed.
- `modify-order` — requires probing the "Protect Position…" / pencil
  edit modal (`[data-name="edit-settings-cell-button"]`).

See [orders.py](orders.py) for implementation and the 2026-04-17 entry
in [probes/snapshots/](probes/snapshots/) for the captured DOM.

### 4b. indicators.py — **BUILT 2026-04-17** ✓

Shipped: `list`, `add`, `remove`, `configure`. Live-verified on MNQ1!
with RSI (add → configure Length=21 → remove, all verified).

Three critical discoveries this probe cycle:
- **Legend drawer is collapsed by default** (`closed-l31H9iuA` class);
  source items sit inside a `display: none` parent. Click
  `[data-qa-id="legend-toggler"]` to open before any per-row action.
- **`pane-top-canvas` intercepts pointer events** at legend
  coordinates. Real mouse clicks and Playwright hover fail.
- **React handlers need the full pointer/mouse event cycle**
  (`pointerdown→mousedown→pointerup→mouseup→click`). Lone
  `element.click()` dispatches but no handler fires. `_fire_click_events`
  dispatches the full synthetic sequence via JS on a marked element
  — bypasses hit-test AND satisfies React.

The `/` keyboard shortcut is the only reliable way to open the
Indicators picker; `[data-name="open-indicators-dialog"]` is
responsive-collapsed at narrow toolbar widths. TV's Indicator search
is fuzzy ("RSI" matches "Relative Strength Index" as top built-in).

**Deferred**:
- `favorite <name>` — toggle favorites. Not implemented.
- Custom Pine script paths (the "My scripts" tab of the dialog) —
  works via `add "<script name>"` since search covers it, but
  filtering behavior when multiple scripts share a name prefix
  hasn't been tested.

### 4c. alerts.py — **BUILT 2026-04-17** ✓

Shipped: `list`, `create-price` (with operator crossing / crossing-up /
crossing-down and trigger once-only / every-time), `delete` (with
confirmation-dialog handling), `pause`, `resume`. Driven through the
right-sidebar alerts panel + the hash-classed Create Alert popup.

Entry path (discovered): Alt+A is intercepted on current builds; the
reliable path is right-sidebar `[data-name="alerts"]` → panel's
`[data-name="set-alert-button"]` ("+" icon). Per-row actions live
behind hover-reveal (`alert-stop-button` on Active,
`alert-restart-button` on Paused, `alert-delete-button`, `alert-edit-button`).

**Name / message / webhook / notifications — BUILT 2026-04-17** ✓
Re-probe found stable ids (`input#alert-name`, `textarea#alert-message`,
`input#webhook-url`) that weren't visible in the first probe pass.
Sub-modal clicks use direct JS dispatch (same pattern as
`indicators._fire_click_events`) because Playwright's element-click
races with React's handler wiring in stacked-modal contexts.

The autonomous Pine→webhook→bridge→orders loop is now end-to-end
automatable: `tv alerts create-price <sym> <op> <value> --webhook ...`
→ Pine condition fires → `tv-worker/` Cloudflare Worker relays →
`bridge.py` FastAPI → `tv orders place-market --tp-offset X --sl-offset Y`.

**Deferred**:
- Indicator-based alerts (condition type "Indicator") — separate
  condition-builder surface.
- `resume` has a status-refresh lag that can mislead the immediate
  post-click read. Easy fix: poll for `alert-item-status` to flip.

### 4d. watchlist.py — **BUILT 2026-04-17** ✓

Shipped: `current`, `contents`, `list`, `add`, `clear` (with dry-run),
`create`, `rename`, `load`, `copy`. Driven through the right-sidebar
Watchlist widget + the `[data-name="watchlists-button"]` operations
menu + the `data-dialog-name="Watchlists"` Open list… picker.

Symbol rows are unusually well-attributed for TV: each row carries
`data-symbol-short`, `data-symbol-full`, `data-active`, and
`data-status` — the cleanest scraping surface in this codebase.
`contents` returns all four per row.

**Critical insight — virtualization**: the sidebar list is the third
TV surface (after Strategy Tester trades and Layouts picker) that only
renders ~10-15 rows in DOM at a time. A single static read produces
inconsistent results — different symbols depending on scroll position.
`_scroll_and_collect` scrolls `[data-name="symbol-list-wrap"]` and
dedups by `data-symbol-short`. Termination anchors on `scrollTop +
clientHeight >= scrollHeight` rather than the conventional
"two-stagnant-rounds" stop — React's row virtualizer can falsely look
stagnant for one or two iterations after a scroll while it mounts the
new range.

**Deferred**:
- `remove <symbol>` — per-row delete X is hover-reveal-only and TV's
  React handlers don't fire on JS-dispatched mouseenter/mouseover
  (same pattern from §7c on the indicators legend; would need real
  pointer-event coordinates). Workaround: `clear` + `add` the
  symbols you want to keep.
- `delete <list>` — no Delete in the operations menu; likely needs
  hover-reveal trash in the Open list… picker (same as
  `layouts.delete`). Workaround: rename and reuse.
- `reorder` — drag-and-drop on canvas-coordinates; complex.

### 4e. layouts.py — **BUILT 2026-04-17** ✓ (partial)

Shipped: `list`, `current`, `load`, `rename`, `save`. Driven through
the top-header `save-load-menu` dropdown + the Open Layout… picker
dialog.

Key discoveries this probe cycle:
- Row anchors are `<a data-name="load-chart-dialog-item">` with
  stable `href="/chart/<layout_id>/"`. Load by navigating the href
  rather than JS-clicking (SPA sometimes swallows programmatic
  clicks).
- Picker is virtualized (~10 rows in DOM, ~4000px scrollHeight);
  always filter via the Search input before row lookup.
- Leading-empty-line trap: some rows have a status-dot emoji that
  renders as an empty text node. `.split('\n')[0]` misses the real
  name unless you filter empty lines first.

**Deferred**:
- `save-as` / `copy` — "Create new layout…" URL transition is
  finicky; rename can mis-target. Avoid in automation.
- `delete` — no UI path found (dropdown has no Delete command;
  picker rows have no hover-reveal trash button). TV.com's
  chart-management page is likely the true surface.
- Multi-chart grid creation — stretch item (§9).

### 4f. screener.py — **BUILT 2026-04-17** ✓ (read paths)

Shipped: `open`, `current`, `filters`, `column-tabs`, `results` (with
`--columns` to switch column groups and `--max-rows` to cap the
scroll-collect). Scrape verified: 500 unique symbols captured in one
call against the modern unified screener at `/screener/`, sorted by
market cap descending (NVDA → FLUT).

Three discoveries this probe cycle:
- The screener pre-loads ~100 rows in DOM (more generous than the
  watchlist's ~10) but still virtualizes beyond that — same
  scrollTop+clientHeight termination pattern as watchlist/trades.
- TV uses **`translateX(-999999px)`** as a tab-strip overflow
  technique. Tabs that don't fit in the visible width sit at x=-999877
  in DOM but aren't clickable until exposed via a "More" chevron
  (currently unhandled; column_tabs splits the result into `visible`
  and `hidden` arrays so callers can see what's reachable).
- Tab `textContent` is **doubled** — TV renders each label twice
  internally (e.g. "OverviewOverview"). Playwright's `:text-is()`
  matches innerText (single-rendered), but `filter(has_text=)` is
  substring-matched and may need fallback for some tabs.

**Scope today**: stocks only. TV's crypto/forex/futures screeners
live at separate URLs (`/crypto-screener/`, `/forex-screener/`,
`/markets/futures/...`) and serve a legacy `tv-screener` DOM rather
than the modern `screenerContainer-` React wrapper this module
targets. Different surface entirely.

**Deferred**:
- crypto/forex/futures screener variants — different DOM shape.
- `filter <pill> <value>` — programmatic filter setting. Each pill
  is a different UI control; each needs its own setter. Workaround
  today: configure filters once in the UI manually, save as a named
  screen, then call `results` programmatically.
- `preset save / preset load` — would need probing the topbar
  screen-picker dropdown (the `screener-topbar-screen-title` element).
- Hidden-tab access via "More" overflow chevron — possible but
  needs probing the chevron's selector.

### 4g. drawings.py — **BUILT 2026-04-17** ✓ (Pine emitter path)

Shipped: a JSON sketch spec → Pine v5 indicator composer
(`tv_automation/drawings.py`) plus the `tv drawings sketch` CLI.
Five drawing primitives: `horizontal`, `trend_line`, `box`, `label`,
`vertical`. Times accept ISO 8601 strings or Unix epoch seconds;
colors accept named (red/blue/green/etc.) or hex (`#rrggbb`); line
styles accept solid/dashed/dotted/arrows; line endpoints accept
extend modes (none/left/right/both).

The composer wraps drawings in `if barstate.islast and not _drawn`
with a one-shot guard, so drawings render once when the chart loads
rather than on every realtime tick. Each sketch becomes an indicator;
re-applying a sketch with the same name overwrites it cleanly. `tv
drawings clear --name <X>` removes a named drawings indicator via
`indicators.remove_indicator`.

Smoke-tested 2026-04-17: full example sketch (5 drawings) rendered
successfully (`compile_boundary` detected, no errors), individual
saved sketch (S/R Levels, 4 horizontals) applied + cleared cleanly.

**Why Pine, not canvas-coordinate clicks**: TV's chart canvas needs
(price, time) → (pixel x, y) projection logic that lives inside React
state (§7 insights). Pine drawings render natively via `xloc.bar_time`
— timestamps drive positioning directly, no projection math. Trade-off:
drawings are NOT user-draggable post-creation. For LLM-driven
annotation that's the right trade.

**Deferred**:
- Polylines / linefills / fib retracement primitives — Pine supports
  them (`polyline.new`, `linefill.new`, plus Pine snippets you can
  emit yourself); not in the JSON spec yet, easy to add when needed.
- Native draggable drawings (canvas-coord toolbar approach) —
  possible-but-hard, see ROADMAP §7 for the projection-state hazards.

### 4h. Lower-priority surfaces

| Surface | Notes |
|---|---|
| News / economic calendar | Read-only, simple scrape, ~1hr each |
| Symbol fundamentals | Right-sidebar financials panel, ~1hr |
| Heatmaps | Navigation + scrape; specific pages on tradingview.com |
| Community ideas feed | Probably skip — social consumption, not automation |
| Account settings | Risk of breaking user's setup; don't automate |

---

## 5. Known unresolved probes

These block specific Tier 2 features. Each has findings so far.

### 5a. Cancel-order / close-position button — **RESOLVED 2026-04-17** ✓

The button is `[data-name="close-settings-cell-button"]`, always
present in DOM when a row exists — no hover/reveal mechanism needed.
Earlier note "empty in static DOM" was captured against an empty
table (emptyStateRow doesn't have per-row buttons).

The `aria-label` differs by context:
- Orders table: `aria-label="Cancel"`
- Positions table: `aria-label="Close"`

Both wired in [orders.py](orders.py) `cancel_order` and
[selectors.yaml](selectors.yaml) `order_panel.row_cancel_button`.
`trading.close_position` already used a fuzzy match that happens to
hit the same button; tighten its selector when convenient.

### 5a'. Orders sub-tab cache bug (new, 2026-04-17)

TV's Orders view gained sub-filters (All / Working / Inactive / Filled
/ Cancelled / Rejected) in a recent build. If "Working" is already
selected and you click it again, the table keeps its stale (often
empty) content even when the count badge shows orders exist. Clicking
All → Working forces a re-render. `orders._ensure_orders_tab_active`
does this double-click on every activation. If TV fixes the bug,
remove the All-click for a small speedup.

### 5a''. Order-placement async latency (new, 2026-04-17)

The round-trip from submit click to orders-table row can exceed 10s
for paper trading. Observed: MSFT sell-limit placed correctly, but
poll at 6s timeout returned `verified: false` even though the order
was live. `orders.py` now polls for 16s and `cancel` for 12s —
adequate headroom without being painfully slow.

### 5b. TradingView localization

**Finding**: tabs (Positions, Orders, Strategy Report, Metrics, List of
trades) have `role="tab"` but no `data-name` / `aria-label`. We match
by English visible text. Switching TV to a non-English language breaks
all tab-based navigation.

**Not urgent** unless you use non-English TV. Fix when needed: switch
to positional selectors (`[role="tab"]:nth-of-type(1)`) with a
startup calibration that maps positions → roles once per session.

### 5c. Strategy Tester "List of trades" virtualization — **RESOLVED 2026-04-17** ✓

`strategy_tester.trades` now scroll-collects against the
`ka-table-wrapper` ancestor and dedups by first-cell text
(`"<trade_num><side>"`, e.g. `"1Short"`). Smoke-tested against the
currently-applied Structure & Flow strategy: 313 unique trades captured
(continuous Trade #1 → #313), stable across re-runs. Termination uses
`scrollTop + clientHeight >= scrollHeight` rather than the conventional
"two-stagnant-rounds" stop, for the same React-virtualizer-mount race
documented under watchlist (§4d).

### 5d. Pine compile console robustness — **RESOLVED 2026-04-17** ✓

`pine_editor.apply` now anchors the apply window on a strictly-new
"Compiling..." console row. Pre-apply snapshots EVERY console row text
(timestamps included — each row is keyed by full visible text), then
after pasting/saving, polls up to 6s for the boundary row to appear
via `_wait_for_new_compiling_row`. Error attribution switches from
`new = all[len(before):]` (assumed append-order) to `new = [e for e in
all if e not in baseline]` (set membership) — robust to console
clears, row reorders, and de-duplication of repeated identical errors.

The result dict now also includes `compile_boundary` (the matched
"Compiling..." row, or null if not detected within timeout) — useful
for diagnosing apply failures.

Smoke-tested against `pine/broken_test.pine`: boundary detected at
`"8:54:26 PMCompiling..."`, 2 new errors at 8:54:27/8:54:28 attributed
to this apply, 2 prior 9:07/9:26 entries correctly classified as
historical, no overwrite of the loaded Structure & Flow strategy.

---

## 6. Pattern for adding a new surface

This is the template every Tier 2 surface should follow. Each step has
been executed successfully for trading, pine_editor, strategy_tester —
no new invention required.

### Step 1: probe

Create `tv_automation/probes/probe_<surface>.py`. Copy
[probe_strategy_tester.py](probes/probe_strategy_tester.py) as a
template. Navigate to the UI state, dump every `[data-name]`,
`aria-label`, button, tab, and role-bearing element. Save JSON to
`probes/snapshots/`.

Run it with the relevant UI open in the automation Chromium:
```bash
./tv probes probe_<surface>
```

### Step 2: catalog selectors

Open the JSON snapshot. Pick the stable selectors (prefer `[data-name]`,
then `[aria-label]`, then `[role]` with text; avoid class names
unless they have a stable prefix like `error-` or `emptyStateRow-`).
Add them to `tv_automation/selectors.yaml` under a new surface key.
**Always prefer broker-prefixed data-names (`Paper.X`) when available**
— they act as a safety guard against wrong-broker interaction.

### Step 3: write the module

Create `tv_automation/<surface>.py`. Template to follow — see
[trading.py](trading.py) for a mutating example or
[strategy_tester.py](strategy_tester.py) for a read-heavy example.

Every module should:

- Import from `lib.context` for `chart_session()`
- Use `lib.selectors.first_visible()` — never raw CSS in the module
- Wrap mutations in `lib.guards.with_lock("tv_browser")`
- Wrap mutations in `audit.timed("<surface>.<action>")`
- For trading-adjacent: call `config.check_velocity("order")` and
  `config.record_action("order")`
- Return typed dicts with `ok`, and where applicable `verified`,
  `dry_run`, `final_status`
- Have a `_main()` at the bottom using argparse + `lib.cli.run(lambda: ...)`

### Step 4: wire the CLI shim

Nothing to do — `./tv <surface> <cmd>` works automatically via the
existing shim at [tradingview/tv](../tv).

### Step 5: smoke-test end-to-end

Run a read command first, then a dry-run of a mutating command, then
the real mutation. If anything fails with `SelectorDriftError`, re-run
the probe.

### Step 6: document

Add the CLI examples to [README.md](README.md)'s CLI surface section.
Add the new module to this ROADMAP.md's "built" status.

---

## 7. Insights worth preserving

Context that took real work to discover; losing it means re-discovering.

### 7a. TradingView naming drift

| What the UI calls it | What the DOM / URL / docs call it |
|---|---|
| "Strategy Report" (current) | used to be "Strategy Tester" (pre-2025) |
| "Paper Trading" (visible) | `Paper.` prefix in data-name, e.g. `Paper.positions-table` |
| "Open Account Manager" (aria-label) | bottom-panel toggle (the broker chip lives here) |
| "Webhook Alert Template" | title in `strategy("...")` call |
| "Metrics" tab | the Performance Summary |

### 7b. Selector stability hierarchy

In descending order of stability:

1. **Broker-prefixed data-names** (`Paper.positions-table`) — bulletproof,
   also serve as broker guards.
2. **Plain data-names** (`qtyEl`, `buy-order-button`) — stable across
   deploys; rotate only on major UI overhauls.
3. **aria-label** — moderately stable; TV changes these less often than
   class names but more often than data-names.
4. **class prefixes with hash suffixes** (`error-v4HmQr2o`,
   `emptyStateRow-pnigL71h`) — the prefix is stable; match with
   `[class*="error-"]`.
5. **Visible text** (tab names, button labels) — last-resort only;
   breaks on localization.
6. **Plain class names** — don't use. TV rotates hashes every deploy.

### 7c. Two types of tables

- **Plain tables**: headers in `<thead><th>`, rows in `<tbody><tr>`,
  cells in `<td>`. Column data-names follow `<field>-column` pattern
  (`symbol-column`, `qty-column`, `pl-column`). Strategy Tester's
  Metrics tables are like this. Use `lib/table.scrape_plain()`.
- **Virtualized tables**: only the visible viewport is in DOM.
  Strategy Tester's List of trades, Order History. Use
  `lib/table.scrape_virtualized()` — scroll & dedup by row-id.

### 7d. Account Manager tab activation

The bottom Account Manager panel only puts ONE tab's table in the DOM at
a time. Clicking Positions tab means Orders table vanishes. This bit me
during order-verification work and forced the fix: activate Orders tab
before baseline snapshot, then poll both tables.

Implication: any future module reading multiple Account Manager tabs
needs to activate each tab once OR treat the tabs as a select-one
constraint.

### 7e. Layout IDs in chart URLs

`https://www.tradingview.com/chart/wqVfOr3Z/?symbol=AAPL` — the
`wqVfOr3Z` segment is a saved-layout identifier. Dropping it (navigating
to `/chart/?symbol=X`) silently wipes all drawings, indicators, and
saved settings. **Always use `lib.urls.chart_url_for(current_url, …)`
when building chart URLs** — it preserves the layout segment.

### 7f. Velocity gating on verified state only

`config.record_action("order")` only fires when `final_status` is
`filled` or `pending_fill`. An `unknown` result doesn't stamp, so the
caller can retry without waiting. This is intentional — the velocity
limit exists to prevent RUNAWAY loops, not legitimate single retries
after ambiguous outcomes.

### 7g. Market hours and fill behavior

A market order placed after hours sits in `Placing` state and fills at
next market open. Paper trading mirrors this. Any "did my trade land"
verification logic must accommodate `pending_fill` — returning
`verified: false` for a placed-but-not-filled order creates retry
pressure that doubles orders.

---

## 8. Testing strategy for Tier 2

For each new surface, go through this checklist:

- [ ] Probe captures all necessary selectors
- [ ] Selectors committed to `selectors.yaml` under new surface key
- [ ] Happy-path CLI call works (one representative command)
- [ ] Error path tested (pass bad input, confirm typed error & exit code)
- [ ] Dry-run mode exists for mutations and doesn't touch browser
- [ ] Audit log shows `request_id`-correlated start/complete pair
- [ ] Selector drift test: temporarily corrupt a selector in yaml,
      confirm `SelectorDriftError` (exit code 4) fires cleanly
- [ ] Interop test: running this surface's CLI while another CLI is
      mid-action serializes via `with_lock("tv_browser")`
- [ ] README CLI examples updated

---

## 9. Stretch ideas (beyond Tier 2)

Only consider these once Tier 2 is solid. Each could be its own project.

### 9a. Backtest sweep

`pine_sweep.py`: given a Pine strategy with input parameters, iterate
through (fastLen=5..30, slowLen=20..100), apply each combo, scrape
metrics, record to CSV. Surfaces the "does X parameter matter" question
programmatically. Needs Tier 2's `pine_editor.apply` reliability + the
existing `strategy_tester.metrics`.

### 9b. Strategy development agent loop

Scheduled: every N hours, for each strategy in a catalog:
1. Apply the strategy
2. Run backtest
3. Read metrics
4. Write a summary entry to a journal file

Given enough history, run meta-analysis: "which strategies degrade
over time as market regime shifts?" Pure read-loop, no mutations beyond
pine apply.

### 9c. Live-vs-paper reconciliation

If you ever connect a real broker: a CLI that reads both
`Paper.positions-table` AND `<RealBroker>.positions-table` and reports
discrepancies. Useful when paper-trading a strategy you intend to go
live with.

### 9d. Claude-in-the-loop Pine debugging

When `pine_editor apply` returns `errors: [...]`, pipe them back to a
Claude session with the source file. Claude edits the Pine, I re-apply,
repeat until clean compile. The infrastructure is all there — just
needs a driver script.

---

## 10. Files to know

| Path | Purpose |
|---|---|
| [tv](../tv) | CLI shim — works from any directory via PYTHONPATH |
| [tv_automation/README.md](README.md) | Usage docs, safety model, exit codes |
| [tv_automation/ROADMAP.md](ROADMAP.md) | **This file** |
| [tv_automation/selectors.yaml](selectors.yaml) | DOM selector single source of truth |
| [tv_automation/limits.yaml](limits.yaml) | Safety limits (allowlist, max qty, velocity) |
| [tv_automation/probes/snapshots/](probes/snapshots/) | Historical probe JSONs — version-controllable for drift diffs |
| [audit/YYYY-MM-DD.jsonl](../audit/) | Per-day append-only action log |
| [pine/broken_test.pine](../pine/broken_test.pine) | Regression test for compile-error scraper |
| [pine/webhook_alert.pine](../pine/webhook_alert.pine) | Working strategy for smoke-testing strategy_tester |
| [../session.py](../session.py) | Chromium attach/launch — unchanged from pre-tv_automation |
| [../preflight.py](../preflight.py) | CDP reachability + sign-in wait |
| [../start_chrome_cdp.sh](../start_chrome_cdp.sh) | Launches the Chromium-Automation profile |

---

## 11. When Claude picks this up again

Tell me to read this file (`tv_automation/ROADMAP.md`) first. Then name
what you want to work on — a Tier 2 surface, one of the unresolved
probes, or a stretch idea. I'll:

1. Verify current state with `./tv status`
2. Read the relevant probe snapshot (if one exists)
3. Run a fresh probe if TV's UI may have drifted
4. Build following the §6 pattern

If you want me to discover drift proactively, ask me to run all the
probes and diff against their latest snapshots. That's a ~5min
selftest that catches UI changes before they bite the next mutation.
