# Action plan: granting "robust visual understanding + action selection"

Drafted 2026-04-17. The asymptote of the vision-loop work shipped this
session. This doc lays out what would be needed to close the gap from
"selector-free clicking on addressable targets" to the full genie
wish:

> "Grant me robust visual understanding and action selection across
> changing desktop and web interfaces, with reliable recovery when
> layouts, labels, or states differ."

Owner: future Claude sessions OR a separate computer-use sub-agent.
Estimated total scope: 5–10 focused sessions across 3–6 weeks of
calendar time, depending on how aggressive the cross-application work
gets.

---

## 1. Where we are today

Shipped this session (commits `e248336` → `66d9246`):

| Tool | Layer | What it does |
|---|---|---|
| `tv chart screenshot --area X` | read | Capture chart / sidebar / pine_editor / right_toolbar / account_manager / full viewport. |
| `tv chart describe-screen` | read | Screenshot **plus** ranked inventory of every addressable element (data-name / aria-label / id / data-qa-id) with rect, center, selector_hint. |
| `tv chart click-at <x> <y>` | act | Pixel-coord click with `element_before`/`element_after` verification. |
| `tv chart click-label "<query>"` | act | One-call: free-text query → fuzzy match → safe click point → click → verify. |
| `tv heal <surface>.<name>` | recover | Parse failed selector for hints → fuzzy-scan DOM → suggest replacements with `suggested_selector` ready to paste. |
| `lib/overlays.bypass_overlap_intercept` | infra | Async context manager that disables pointer events on `#overlap-manager-root` so Pine Editor's wrapper doesn't intercept toolbar clicks. |

Together these form a **see → understand → choose → act → recover**
loop that works **for any element with a stable identifier** —
data-name, aria-label, id, data-qa-id, or distinctive visible text.
That covers ~95% of TradingView's UI.

The **5% gap**: purely-visual targets — chart candles at a specific
price, colored heatmap cells, drag handles, drawing-tool anchor
points, anything canvas-rendered. Plus the **continuous-loop gap** —
each tool invocation is one atomic step; multi-step plans require an
outer driver.

---

## 2. The gap, decomposed

| Gap | Concrete failure case | Why our loop can't solve it today |
|---|---|---|
| Purely visual targets | "Click the highest candle in the last hour" | Candles are rendered to canvas — no DOM addressability. `describe-screen` returns nothing useful. |
| Region-only labels | "Click the green button below the price label" | Spatial reasoning over the screenshot. We can locate elements by attributes, not by position relative to OTHER elements. |
| Multi-step plans | "Place a buy at $27,000 with a 10-point stop" | Each tool is one step. No driver chains describe-screen → click-label → describe-screen → click-label → verify with goal-aware termination. |
| Drift recovery beyond hints | Selector worked yesterday, today the panel was redesigned and the data-name is gone entirely | `heal` only suggests when SOMETHING about the original survives in DOM. Whole-element redesigns fall through. |
| Cross-application | "Open the broker terminal beside TradingView and place the same trade" | Playwright is single-page-context. No OS-level control to switch apps or read other windows. |
| Realtime observation | "Wait until price crosses 27000, then click Buy" | Each `describe-screen` is a one-shot snapshot. No streaming / polling primitive. |

---

## 3. Phased plan

Each phase is independently shippable. Earlier phases unlock later
ones; effort estimates assume the prior phase is in place.

### Phase 1 — `tv act <goal>`: the LLM-in-loop driver (~1 session)

**Goal**: Wrap the existing tools in an autonomous loop that takes a
natural-language goal and chains multiple atomic steps.

**Deliverables**:
- `tv_automation/act.py` — new module, CLI entry `tv act "<goal>"`.
- Each iteration: `describe-screen` → call Claude API with
  (screenshot, inventory, goal, history) → parse decision → execute
  via `click-label` / `click-at` / typing keys → repeat.
- Stops when Claude returns `done` OR step counter exceeds N (default
  10) OR explicit failure.
- Records every step in audit log with `request_id` correlation.

**Dependencies**:
- `anthropic` SDK (likely already available in `.venv`).
- `ANTHROPIC_API_KEY` env var. Document how to set up.
- Cost per loop: ~1 vision message per step × (~3000 input tokens +
  ~500 output) ≈ $0.02–0.05 per step. 10-step loops ≈ $0.30–$0.50.

