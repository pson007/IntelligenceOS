# HumanOS Product Thesis — Trading
## IntelligenceOS: a decision interface for active trading

---

## Core thesis

**The trader's job is to judge. Everything else — gathering charts,
reconciling timeframes, computing R:R, drafting strategy code, logging
decisions — is staff work the AI should do.**

Today, even with TradingView, Bloomberg, X feeds, Discord rooms, and
backtesting tools, active traders spend most of their screen-time
*preparing* to decide instead of deciding. Multi-timeframe context
doesn't assemble itself. Risk math happens on paper or in the head.
Strategy code takes 20 minutes to write for a setup that'll be stale
in two candles. Post-trade review rarely happens because it requires
yet another tool.

IntelligenceOS treats that preparation as infrastructure. The trader
sees a *Decision Brief for one trade*: signal, levels, R:R, rationale,
per-timeframe breakdown, backtestable strategy, one-click bracket
entry. Sub-30 seconds end-to-end. The human's only job is to say yes,
no, or "tell me more" — and "tell me more" is one click.

This is a HumanOS instance. The generic principle — *AI works the case,
human makes the call* — is the same as the broader thesis. This doc
specs what that looks like in a domain where decisions happen every
few minutes, positions cost real money, and being wrong is instant.

---

## Why trading is the right wedge

Trading is a rare domain where the full loop — decision → action →
outcome → signal back to the decision system — closes in minutes to
hours, not months. That matters because:

1. **The feedback loop is short enough to calibrate.** A vendor-renewal
   AI's "medium confidence" is unverifiable for a year. A trade-entry
   AI's "75% confidence on a Long" either wins or loses by end-of-day.
   Calibration infrastructure is *buildable* here in a way it isn't
   for most business decisions.
2. **The user tolerates small UI changes.** Traders already use Level 2,
   DOM, footprint charts, cryptic multi-window setups. Unlike a sourcing
   manager who wants a "calm briefing," a day trader will accept
   information-dense UI as long as it's useful per-pixel.
3. **Decisions are reversible within a constrained window.** A bracket
   order you regret can be flattened in one click. Unlike "should we
   sign this vendor," entering a trade is a two-way door — which makes
   it a safer domain to let AI be wrong in.
4. **The domain has clear ground truth.** P&L doesn't lie. Confidence
   calibration, provider quality, strategy backtest accuracy — all
   measurable with close-of-day data. Most business AI tools never
   face this.
5. **The user is the decision owner.** No approval chains, no CFO
   sign-off, no legal review. The trader's account is the trader's
   account. Every piece of the decision interface maps to one human.

These properties make trading the right *first* domain for HumanOS —
not because it's the biggest market, but because it's where the
principles can be *proven* end-to-end with real outcome data. Anything
that works here generalizes outward; anything that doesn't work here
won't work in longer-cycle domains either.

---

## What's already built

IntelligenceOS ships the core HumanOS loop for a single-trade decision:

| HumanOS concept                  | Current IntelligenceOS              | File                         |
|----------------------------------|-------------------------------------|------------------------------|
| Decision header                  | Signal pill + confidence + R:R     | [ui/index.html](tradingview/ui/index.html) |
| What matters now                 | Entry / Stop / TP levels, $ format | [ui/app.js:renderAnalysisResult](tradingview/ui/app.js) |
| Trusted context: confirmed       | Live chart + capture metadata       | TV chart via CDP             |
| Trusted context: AI synthesis    | LLM rationale + per-TF breakdown    | [analyze_mtf.py](tradingview/tv_automation/analyze_mtf.py) |
| One-click get-me-what-I-need     | Analyze / Deep / Apply-pine         | [ui_server.py](tradingview/ui_server.py) |
| Commitment surface               | Apply-to-order (brackets) + Flatten | [trading.py](tradingview/tv_automation/trading.py) |
| Provider choice (human agency)   | ollama / claude_web / anthropic     | [analyze_mtf.py:_resolve_model](tradingview/tv_automation/analyze_mtf.py) |
| Auditable reasoning trace        | JSONL audit log per request_id      | [lib/audit.py](tradingview/tv_automation/lib/audit.py) |

A full single-TF decision runs in **~20 seconds** on claude_web Sonnet
4.6. A deep 9-timeframe analysis with strategy-script generation runs
in **~60 seconds**. The trader captures, analyzes, reads rationale,
applies brackets, places order — all from one screen. That's already
operational HumanOS for a single-trade decision.

---

## The gaps — what's missing to make this *real*

