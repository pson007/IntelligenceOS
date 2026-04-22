# IntelligenceOS

Personal trading-intelligence console for a single user (Phirun). A Python
FastAPI backend drives the user's real Chrome over CDP to automate
TradingView (chart capture, analysis, order entry) and claude.ai (vision
LLM analysis without an API key). Not a SaaS, not multi-tenant — one
operator, one workflow.

---

## Who the user is

**Phirun Son** — `phirun.son@gmail.com`. Day trader, builder.
- Primary market: **MNQ1!** (Micro E-mini NASDAQ-100 futures, CME).
  When working in this repo, default symbol = MNQ1! unless told otherwise.
- TradingView Pro+ subscription, claude.ai Max subscription.
- Hardware: **M3 Max MacBook Pro, 128GB RAM, macOS Tahoe 26.4.1**.
  Can comfortably run large local LLMs; prefers **local inference
  ($0/call)** where quality permits, and falls back to claude.ai web UI
  for better reasoning.
- Remote access: the console is exposed over Tailscale at
  `home.tail772848.ts.net`; he opens it from iPhone/iPad during the
  trading session.
- Working style: **terse, grounded, no speculation**. Prefers minimal
  focused changes over speculative abstractions. Verify claims before
  recommending. Don't auto-commit or push.

---

## What this project does

Day-trading deck where one chart drives everything:

1. **Capture** the chart (Playwright screenshot through a CDP-attached
   Chrome) — symbol + timeframe pills → live TV chart → PNG saved to
   `~/Desktop/TradingView/`.
2. **Analyze** via a vision LLM:
   - *Single-TF analyze* — one chart, one LLM call, returns Long/Short/
     Skip + entry/stop/tp/R:R + rationale + a Pine v6 **indicator**
     overlay.
   - *Deep analyze* — all 9 timeframes (1m→1M), one multi-image call,
     returns an **optimal TF recommendation** + bracket levels
     calibrated to that TF + a Pine v6 **strategy** (backtestable,
     not just annotation).
3. **Act** on the result — Apply-to-order copies stop/tp into a bracket
   Quick Order; Apply-pine pastes the generated script into TV's Pine
   Editor and adds it to the chart.

The whole thing attaches to the user's *real* Chrome. TradingView and
claude.ai sessions are reused — no separate profile/login state.

---

## Layout (read this first)

```
IntelligenceOS/
├── tradingview/                 # Main app
│   ├── ui_server.py             # FastAPI backend on 127.0.0.1:8788
│   ├── session.py               # Playwright CDP-attach helper
│   ├── preflight.py             # Chrome readiness check
│   ├── apply_pine.py            # Paste/save/add Pine to chart (subprocess)
│   ├── run-ui.sh                # Start uvicorn --reload
│   ├── start_chrome_cdp.sh      # Start Chrome with CDP port 9222
│   ├── ui/                      # Static HTML/CSS/JS frontend
│   ├── tv_automation/           # The automation package
│   │   ├── chart.py             # Symbol/TF navigation, screenshots
│   │   ├── analyze_mtf.py       # Single-TF + deep analysis
│   │   ├── claude_web.py        # Drive claude.ai for analysis
│   │   ├── trading.py           # Paper trading via TV order panel
│   │   ├── orders.py            # Bracket orders + order-panel
│   │   ├── watchlist.py         # Watchlist scraping/editing
│   │   ├── alerts.py            # Alert management
│   │   ├── layouts.py           # TV layout management
│   │   ├── indicators.py        # Indicator add/remove
│   │   ├── drawings.py          # Chart drawing management
│   │   ├── act.py               # Agentic multi-step TV automation
│   │   ├── screener.py          # Stock screener
│   │   ├── strategy_tester.py   # TV backtester automation
│   │   ├── pine_editor.py       # Pine Editor panel control
│   │   └── lib/                 # Shared helpers
│   │       ├── audit.py         # JSONL audit log w/ request_id ctxvar
│   │       ├── guards.py        # Login / session checks
│   │       ├── selectors.py, selectors_healer.py  # Stable TV selectors
│   │       ├── modal.py, session_modal.py          # Modal dismissal
│   │       └── retry.py, urls.py, keyboard.py, ...
│   ├── pine/generated/          # LLM-generated Pine scripts
│   ├── pine/parse_failures/     # Full raw LLM responses on parse fail
│   ├── audit/                   # Per-day JSONL audit log
│   ├── benchmarks/              # Bench scripts + stored results
│   ├── tests/smoke_ui.py        # Headless smoke test
│   ├── session/                 # Persistent Playwright profile (if launch mode)
│   └── .venv/                   # Python 3.12 venv
├── tv-worker/                   # Cloudflare Worker (TypeScript)
│   └── src/                     # Webhook ingest from TV alerts
├── tradingview-chart.sh         # Root-level helper
├── start-whisper-recording.sh   # Whisper voice capture
└── .claude/                     # Claude Code settings
```