**Success criteria**:
- `tv act "open the watchlist sidebar and add SPY"` succeeds
  end-to-end without hand-coding the steps.
- Failure modes (LLM hallucinates element, goal ambiguous) surface
  as clean error messages, not cryptic stack traces.

**Risks**:
- Cost escalation if a goal triggers an unbounded loop. Mitigation:
  hard step cap, explicit cost budget surfaced in audit.
- Token bloat from repeated screenshot resends. Mitigation: only
  resend image when the inventory diff is significant.

### Phase 2 — Vision-model fallback for purely-visual targets (~1 session)

**Goal**: When `describe-screen` returns no matches for a query (or
the query implies a visual target — "the green candle", "the red
arrow"), fall back to a vision-model identification step.

**Deliverables**:
- `tv chart click-visual "<description>"` — sends screenshot +
  description to Claude with vision, asks for (x, y) coordinates,
  clicks them via `click-at`.
- Optional `--annotate` flag: vision model returns coords AND a
  bounding box, we draw the box on a debug screenshot for review.
- Integrates with `click-label`: when `min_score` rejects all
  candidates, optionally fall through to `click-visual` (gated by a
  flag to keep cost predictable).

**Dependencies**: same Anthropic SDK + key from Phase 1.

**Success criteria**:
- `tv chart click-visual "the highest candle in the last 20 bars"`
  finds and clicks the right pixel on the canvas.
- `tv chart click-visual "the orange box in the middle of the chart"`
  works for our `tv drawings sketch` rendered overlays.

**Risks**:
- Vision-model coordinate accuracy: typically ±10-30 pixels. May need
  iterative refinement (click, observe via screenshot, adjust).
- Hallucinated coordinates outside the viewport. Mitigation: validate
  against viewport bounds; reject + retry with a sharper prompt.

### Phase 3 — Visual-diff healing (~1 session)

**Goal**: When `heal`'s fuzzy hint matching returns no candidates,
fall back to visual matching against historical probe snapshots.

**Deliverables**:
- Extend `lib/selectors_healer.py` with `find_candidates_visual` that
  takes a probe snapshot's element bbox + description and asks the
  vision model to locate the equivalent in current DOM.
- `tv heal --visual <surface>.<name>` flag — opt-in because of the
  vision-call cost.
- Probe snapshots already store enough metadata (rect, text,
  data-name) to drive the visual matcher — no schema changes needed.

**Dependencies**: Phase 2's vision integration.

**Success criteria**: when TV ships a UI redesign that removes a
data-name entirely, `heal --visual` still finds the new selector with
≥80% accuracy on a corpus of 5+ test cases.

### Phase 4 — Spatial reasoning primitives (~1 session)

**Goal**: Address targets by their RELATIVE position to other
elements ("the button BELOW the price label", "the X to the right of
the symbol row").

**Deliverables**:
- `tv chart click-relative "<anchor>" <direction> "<target>"` —
  finds anchor via `click-label` logic, then scans in the specified
  direction for the target (or applies the vision model if needed).
- Direction tokens: `above`, `below`, `left-of`, `right-of`,
  `inside`.
- Useful for the watchlist-row X button (revealed only on hover) —
  `click-relative "VX1!" inside "remove"` would work.

**Dependencies**: Phase 1 (driver) + Phase 2 (vision fallback for
ambiguous spatial queries).

### Phase 5 — Cross-application control (~3+ sessions, research-grade)

**Goal**: Step beyond Playwright's single-page scope to OS-level
control: open / focus other apps, read clipboard from non-TV
sources, drive native UI.

**Deliverables**:
- `tv_automation/cross_app/` — new sub-package.
- macOS-specific: `pyobjc` for accessibility APIs, screen recording
  permissions, AppleScript shimming.
- Linux: `xdotool` / `wmctrl` shimming.
- Cross-platform abstraction: `tv app focus <name>`, `tv app
  screenshot <name>`, `tv app click-label <name> "<query>"`.

**Dependencies**: macOS accessibility permissions for the
Chromium-Automation profile + Terminal. Probably new entitlements.

**Success criteria**: `tv app focus "Interactive Brokers TWS" && tv
app click-label "Interactive Brokers TWS" "Buy"` works end-to-end.

**Risks**:
- Permission model varies wildly across OSes.
- Native UI lacks DOM-equivalent introspection — `describe-screen`'s
  approach doesn't translate. Heavy reliance on accessibility APIs
  (which are inconsistent) or vision models (which are expensive).
- Out-of-scope for the TradingView use case; only build if
  multi-app workflow becomes a real requirement.

### Phase 6 — Streaming / realtime observation (~2 sessions)

**Goal**: Move from one-shot screenshots to continuous observation
with event-driven action selection.

**Deliverables**:
- `tv chart watch <selector_or_description> --until <condition>` —
  poll the page, fire a callback when the condition is met (e.g.
  price-crossed, button-appeared).
- WebSocket-style event stream: subscribe to URL changes, console
  log appends, specific DOM mutations.
- `tv act --realtime "<goal>"` — variant of Phase 1's driver that
  runs the LLM loop on events rather than fixed iterations.

**Dependencies**: Phases 1 + 2.

**Risks**: high latency cost of vision calls makes truly-realtime
hard. Practical lower bound: ~2-3s per cycle.

---

## 4. Cross-cutting concerns

These apply across all phases and should be designed in from Phase 1:

### Cost ceiling
Every `tv act` / `click-visual` invocation has a non-zero API cost.
Add a mandatory `--max-cost-usd` flag with a sane default ($0.50)
that aborts the loop when exceeded. Surface running cost in audit.

### Audit log integration
Phase 1+ should emit per-step audit entries with `request_id`
correlation, just like every other surface. Include the model
decision, the action taken, and the observed result so `tail -f
audit/...jsonl` shows the loop's reasoning trail.

### Failure-mode taxonomy
Define typed errors for the new failure modes:
- `VisionAmbiguousError` — vision model returned multiple equally-
  likely targets.
- `LoopBudgetExceededError` — step or cost cap hit.
- `GoalUnachievableError` — model declared the goal can't be done
  from current state (e.g. requires a logged-out user).

These map to clean exit codes via `lib/cli.run`.

### Reproducibility
Every `tv act` run should optionally save its full transcript
(screenshots, decisions, results) to a directory so failed runs can
be replayed and debugged. Without this, vision-model non-determinism
makes regression-finding miserable.

### Safety guards
Phase 1+ inherits the existing `assert_paper_trading` guard for any
order-placing action. Add a `--read-only` flag for the loop driver
that refuses to execute anything classified as mutating.

---

## 5. Explicit non-goals

What NOT to build, even if tempting:

- **General-purpose desktop agent**. Stay scoped to TradingView +
  immediately-adjacent broker / data-source UIs. Building a generic
  Computer Use clone within this project is duplicative of
  Anthropic's frontier work.
- **Sub-second realtime loops**. The vision-call latency floor is
  too high. Use Pine alerts → webhook → bridge for true realtime
  paths (already shipped); reserve `tv act` for plan-and-execute
  workflows that tolerate 2-10s per step.
- **Selector auto-write to selectors.yaml**. `heal` is suggest-only
  for good reasons (auto-pollution, comment-loss). Auto-writes belong
  in a separate `selectors_healed.yaml` review queue, never in the
  human-curated registry.

---

## 6. Open questions

To answer before starting Phase 1:

1. **Which Claude model for the vision calls?** Sonnet 4.6 is
   probably right for cost/quality balance. Opus 4.7 for harder
   visual reasoning at higher cost. Worth A/B-ing on a test corpus.
2. **Where do API keys live?** Probably `.env` in the project root
   (gitignored), loaded via `python-dotenv`. Add to setup docs.
3. **Should `tv act` run in this process or fork a sub-process?**
   Forking isolates cost / state but adds latency. Probably
   in-process for MVP; sub-process if memory becomes a concern.
4. **How does `tv act` discover available actions?** Hard-code the
   list from the existing CLI surfaces, OR scan `tv --help` output,
   OR generate a JSON schema. Hard-code is simplest for MVP.

---

## 7. The two-line summary

What's been built: **the addressable-target half of the wish** —
selector-free clicking, screenshot+inventory in one call, drift
recovery for hint-bearing elements. Live-tested across the chart UI.

What's missing: **the visual-reasoning half** — purely-visual
targets, multi-step LLM-in-loop driving, cross-application control.
Phase 1 (LLM-in-loop) is the next 1-session build; Phases 2-6 are a
sequence with diminishing per-session value but increasing reach.