The current product is a *working loop*; it's not yet a *trustworthy
decision interface*. Five gaps separate it from that.

### Gap 1 — Calibration (the biggest)

Today the UI shows "confidence: 72%" and the trader has to decide
whether to trust that number. There's no history showing:
- How often this provider has been right at this confidence level
- Which market regimes (trending/range/news) each provider handles well
- Whether confidence scores move meaningfully with setup quality

**What's needed**: a lightweight outcome-logging layer that records
(signal, confidence, levels, timestamp) and reconciles against
realized P&L after each trade. A confidence-calibration plot — "when
Opus says 75%, it's right 68% of the time" — beside every analysis.

This is the single highest-leverage addition. Without it, every other
sophistication is decoration.

### Gap 2 — Explicit unknowns surface

Current UI shows what the AI concluded, not what it *didn't know*.
The original HumanOS thesis calls this "unknowns that could change
the decision" — the piece most tools skip entirely.

**What's needed**: a dedicated "What could change my mind" section in
the Decision Brief. Examples for trading:
- "FOMC in 40 minutes — no position before release"
- "ES futures front-month rolls in 2 days — thin liquidity"
- "Earnings for top-weighted NDX constituent after close"
- "Current price is 80% of the way to a prior-day VAH; resolving
  that level in either direction flips the setup"

Each unknown should have a one-click action that resolves it
(check the economic calendar, pull options flow, show the
volatility term structure). Unknown + action in the same row.

### Gap 3 — Multi-provider disagreement view

The live bench showed providers sometimes agree on direction but
disagree on levels (Gemma wants 26950 TP; Claude wants 26920). The UI
picks one and hides the rest. But disagreement *is signal* — if every
provider says Long, confidence is earned; if providers split, the
setup is ambiguous.

**What's needed**: a "second opinion" surface that runs the same
question through 2-3 providers and shows the consensus + the
disagreement. Not for every trade — that's expensive — but available
as a one-click "pressure test this setup" action for trades where
size is meaningful.

### Gap 4 — Decision log

After clicking Apply-to-order, the system knows: symbol, time, side,
levels, which analysis drove it. Today it's in `audit/*.jsonl` but
not surfaced. There's no "trade journal" view, no way to review last
week's decisions, no "your confidence-Long calls closed +1.4R on
average; your confidence-Skip calls avoided -0.6R."

**What's needed**: a decision-log view that joins analysis events with
trade outcomes. Minimum viable: a list of past decisions with "you
took / you skipped" + realized R-multiple. This is also what feeds
Gap 1 (calibration).

### Gap 5 — Reversibility-aware commitment

Currently Apply-to-order looks identical whether it's a 1-contract MNQ
scalp or a 10-contract swing. But the *weight* of those decisions is
wildly different. The commitment surface should reflect that.

**What's needed**: the Quick Order bar should show:
- Position size × point value = dollar risk
- Relative to daily loss limit (if configured)
- "This trade commits 18% of today's loss budget" — friction-adjusting
  feedback
- Distinct visual treatment for "two-way door" trades (small scalps)
  vs "one-way door" equivalents (size that would sting)

This isn't about slowing the trader down on small trades. It's about
*visibly calibrating the UI's weight* to the financial weight of the
decision.

---

## Revised design principles (for trading specifically)

The original HumanOS principles hold — decision-order, calm by default,
trusted info legible, AI as staff not authority, missing info
actionable, minimize context switching — but trading demands three
additions:

### 7. Calibration is a first-class UI element
Every confidence score shown must be earnable — i.e., backed by a
visible historical accuracy track. If a provider has no history for
the current regime, say so explicitly. "Opus 62%" means nothing until
it's paired with "Opus has been calibrated at ±3% over the last 30
MNQ Skip signals."

### 8. Surface what could flip the decision, not just what drove it
The absence of information is information. An analysis that doesn't
show *what could change it* is falsely confident. The "What could
change my mind" slot has to exist even if it's sometimes empty.

### 9. The UI's weight scales with the trade's weight
Friction for small reversible trades should be near-zero. Friction for
position sizes that would matter should be visible without being
punitive. The commitment surface is not a single shape.

---

## The Decision Brief — trading shape

What one trade decision looks like in IntelligenceOS (ideal-state
after the gaps close):