Current branch is `main`. Commits flow directly; there's no staging
branch or release process.

---

## Running it

Two processes need to be alive:

**1. Chrome with CDP** (one-time until reboot):
```bash
cd tradingview && ./start_chrome_cdp.sh
```
Then sign into tradingview.com and claude.ai once. Sessions persist in
the Chrome profile.

**2. UI server** (development):
```bash
cd tradingview && ./run-ui.sh
```
Runs `uvicorn ui_server:app --reload` on `127.0.0.1:8788`. Edits to
`.py` files auto-restart. Edits to `ui/*.html|css|js` are live (read
per-request, no restart needed).

Logs go to stdout; when backgrounded via `nohup ./run-ui.sh > /tmp/ui_server.log 2>&1 &`,
tail that.

`.env` is the source of truth for config:
- `TV_CDP_URL=http://localhost:9222` — **set by default**; switches the
  Playwright stack into CDP-attach mode (drives user's real Chrome).
  Unset to launch a private Chromium instead (not normally used).
- `UI_TOKEN` — bearer for the UI server's CSRF gate.
- `ANTHROPIC_API_KEY` — optional, only needed for `provider=anthropic`.

---

## Analysis providers (pick carefully)

The UI exposes three providers. Each has a different trade-off profile.
Bench data lives in `tradingview/benchmarks/live_bench_results.json`.

| Provider    | Model               | Single-TF | Deep (9-TF) | Cost              | When to use                                     |
|-------------|--------------------|-----------|-------------|-------------------|-------------------------------------------------|
| `ollama`    | `gemma4:31b`       | ~85s      | ~180s       | $0                | Offline / privacy / claude quota burned         |
| `ollama`    | `gemma4:26b`       | ~55s      | ~130s       | $0                | "Fast mode" local — slight signal-quality cost  |
| `claude_web`| `Sonnet 4.6` ⭐    | ~20s      | ~60s        | Subscription      | **Default recommended — speed + quality**       |
| `claude_web`| `Haiku 4.5`        | ~15s      | ~45s        | Subscription      | Fast iteration across many symbols              |
| `claude_web`| `Opus 4.7`         | ~25s      | ~90s        | Subscription      | Hard calls — best confidence calibration        |
| `anthropic` | `claude-sonnet-4-6`| ~10s      | ~30s        | Paid (API)        | Only if `ANTHROPIC_API_KEY` is set              |

**Why claude_web exists**: the user has a Max subscription but doesn't
always have an API key configured. `claude_web` opens a new tab in the
attached Chrome, uploads the screenshot(s), types the prompt, scrapes
the response. Same $0 as the subscription, no key management.

Gemma-family models have a documented bias toward "Long 75% every time"
on trending charts — use them as a crosscheck, not a primary signal
(see the 2026-04-19 bench for details).

---

## Architectural choices (non-obvious)

- **CDP attach, not launch**: `session.tv_context()` connects to the
  existing Chrome at `localhost:9222`. Tabs we open are in *user's*
  browser. **Never call `context.close()`** — that kills the user's
  Chrome. The `async with tv_context()` context manager knows this.
- **Audit-first debugging**: every meaningful action emits to
  `tradingview/audit/YYYY-MM-DD.jsonl` with a `request_id` contextvar.
  The UI streams progress via `/api/audit/tail?request_id=...`.
  When something breaks, grep audit first.
- **Concurrency guard**: `_cdp_busy()` in `ui_server.py` blocks
  simultaneous act/analyze runs; the UI also disables conflicting
  buttons. Server returns HTTP 409 if bypassed.
- **Pine apply is a subprocess**, not an in-process call. `apply_pine.py`
  runs standalone against the same Chrome, pastes/saves/adds the script,
  then collapses the Pine Editor panel. Fire and forget.
- **Two dockings for Pine Editor**: side (`.tv-script-widget`, close
  button has `aria-label="Close"`) vs bottom (widget bar, chevron with
  `aria-label="Collapse panel"`). `close_pine_editor` handles both by
  walking up from `.pine-editor-monaco` to find whichever close button
  is an ancestor.
- **Parse failures save the full response** to `pine/parse_failures/`
  so you can re-inspect without re-running the LLM. Audit event
  `analyze.parse_fail` includes the `dump_path`.
- **Single-TF vs deep = two endpoints, one renderer**: `/api/analyze`
  and `/api/analyze/deep`. The JS renders both through the same result
  card, branching on `mode === 'deep'` for the optimal-TF badge and
  per-TF breakdown table.
- **Timeframe format mismatch is built-in**: TradingView uses `"1"`,
  `"60"`, `"D"` in URL params; the UI pills use `"1m"`, `"1h"`, `"1D"`.
  `_TIMEFRAME_MAP` in `tv_automation/chart.py` and `TV_INTERVAL_TO_PILL`
  in `ui/app.js` are the canonical translation tables — **keep them in
  sync**.
- **claude.ai smart-quote normalization**: claude.ai's markdown
  renderer turns `'` into `'` (U+2019). `_normalize_text` in
  `claude_web.py` converts them back before JSON parsing. Don't
  remove this — it's the reason parse-failures dropped to zero.

---

## Conventions

**Commits** (match the existing `git log` style):
```
area: short noun-phrase summary — em-dash subclauses if needed

One paragraph of why.

- Bullet-list specific changes.
- Use em-dashes, not ASCII `--`, for sub-clauses.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
Examples: `trade: unified deck with MTF analysis`, `ui: full-screen PWA
on iPhone 15 Pro Max`, `close blind spots 1 + 5: concurrent act guard +
GitHub Actions CI`. **Create NEW commits, never amend.** Don't push
without asking.

**Pine**: always `//@version=6`. `indicator(overlay=true)` for
annotations; `strategy(..., initial_capital=10000, commission_type=...)`
for backtests. Never write `//@version=5`.
**Before editing any `.pine` or `forecast_pine.py`, read
`tradingview/pine/pine.md`** — canonical reference for architecture, v6
gotchas, layout conventions, recipes, and the session-history of
structural edits.

**UI**: dark theme, mono font for prices. Levels show with
thousand-separator commas (`26,842`, not `26842`). R:R colored green ≥2,
amber 1–2, red <1. Per-TF table shows ★ on the optimal row.

**Python**: 3.12, async everywhere, `from __future__ import annotations`
at the top of each module. Type hints on function signatures. Prefer
`Path` over string paths, `audit.log(...)` over `print(...)`.

**JS**: no framework, vanilla. Single `ui/app.js` file. Add new
handlers near related ones, not at the bottom.

---

## How to help well

Things this user values:
- **Verify before asserting**: if you recall a function name from
  memory or prior context, grep to confirm it still exists before
  recommending it.
- **Audit log is authoritative**: prefer `tail -n 200 audit/*.jsonl`
  over assumptions about state.
- **Minimal diffs**: three similar lines > a premature helper. Don't
  build generic abstractions for hypothetical future use.
- **Ask before risky ops**: server restart, `pkill`, `git reset`,
  `rm -rf`, force-push. These aren't destructive but they are
  user-visible.
- **Local-first when quality permits**: don't route everything to
  claude.ai; the ollama path exists for a reason. But also don't
  default to ollama when the quality gap is meaningful (see bench).
- **Don't generate docs unless asked**: no READMEs, no "here's how I
  would structure this" unless requested. The exception: this file.

Things that are fine to do autonomously:
- File edits, small refactors, grep/read operations
- Running benchmarks, reading logs, probing DOM
- Kicking off a local test server for self-check

---

## Common tasks and their files

| Task                          | Entry point                           |
|-------------------------------|---------------------------------------|
| Add a new analysis provider   | `tv_automation/analyze_mtf.py` — see `_call_claude_web` as template |
| Change the TV interaction     | `tv_automation/chart.py` or the relevant sibling module |
| Adjust an LLM prompt          | `_SYSTEM_PROMPT` / `_DEEP_SYSTEM_PROMPT` in `analyze_mtf.py` |
| Add a UI control              | `ui/index.html` + handler in `ui/app.js` + CSS in `ui/style.css` |
| Add a new endpoint            | `ui_server.py` |
| Debug a selector break        | Live DOM probe via `session.tv_context` — see examples in `benchmarks/` |
| Re-benchmark providers        | `cd tradingview && .venv/bin/python benchmarks/live_bench_single_tf.py` |
| Restart server cleanly        | `pkill -f 'uvicorn ui_server'; cd tradingview && nohup ./run-ui.sh > /tmp/ui_server.log 2>&1 & disown` |

---

## Important paths

- Screenshots: `~/Desktop/TradingView/SYMBOL_TF_YYYYMMDD_HHMMSS.png`
- Generated Pine: `tradingview/pine/generated/`
- Parse failures: `tradingview/pine/parse_failures/`
- Audit log: `tradingview/audit/YYYY-MM-DD.jsonl`
- Server log (when backgrounded): `/tmp/ui_server.log`
- Latest bench results: `tradingview/benchmarks/live_bench_results.json`
