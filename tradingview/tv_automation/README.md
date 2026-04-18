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

**Auto-reconnect preflight.** When TV's "Session disconnected" modal
appears (account signed in from another device), every tv command
auto-dismisses it before doing its work. No manual `reconnect` needed.
Hot-path cost when the modal isn't present is <10ms (one JS
`querySelector`). Explicit probe: `tv chart reconnect`. Detection logic
lives in `lib/session_modal.py` — add new modal phrasings / button
labels there if TV ships a variant.

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
# Region-targeted captures — use when chart-only crop hides what you want:
tv chart screenshot --area full -o /tmp/full.png             # entire viewport
tv chart screenshot --area sidebar -o /tmp/sidebar.png       # right widgetbar (watchlist/alerts/etc)
tv chart screenshot --area pine_editor -o /tmp/pine.png      # Pine editor pane
tv chart screenshot --area account_manager -o /tmp/am.png    # bottom panel
tv chart screenshot --area right_toolbar -o /tmp/tools.png   # right icon strip
```

`--area` defaults to `chart` (the existing crop). `full` captures the
whole viewport — the right call when you need to verify multi-panel
state (e.g. "did the alert dialog actually appear next to the watchlist
sidebar?"). Region captures fall back to `full` if the named region
isn't found (e.g. Pine editor is collapsed); the response includes
`area` (the actually-captured region) and `fell_back: true/false`.

**Vision-driven control: click by pixel coordinates.**

```bash
tv chart click-at 120 19                          # click at viewport (x, y)
tv chart click-at 120 19 --button right           # right-click
tv chart click-at 120 19 --double                 # double-click
tv chart click-at 120 19 --bypass-overlap         # bypass Monaco/overlap-manager intercepts
```

Selector-free — combine with `screenshot --area full` for a vision
loop: take a screenshot → identify the target visually → issue the
click. Useful when DOM selectors break, when the target lacks a
stable selector, or when the target is canvas-rendered.

Result includes `element_before` and `element_after` — what was at
`(x, y)` immediately before and after the click. `element_before`
verifies the click landed on the intended element; `element_after`
notices UI changes (e.g. `backdrop-aRAWUDhF` appearing means a
modal opened). The viewport is typically 1565×812 (one of the
useful coordinate baselines).

**Inventory + click in one round-trip: `describe-screen`.**

```bash
tv chart describe-screen                    # full viewport: screenshot + addressable inventory
tv chart describe-screen --area sidebar     # scope inventory to one panel
tv chart describe-screen --include-all      # include unaddressable elements too
```

Returns the screenshot path AND a JSON list of every clickable element
in the area, each with its `rect`, `center` (ready to feed into
`click-at`), and a `selector_hint` (best-guess CSS selector). Default
filter keeps only "addressable" elements — those with a `data-name`,
`aria-label`, or `id` — since unaddressed elements are rarely useful
targets and bloating the inventory hurts scan-ability. Inventory of
the chart sidebar typically returns 8 entries; of the full chart,
30-100. `--include-all` returns 500+.

This is the read half of the vision-driven loop: instead of taking a
screenshot and querying the DOM separately and cross-referencing,
`describe-screen` returns both linked. Then pass an inventory entry's
`center` to `click-at`.

**Caveat — nested child elements.** A button's `center` may sit
inside a child `<span>` that contains its label text. Clicking that
center hits the child, and some React buttons delegate via
`event.target === button` so the parent's click handler doesn't fire.
The symptom: `element_before` reports a SPAN with no `data_name`,
when you wanted the BUTTON with `data_name="..."`. Fix: click an
offset position within the rect (e.g. 6-10px from the rect edge,
inside the button's padding) so `elementFromPoint` returns the button
itself. The `element_before` field surfaces this immediately so a
vision loop can self-correct.

**One-call abstraction: `click-label`.**

```bash
tv chart click-label "Watchlist"            # opens watchlist sidebar / menu
tv chart click-label "Add symbol"           # clicks the + button
tv chart click-label "Pine"                 # toggles Pine editor
tv chart click-label "Settings" --area sidebar     # scope the search
tv chart click-label "Buy" --bypass-overlap        # for Monaco-blocked targets
```

Wraps the three vision-loop fragments into one call: scan DOM for
elements matching the query (data-name OR aria-label OR text, fuzzy-
scored), pick the top candidate, compute a safe click point with
auto-correction for nested-child traps, click, return verification.

This is the closest thing in the codebase to "click the thing I see"
— no coords, no selectors, just describe what you want. Lower the
bar to selector-free use:

  - data-name⊇/⊆ matches resolve typos in stored selectors
    (the same fuzzy logic as `tv heal`)
  - aria-label and visible-text matches handle UI rewordings
  - safe-point heuristic walks up from `elementFromPoint` to verify
    the click is within the target's subtree, falls back to top-
    padding if center hits the wrong element

**The asymptote.** The genie wish — Computer-Use-grade visual
reasoning across arbitrary UI — needs an LLM in the inner loop to
identify elements without stable identifiers (data-name / aria-label /
text). `click-label` only works when SOMETHING about the target is
addressable. For purely-visual targets (a specific candle on a chart,
a colored bar in a heatmap), you'd need vision-model integration
beyond what this codebase ships.

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

### watchlist (named lists + symbol membership)

The right-sidebar Watchlist is the "set of symbols I care about". Each
named list (e.g. "Tech", "Crypto Watch") stores an ordered set of
symbols rendered with realtime quote columns. `tv watchlist` makes the
list scriptable — useful for "morning prep: build today's watchlist
from screener results" or "reset my crypto list to a hot-list snapshot".

```bash
tv watchlist current                # active list name
tv watchlist contents               # full symbol list (handles virtualization)
tv watchlist list                   # all named lists from the picker
tv watchlist add SPY                # add a symbol to the active list
tv watchlist remove SPY             # remove a symbol from the active list
tv watchlist clear --dry-run        # preview a wipe without committing
tv watchlist clear                  # actually wipe the active list
tv watchlist create "Tech Watch"    # new list, switches to it
tv watchlist rename "Tech v2"       # rename the active list
tv watchlist load "Tech Watch"      # switch to a saved list
tv watchlist copy "Tech Watch v2"   # duplicate the active list
```

**Virtualization**: the sidebar only renders ~10-15 rows in DOM at a
time. `contents` scrolls `[data-name="symbol-list-wrap"]` top→bottom
and dedups by `data-symbol-short`, anchoring termination on the
container's own `scrollTop + clientHeight >= scrollHeight` (a
"two-stagnant-rounds" stop fires falsely while React is still mounting
new rows after a scroll).

**Symbol row attributes** are unusually rich for TV: each row carries
`data-symbol-short` ("MNQ1!"), `data-symbol-full`
("CME_MINI:MNQ1!"), `data-active="true"` for the currently-charted
symbol, and `data-status="resolved"` when the row finished loading.
`contents` returns all four — most other TV tables require parsing
visible text.

**Add idempotency**: `add SYMBOL` short-circuits with
`already_present: true` if the symbol is already in the list — safe
to call from a script without first checking membership.

**Deferred**:
- `delete <list>` — no obvious "Delete" command in the operations
  menu; probably needs hover-reveal trash inside the picker (similar
  to `layouts delete`). Workaround: rename and reuse.
- `reorder` — drag-and-drop on canvas-coordinates; complex.

### screener (stock discovery via the modern unified screener)

Read paths over TradingView's modern stock screener
(`tradingview.com/screener/`). The screener pre-loads ~100 rows
and virtualizes beyond that — `results` scroll-collects up to
`--max-rows` symbols in one call, deduped by ticker.

```bash
tv screener open                              # navigate to /screener/
tv screener current                           # active screen / preset name
tv screener filters                           # list active filter pills
tv screener column-tabs                       # list visible + hidden tab groups
tv screener results                           # scrape (default Overview, up to 1000)
tv screener results --columns Performance     # switch column tab first
tv screener results --max-rows 500            # cap on returned rows
```

**Scope**: STOCKS ONLY. TV's crypto/forex/futures screeners live at
separate URLs and use a legacy `tv-screener` DOM rather than the
modern `screenerContainer-` React wrapper this module targets.
Adding them needs a parallel implementation; deferred.

**Tab-strip overflow**: TV positions tabs that don't fit in the
visible width at `translateX(-999999px)`. They're in DOM but
unclickable until exposed (typically via a "More" overflow chevron
that this module doesn't yet operate). `column-tabs` returns
`visible` and `hidden` arrays so callers can see what's reachable.
Workaround: widen the screener browser window to push more tabs into
the visible strip.

**Filter pills**: each pill carries a stable random hash in its
`data-name` (e.g. `screener-filter-pill-kHEyk7MJ2yfz_KUJUYlOe` =
"Index"). `filters` returns both the hash and the visible pill text
(which includes the active value, e.g. "Price >50"). Setting a
filter programmatically is **deferred** — each pill is a different
UI control (range slider / dropdown / multi-select / date picker),
so each needs its own setter. The pragmatic workflow today:
configure filters once in the UI manually, save as a named screen,
then call `results` programmatically.

**Symbol cell**: the first column packs ticker + company name with a
newline (e.g. `"NVDA\nNVIDIA Corporation"`). Split on `\n` if you
need just the symbol.

### drawings (Pine-emitted chart annotations)

Programmatic chart annotation via a JSON sketch spec. Each sketch is
composed into a Pine v5 indicator that renders horizontal/trend lines,
boxes, labels, and verticals using `xloc.bar_time` (timestamps drive
positioning, no canvas-coordinate math). Re-applying a sketch with
the same name overwrites the chart instance — no clutter.

```bash
tv drawings sketch pine/drawings/sr_levels.json     # apply a saved sketch
echo '<json>' | tv drawings sketch --stdin           # apply from stdin
tv drawings sketch <file> --dry-run                  # emit Pine to /tmp without applying
tv drawings example                                  # print an example sketch JSON
tv drawings clear --name "S/R Levels"                # remove a drawings indicator
```

**Why an emitter, not canvas clicks**: TV's chart canvas needs (price,
time) → (pixel x, y) projection logic that lives inside React state.
Reading it from outside is hairy and breaks every UI tweak. Pine
drawings render natively — `line.new()` accepts `xloc.bar_time` so
timestamps drive positioning directly, no projection math. Trade-off:
drawings aren't user-draggable post-creation. For LLM-driven
annotation that's the right trade — drawings are recomputable from
the JSON, not edited.

**Drawing types** — see [drawings.py](drawings.py) for the full
schema. Quick reference:

```json
{"type": "horizontal", "price": 27000, "color": "blue", "style": "dashed", "label": "R1"}
{"type": "trend_line", "p1": ["2026-04-15T09:30", 26800.0], "p2": ["2026-04-17T15:00", 27200.0], "color": "orange", "extend": "right"}
{"type": "box", "p1": ["...", 26800], "p2": ["...", 27200], "border_color": "green", "bg_color": "green", "bg_alpha": 85}
{"type": "label", "at": ["...", 27000], "text": "Recent high", "color": "blue"}
{"type": "vertical", "time": "2026-04-17T15:00", "color": "purple", "label": "Pivot"}
```

**Time formats**: ISO 8601 string (UTC assumed if no offset) OR Unix
epoch seconds (int).

**Color formats**: named (`"red"`, `"blue"`, `"green"`, `"orange"`,
`"purple"`, `"yellow"`, `"aqua"`, `"fuchsia"`, `"white"`, `"black"`,
`"gray"`, `"silver"`, `"lime"`, `"maroon"`, `"navy"`, `"olive"`,
`"teal"`) OR hex (`"#ff0000"`).

**Pine alpha is 0 (opaque) ↔ 100 (transparent)** — opposite of CSS.
Most callers want `bg_alpha: 80-90` for subtly-tinted boxes.

**Sample sketches**: see [pine/drawings/](../pine/drawings/) for ready-to-apply
JSON files (S/R levels, range box).

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

### act (LLM-in-loop vision driver)

Autonomous goal-follower. Wraps `describe-screen` + `click-label` +
`click-at` in a loop: each turn sends (goal, inventory, screenshot,
history) to an LLM, parses a JSON decision, executes one atomic
action, loops until `done` / `fail` / step cap / cost cap.

```bash
tv act "open the watchlist sidebar"                      # anthropic default
tv act "add SPY to the active watchlist" --max-steps 15
tv act "<goal>" --provider ollama --model qwen2.5vl:7b --vision
tv act "<goal>" --provider ollama --model qwen3.5:27b    # text-only
tv act "<goal>" --read-only                              # refuses mutating
tv act "<goal>" --dry-run                                # model decides, no clicks
```

**Three LLM backends:**

| Provider | Endpoint | Cost | Vision default | Notes |
|---|---|---|---|---|
| `anthropic` | Anthropic SDK | paid | on | Needs `ANTHROPIC_API_KEY` in `.env`. Default model: `claude-sonnet-4-6`. Aliases: `sonnet` / `opus` / `haiku`. |
| `ollama` | `http://localhost:11434/v1` | free | off | OpenAI-compat. Default model: `qwen3.5:27b` (text). Pass `--vision --model qwen2.5vl:7b` for screenshot support. |
| `mlx` | `http://localhost:8080/v1` | free | off | OpenAI-compat (`mlx_lm.server`). No default model — pass `--model`. |