```
┌─────────────────────────────────────────────────────────────┐
│ MNQ1! · 5m · $26,842 (+1.28%)                     [10:48]   │
│                                                              │
│ ▸ Signal: LONG   Confidence: 72%  (Opus track: 65% @ 70%+)  │
│ ▸ Entry 26,842   Stop 26,780   TP 26,920   R:R 1.26:1       │
│ ▸ Size: 1 MNQ = $310 risk · 14% of today's budget           │
│                                                              │
│ WHY:  Macro Trend BULLISH / Flow UP; price holding above    │
│       rising fast EMA after clean pullback from ~26,885     │
│       swing high to ~26,775 and reclaim.                    │
│                                                              │
│ CONFIRMED        SYNTHESIZED       UNKNOWN — 1 CLICK        │
│ • Price 26,842   • Structure: HH   • FOMC in 40m [check]    │
│ • Trend: Up      • 5m trigger ok   • NDX earns after [sched]│
│ • EMA: 26,820                      • Vol term curve [pull]  │
│                                                              │
│ ALT PATHS                                                    │
│ • Wait for 26,820 retest — better R:R (2:1) but may miss    │
│ • Skip — current mid-range; no fresh structure break        │
│                                                              │
│ SECOND OPINION                                               │
│ • Sonnet: Long 72% (same levels)                            │
│ • Gemma:  Long 75% (entry 26,800 — aggressive pullback)     │
│ ✓ Convergence on direction; slight disagreement on entry    │
│                                                              │
│ [ Apply to order ]  [ Apply pine strategy ]  [ Pressure test ]│
│ [ Skip and log reason ]              [ Dismiss — no trade ]  │
└─────────────────────────────────────────────────────────────┘
```

Every element is real or buildable. Highlighted cells are the gaps
above made concrete.

---

## Roadmap — what to build, in order

Priority is by leverage, not by technical difficulty. Each item closes
one gap and unblocks the next.

### Phase 1 — Calibration infrastructure *(closes Gap 1, Gap 4)*

- **Decision log table** — every Analyze/Deep run writes `(request_id,
  ts, provider, model, signal, confidence, entry, stop, tp, symbol, tf)`
  to a SQLite file.
- **Outcome reconciliation** — daily job (or on-demand) queries TV for
  realized high/low/close of positions and joins against the decision
  log. Each decision gets a P&L tag: `hit_tp`, `hit_stop`, `expired`,
  `skipped_and_right`, `skipped_and_wrong`.
- **Calibration chart** — a new tab or side panel that shows, for each
  provider/model, a reliability diagram (predicted vs. realized accuracy
  at each confidence bucket). Updated daily.
- **Inline calibration chip** in the Decision Brief: next to
  "Confidence: 72%" show "(Sonnet track: 68% @ 70-80% bucket)."

### Phase 2 — Unknowns surface *(closes Gap 2)*

- **Economic calendar integration** — one-click action that pulls
  upcoming high-impact events within N hours for the underlying.
- **Options flow hook** — where available, pull current-day unusual
  options activity for the symbol.
- **Prompt change** — add a required `unknowns[]` field to the
  analysis JSON schema. Each unknown is `{description, resolves_how,
  action_id}`. If the LLM can't produce any, it emits an empty array
  with a note.
- **UI slot** — new "What could change my mind" section between
  rationale and per-TF breakdown. Each unknown renders with its
  one-click resolver.

### Phase 3 — Reversibility-aware commitment *(closes Gap 5)*

- **Daily loss budget config** — one env var / UI setting, e.g.
  `DAILY_LOSS_LIMIT=2000`.
- **Pre-trade check** — compute `size × point_value × (entry - stop)`
  in dollars. Compare to remaining budget.
- **Commit-bar color scale** — green (<10% of budget), amber (10-30%),
  red (>30%). Red trades require a second click to confirm.
- **Hard stop** — if executing would exceed the budget, the Apply
  button disables with a clear explanation.

### Phase 4 — Multi-provider pressure test *(closes Gap 3)*

- **New endpoint** `POST /api/analyze/second-opinion` — runs the
  *same* image through 2-3 providers in parallel, returns a consensus
  object `{consensus_direction, all_providers_agree, level_spread,
  per_provider[]}`.
- **UI button** "Pressure test" in the Decision Brief — only rendered
  when trade size > 5% of budget (see Phase 3) so it's not a casual
  click that burns quota.
- **Consensus badge** in the result: `✓ 3/3 agree` or `✗ 1/3 agree —
  check the disagreement`.

### Phase 5 — Post-trade review surface

- **Journal view** — list of past decisions with outcome, confidence,
  and a one-sentence "what I should learn" slot the trader fills in.
- **Weekly rollup** — P&L attribution: which setups worked, which
  providers drove winners/losers, what the trader's override rate was
  (did you skip what the AI said Long and regret it?).
- **Export** — copy decisions as structured notes for compliance or
  taxes.

---

## Measurement

How to know this is working. Instrument from day one — don't bolt on.

| Metric                                  | What it signals                     | How to measure                          |
|-----------------------------------------|-------------------------------------|-----------------------------------------|
| Time-to-decision                        | Product's raw value                 | Click Analyze → click Apply-to-order    |
| Trades skipped after analysis           | Quality of the "Skip" signal        | Skipped + price moved against = saved   |
| Confidence calibration error (per provider) | Trust in the AI layer           | |predicted conf − realized accuracy|    |
| Override rate                           | Does the user trust the system?     | Trades placed *against* the AI's signal |
| Override P&L                            | Is the user's override justified?   | Realized R of overrides vs. followed    |
| Decisions per session                   | Friction level                      | N trades / hour of active use           |

Vanity metrics to resist: feature usage counts, button-click heat
maps, "engagement." None of these tell you whether the trader is
making *better decisions*.

---

## The wedge — what's different about this vs. what exists

Active traders already have tools. What distinguishes IntelligenceOS
from Bloomberg, TradingView, Interactive Brokers, NinjaTrader,
TrendSpider, and the newer AI-chart tools:

- **Bloomberg / Refinitiv**: reference data + news + news-driven
  workflows. Zero opinion, zero recommendation, zero decision
  interface. Still requires the trader to be the integration layer.
- **TradingView**: charting + community + scripted alerts. Excellent
  at the chart layer; no AI reasoning about *this chart right now*.
  Pine community-script quality is wildly variable.
- **Interactive Brokers / brokers**: execution + some analytics.
  Commoditized, not opinionated.
- **TrendSpider / VectorVest / similar AI-chart tools**: pattern
  recognition + signals. Usually pre-trained classifiers, not
  LLMs, and not open about confidence calibration. Don't offer
  strategy generation or multi-TF reasoning.

**IntelligenceOS's defensible wedge**:

1. **The decision interface itself** — no competitor frames trading
   as a Decision Brief with the confirmed/synthesized/unknown
   hierarchy.
2. **Provider-agnostic + local-first** — ollama + claude_web +
   anthropic in one UI. Nobody else offers $0/call local inference
   alongside frontier models with a calibrated comparison.
3. **Pine strategy generation (not just indicators)** — you get a
   backtestable artifact, not a chart annotation. A differentiator
   once strategy quality is proven.
4. **Outcome-measured, not engagement-measured** — if the calibration
   chart (Phase 1) becomes visible in the product, that's a moat.
   Nobody else in the category ships honest confidence tracking.

The wedge isn't in capabilities anyone couldn't copy. It's in the
*discipline* of measuring whether the tool actually helps, visibly,
and improving on that signal — which most of the category avoids
because it would reveal how often their AI is wrong.

---

## What this thesis is NOT

- Not a consumer product pitch. This is a tool for active traders
  who are comfortable with TradingView, understand brackets and R:R,
  and want to reduce cognitive load — not a "robo-advisor for
  everyone."
- Not a backtesting platform. The Pine strategy output hands off to
  TradingView's backtester; IntelligenceOS doesn't run simulations
  itself.
- Not a signal-service. There's no subscription feed of "Claude says
  buy MNQ at market." Every decision is user-initiated on the user's
  own chart.
- Not a replacement for broker infrastructure. IntelligenceOS drives
  TradingView's paper-trading or connected brokers; it doesn't
  clear or custody anything.

Staying narrow is the whole point. The broader HumanOS thesis can
generalize later; the trading instance has to be *demonstrably good
at trading* first.

---

## Next concrete step

Ship **Phase 1 (calibration infrastructure)** before adding any more
features. Specifically:

1. Write `tv_automation/decision_log.py` — SQLite wrapper, single
   table, insert on every `analyze.done` audit event.
2. Write a script that pulls TV trade history, joins to decisions,
   writes outcome tags back.
3. Add a `/api/calibration/chart` endpoint + a minimal chart page.
4. Expose "Provider track: X% @ Y%" chip in the Decision Brief.

Two weeks of work. Once that ships, the product stops being "pretty
UI over Playwright + LLMs" and becomes "the only trading AI tool
that's honest about its accuracy." That honesty is the product.

Everything downstream — unknowns surface, pressure test, reversibility
UI, journal — depends on having calibration data to reason about.
Don't build them first.