Vision is on by default for Anthropic; off for local providers (most
pulled local models aren't VL). `--vision` forces on; `--text-only`
forces off. In text-only mode the model drives via the structured
inventory alone — works for most UI goals where the target has a
`data_name` / `aria_label`, fails for canvas targets (chart candles,
drawings, heatmap cells).

**Action schema** — the model emits ONE of these per turn:

```json
{"action": "click_label", "query": "<description>", "reason": "<why>"}
{"action": "click_at",    "x": 120, "y": 240, "reason": "<why>"}
{"action": "type",        "text": "<text>", "reason": "<why>"}
{"action": "press",       "key": "Escape", "reason": "<why>"}
{"action": "describe_only", "reason": "<re-scan after a state change>"}
{"action": "done", "result": "<short success summary>"}
{"action": "fail", "reason": "<blocked — e.g. missing permissions>"}
```

**Budget guards.** `--max-steps` (default 10) and `--max-cost-usd`
(default $0.50) abort the loop before runaway cost. `--read-only`
refuses any action whose `query` matches `/buy|sell|place|submit|
confirm|delete|remove|cancel|close|save/i` plus all `click_at`
(opaque intent). Raises `LoopBudgetExceededError` (exit 9) or
`GoalUnachievableError` (exit 10).

**Transcripts.** Every run persists per-step decisions + action
results to `~/Desktop/TradingView/act_transcripts/<request_id>/` —
one JSON file per step plus the screenshot path. Enables replay,
debugging, and cost audit.

**Limitations (Phase 1 scope).** Purely-visual targets (canvas,
heatmaps), multi-app control, and streaming/realtime observation are
future phases — see [VISION_LOOP_PLAN.md](VISION_LOOP_PLAN.md).

### heal (suggest replacement selectors when stored ones drift)

When TradingView ships a UI tweak that breaks `selectors.yaml`, the
historical fix was: re-run the relevant probe, eyeball the snapshot
diff, edit selectors.yaml. `tv heal` shortcuts that:

```bash
tv heal alerts_panel.sidebar_icon
# Tries each candidate from selectors.yaml. If any work, prints
# "still resolves" + which one. If all fail, runs the healer against
# current DOM and prints ranked replacement candidates.

tv heal --selector '[data-name="alerts-typo"]'
# Heal an arbitrary selector — useful for testing or one-off recovery.

tv heal --selector '[data-name="some-pill"]' \
    --scope 'div[class*="screenerContainer-"]'
# Restrict the healer's DOM scan to a specific area (e.g. screener
# container) — prevents matching unrelated elements elsewhere.
```

**How it works**: parse the failed selector → extract identifying hints
(data-name, aria-label, id, data-qa-id, has-text) → scan current DOM
for elements that fuzzy-match the hints → rank by closeness:

  - `data-name==`     — exact match (100 pts)
  - `data-name⊇`      — current name CONTAINS the original (65 pts;
                        e.g. original `alerts`, current `alerts-icon`)
  - `data-name⊆`      — original CONTAINS current (45 pts;
                        e.g. typo `alerts-typo` vs real `alerts`)
  - `aria-label==`    — exact match (80 pts)
  - `aria-label⊇/⊆`   — partial (50 / 30 pts)
  - `id==/⊇`          — id match (95 / 60 pts)
  - `data-qa-id==/⊇`  — chart-legend identifier (100 / 60 pts)
  - `text==/⊇`        — visible-text match (35 / 18 pts; weakest)
  - `role==`          — tie-breaker only (10 pts)

Each candidate's response includes a `suggested_selector` ready to
paste into `selectors.yaml` as a new fallback under the same role.

**Deliberately report-only.** Auto-modifying `selectors.yaml` is the
failure mode that makes this kind of system fragile (a wrong heal
that works once but breaks later pollutes the file forever, and
YAML edits would mangle the file's heavy comments). Healed
selectors are SUGGESTIONS; the human/LLM in the loop applies them.

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
| 9    | `LoopBudgetExceededError` — `tv act` hit --max-steps or --max-cost-usd |
| 10   | `GoalUnachievableError` — `tv act` model declared goal blocked |

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
