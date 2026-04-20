"""IntelligenceOS Console — local web UI for driving TradingView automation.

Run:
    cd tradingview
    .venv/bin/uvicorn ui_server:app --host 127.0.0.1 --port 8788 --reload

Then open http://127.0.0.1:8788 in your browser.

The server imports the `tv_automation` package directly and calls its
async entry points (chart/trading/watchlist/alerts/act). It does NOT go
through the HMAC-signed webhook path — localhost binding is the trust
boundary, same as `bridge.py`'s existing posture.

Coexistence with bridge.py:
  * CDP-attach mode (TV_CDP_URL set): both servers can run concurrently.
    Each call just opens a brief CDP connection against the user's
    already-running Chrome.
  * Launch mode: only ONE process at a time can hold the persistent
    Chromium profile — don't run both servers.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from tv_automation import alerts as alerts_mod
from tv_automation import act as act_mod
from tv_automation import analyze_mtf as analyze_mtf_mod
from tv_automation import chart as chart_mod
from tv_automation import decision_log as decision_log_mod
from tv_automation import orders as orders_mod
from tv_automation import reconcile as reconcile_mod
from tv_automation import trading as trading_mod
from tv_automation import watchlist as watchlist_mod
from tv_automation.lib import audit

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: prune screenshots older than _SCREENSHOT_TTL_DAYS. Cheap,
    # runs once per process start. No shutdown cleanup needed — the ASGI
    # app doesn't own any long-lived resources (browser attaches are
    # per-request).
    _prune_old_screenshots()
    yield


app = FastAPI(title="IntelligenceOS Console", lifespan=lifespan)

_UI_DIR = Path(__file__).parent / "ui"
_AUDIT_DIR = Path(__file__).parent / "audit"
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView").resolve()

# Optional shared-secret token. When set in .env as UI_TOKEN=..., every
# /api/* request must carry X-UI-Token: <same value>. Localhost-only
# binding is usually enough, but on a shared workstation set this too.
_UI_TOKEN = os.getenv("UI_TOKEN", "").strip()


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def guard(request: Request, call_next):
    """CSRF + shared-secret guard on /api/* routes.

    * Any non-GET request must carry `X-UI: 1`. A malicious site you
      visit in the same browser cannot set custom headers cross-origin
      without triggering a CORS preflight — which we never respond to
      with Access-Control-Allow-*, so the attack fails.
    * If UI_TOKEN is set in .env, non-loopback /api/* requests (GET and
      POST) must match `X-UI-Token`. Constant-time compare.
    * Loopback requests (127.0.0.1 / ::1) are trusted — the socket is
      already a trust boundary and requiring the token doubles the
      friction on every local dev session for zero security gain.
      Tailscale Serve preserves the original client IP (100.x.x.x) so
      remote requests still fall through the strict path.
    * Non-/api/* (HTML, static assets) is unrestricted.
    """
    path = request.url.path
    if path.startswith("/api/"):
        if request.method != "GET":
            if request.headers.get("X-UI") != "1":
                return JSONResponse({"detail": "CSRF: missing X-UI header"}, status_code=403)
        if _UI_TOKEN:
            client_host = (request.client.host if request.client else "") or ""
            if client_host not in _LOOPBACK_HOSTS:
                sent = request.headers.get("X-UI-Token") or ""
                if not secrets.compare_digest(sent, _UI_TOKEN):
                    return JSONResponse({"detail": "auth: bad or missing X-UI-Token"}, status_code=401)
    return await call_next(request)

# In-memory registry of background act() runs. Keyed by task_id; state
# is "running" / "done" / "failed". Kept simple — no persistence, dies
# with the process. Bounded by TTL (_ACT_TASK_TTL_S) so long-running
# servers don't accumulate stale entries.
_act_tasks: dict[str, dict] = {}
_ACT_TASK_TTL_S = 60 * 60  # 1 hour

# At most one act run at a time — they all share the same Playwright
# session, so concurrent runs would interleave clicks unpredictably.
# Tracks the task_id of the currently-running act (or None if idle).
# A second /api/act call while this is set returns 409 Conflict.
_active_act_task: str | None = None

# Multi-timeframe analysis tasks share the same CDP session as act, so
# the two must be mutually exclusive. Separate registry (different result
# shape), shared conflict check via _cdp_busy().
_analyze_tasks: dict[str, dict] = {}
_active_analyze_task: str | None = None


def _prune_act_tasks() -> None:
    """Remove finished tasks older than TTL. Called opportunistically on
    each new run rather than via a background sweeper — keeps footprint
    proportional to activity."""
    cutoff = time.time() - _ACT_TASK_TTL_S
    stale = [tid for tid, t in _act_tasks.items()
             if t.get("finished_at") and t["finished_at"] < cutoff]
    for tid in stale:
        _act_tasks.pop(tid, None)
    stale_a = [tid for tid, t in _analyze_tasks.items()
               if t.get("finished_at") and t["finished_at"] < cutoff]
    for tid in stale_a:
        _analyze_tasks.pop(tid, None)


def _cdp_busy() -> dict | None:
    """Return info about any in-flight act or analyze run, or None if idle.
    Both hold the single CDP session exclusively; used to 409 concurrent
    starts regardless of which endpoint the conflicting run came from."""
    if _active_act_task and _active_act_task in _act_tasks:
        t = _act_tasks[_active_act_task]
        if t.get("state") == "running":
            return {"kind": "act", "task_id": _active_act_task,
                    "started_at": t.get("started_at"), "goal": t.get("goal")}
    if _active_analyze_task and _active_analyze_task in _analyze_tasks:
        t = _analyze_tasks[_active_analyze_task]
        if t.get("state") == "running":
            return {"kind": "analyze", "task_id": _active_analyze_task,
                    "started_at": t.get("started_at"),
                    "symbol": t.get("symbol")}
    return None


# Screenshot cleanup — chart.screenshot() writes PNGs to ~/Desktop/TradingView/
# every capture. Left alone they accumulate indefinitely. On startup we
# delete anything older than _SCREENSHOT_TTL_DAYS.
_SCREENSHOT_TTL_DAYS = 14


def _prune_old_screenshots() -> None:
    if not _SCREENSHOT_ROOT.exists():
        return
    cutoff = time.time() - _SCREENSHOT_TTL_DAYS * 86400
    removed = 0
    for p in _SCREENSHOT_ROOT.glob("*.png"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        audit.log("ui_server.screenshot_prune",
                  removed=removed, ttl_days=_SCREENSHOT_TTL_DAYS)




# ---------------------------------------------------------------------------
# Static UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((_UI_DIR / "index.html").read_text())


# Serve /ui/* static assets (style.css, app.js) directly from disk.
# Files here are read fresh each request — no bundler / build step.
app.mount("/ui", StaticFiles(directory=str(_UI_DIR)), name="ui")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


# Browser-health probe. Cached for 30s so a noisy UI polling this
# doesn't hammer the CDP endpoint. Returns degraded state (ok=false)
# whenever tv_context() fails to attach or there's no chart page.
_browser_health = {"ok": None, "at": 0.0, "err": None, "url": None}


async def _probe_browser() -> dict:
    try:
        from session import tv_context as _tv_context
        async with _tv_context() as ctx:
            pages = ctx.pages
            tv = next((p for p in pages if "tradingview.com" in (p.url or "")), None)
            return {"ok": True, "url": tv.url if tv else None}
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}


@app.get("/api/health/browser")
async def health_browser(force: bool = False) -> dict:
    now = time.time()
    if force or now - _browser_health["at"] > 30:
        result = await _probe_browser()
        _browser_health.update({"at": now, **result})
    # Never return the internal 'at' as a float — UI wants iso time.
    return {
        "ok": _browser_health.get("ok"),
        "err": _browser_health.get("err"),
        "url": _browser_health.get("url"),
        "checked_at": _browser_health["at"],
    }


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

@app.get("/api/chart/metadata")
async def chart_metadata() -> dict:
    try:
        return await chart_mod.metadata()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/chart/set-symbol")
async def chart_set_symbol(payload: dict) -> dict:
    symbol = (payload or {}).get("symbol", "").strip()
    if not symbol:
        raise HTTPException(400, "symbol required")
    interval = (payload or {}).get("interval") or None
    try:
        return await chart_mod.set_symbol(symbol, interval)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/chart/screenshot")
async def chart_screenshot(payload: dict | None = None) -> dict:
    payload = payload or {}
    area = payload.get("area", "chart")
    symbol = payload.get("symbol") or None
    interval = payload.get("interval") or None
    try:
        result = await chart_mod.screenshot(symbol, interval, None, area=area)
    except Exception as e:
        raise HTTPException(500, str(e))

    # Inline the PNG as a data: URI so the UI's <img> renders it without
    # a second authed request. Native <img src="…"> loads don't carry the
    # X-UI-Token header, so serving via /api/chart/image would 401 on
    # every request once auth is enabled. Size cost: base64 inflates
    # ~33% (typical 300KB PNG → 400KB JSON), negligible over localhost
    # or tailnet.
    import base64
    try:
        png_bytes = Path(result["path"]).read_bytes()
        result["data_url"] = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        result["size_bytes"] = len(png_bytes)
    except Exception as e:
        # Non-fatal — older clients can still fall back to the URL path.
        result["data_url"] = None
        result["data_url_error"] = f"{type(e).__name__}: {e}"

    # Keep a plain URL for curl / direct inspection. Still auth-gated.
    result["url"] = f"/api/chart/image?path={result['path']}&t={int(time.time())}"
    return result


@app.get("/api/chart/image")
async def chart_image(path: str):
    """Serve a screenshot PNG — restricted to the TradingView screenshot
    root so path traversal can't expose arbitrary files."""
    try:
        resolved = Path(path).resolve()
    except Exception:
        raise HTTPException(400, "invalid path")
    if not str(resolved).startswith(str(_SCREENSHOT_ROOT)):
        raise HTTPException(403, "path outside allowed root")
    if not resolved.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(resolved), media_type="image/png")


# ---------------------------------------------------------------------------
# Act — vision loop. Runs in background so the UI can poll audit for progress.
# ---------------------------------------------------------------------------

@app.post("/api/act")
async def act_start(payload: dict) -> dict:
    global _active_act_task
    goal = (payload or {}).get("goal", "").strip()
    if not goal:
        raise HTTPException(400, "goal required")

    # Refuse if another CDP-holding run is in flight (act OR analyze).
    # They share a single Playwright session; concurrent runs interleave
    # clicks / chart navigations unpredictably.
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()

    # Set the contextvar BEFORE creating the task — asyncio.create_task
    # copies the current context, so the background runner inherits it
    # and all audit.log() calls inside act() carry this request_id.
    audit.current_request_id.set(request_id)

    _act_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "goal": goal,
    }

    async def runner():
        global _active_act_task
        try:
            result = await act_mod.act(
                goal,
                # Local-first default — no API key required out of the
                # box. Pass provider='anthropic' explicitly to use Claude.
                provider=payload.get("provider", "ollama"),
                model=payload.get("model") or None,
                base_url=payload.get("base_url") or None,
                max_steps=int(payload.get("max_steps", 10)),
                max_cost_usd=float(payload.get("max_cost_usd", 0.50)),
                text_only=bool(payload.get("text_only", False)),
                vision=bool(payload.get("vision", False)),
                read_only=bool(payload.get("read_only", False)),
                dry_run=bool(payload.get("dry_run", False)),
            )
            _act_tasks[task_id]["state"] = "done"
            _act_tasks[task_id]["result"] = result
        except Exception as e:
            _act_tasks[task_id]["state"] = "failed"
            _act_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _act_tasks[task_id]["finished_at"] = time.time()
            # Release the single-runner slot. If a new run somehow grabbed
            # it under us (shouldn't be possible given the check at start),
            # don't step on it.
            if _active_act_task == task_id:
                _active_act_task = None

    _active_act_task = task_id
    asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.get("/api/act/{task_id}")
async def act_status(task_id: str) -> dict:
    t = _act_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task_id")
    # Never return the asyncio.Task object — it doesn't serialize.
    return {k: v for k, v in t.items() if not callable(v)}


# ---------------------------------------------------------------------------
# Single-timeframe analysis — captures the chart at the user-selected TF,
# runs one vision-LLM call, returns a trade recommendation + saved Pine
# script. Task-based (like /api/act) because a full run is ~30-60s.
# ---------------------------------------------------------------------------

@app.post("/api/analyze")
async def analyze_start(payload: dict) -> dict:
    global _active_analyze_task
    p = payload or {}
    symbol = (p.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(400, "symbol required")
    timeframe = (p.get("timeframe") or "").strip() or None

    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()

    # Same contextvar pattern as /api/act — the background runner inherits
    # the request_id so all audit events from analyze_mtf.* carry it and
    # the UI can stream progress via /api/audit/tail?request_id=...
    audit.current_request_id.set(request_id)

    _analyze_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "symbol": symbol,
        "timeframe": timeframe,
    }

    async def runner():
        global _active_analyze_task
        try:
            kwargs = {
                # Local-first default — no API key or per-call cost. Pass
                # provider="anthropic" explicitly to opt into Claude.
                "provider": p.get("provider", "ollama"),
                "model": p.get("model") or None,
                "base_url": p.get("base_url") or None,
            }
            if timeframe:
                kwargs["timeframe"] = timeframe
            result = await analyze_mtf_mod.analyze_chart(symbol, **kwargs)
            _analyze_tasks[task_id]["state"] = "done"
            _analyze_tasks[task_id]["result"] = result
        except asyncio.CancelledError:
            _analyze_tasks[task_id]["state"] = "cancelled"
            raise
        except Exception as e:
            _analyze_tasks[task_id]["state"] = "failed"
            _analyze_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _analyze_tasks[task_id]["finished_at"] = time.time()
            if _active_analyze_task == task_id:
                _active_analyze_task = None

    _active_analyze_task = task_id
    _analyze_tasks[task_id]["_task"] = asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


# Deep multi-TF analysis — captures 10 TFs and produces an integrated
# signal + optimal-TF recommendation + Pine strategy script. Same task
# shape as /api/analyze so the UI can use the same polling loop; the
# result dict carries `mode: "deep"` + `optimal_tf` + `per_tf[]` for
# renderer-side branching.
@app.post("/api/analyze/deep")
async def analyze_deep_start(payload: dict) -> dict:
    global _active_analyze_task
    p = payload or {}
    symbol = (p.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(400, "symbol required")

    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _analyze_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "symbol": symbol,
        "mode": "deep",
    }

    async def runner():
        global _active_analyze_task
        try:
            result = await analyze_mtf_mod.analyze_deep(
                symbol,
                # claude_web default — bench confirmed it beats Gemma on
                # multi-image reasoning and the 9-image upload is a single
                # message against the subscription.
                provider=p.get("provider", "claude_web"),
                model=p.get("model") or None,
                base_url=p.get("base_url") or None,
            )
            _analyze_tasks[task_id]["state"] = "done"
            _analyze_tasks[task_id]["result"] = result
        except asyncio.CancelledError:
            _analyze_tasks[task_id]["state"] = "cancelled"
            raise
        except Exception as e:
            _analyze_tasks[task_id]["state"] = "failed"
            _analyze_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _analyze_tasks[task_id]["finished_at"] = time.time()
            if _active_analyze_task == task_id:
                _active_analyze_task = None

    _active_analyze_task = task_id
    _analyze_tasks[task_id]["_task"] = asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


# Multi-provider pressure test — captures once, runs the same chart
# through 2-3 providers, returns per-provider results + a consensus
# summary. Task-based because 3 sequential LLM calls take 60-130s.
@app.post("/api/analyze/pressure-test")
async def pressure_test_start(payload: dict) -> dict:
    global _active_analyze_task
    p = payload or {}
    symbol = (p.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(400, "symbol required")
    timeframe = (p.get("timeframe") or "").strip() or None
    combos = p.get("combos") or None

    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _analyze_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "symbol": symbol,
        "mode": "pressure_test",
    }

    async def runner():
        global _active_analyze_task
        try:
            kwargs = {"combos": combos, "base_url": p.get("base_url") or None}
            if timeframe:
                kwargs["timeframe"] = timeframe
            result = await analyze_mtf_mod.pressure_test(symbol, **kwargs)
            result["mode"] = "pressure_test"  # UI uses this to branch render
            _analyze_tasks[task_id]["state"] = "done"
            _analyze_tasks[task_id]["result"] = result
        except asyncio.CancelledError:
            _analyze_tasks[task_id]["state"] = "cancelled"
            raise
        except Exception as e:
            _analyze_tasks[task_id]["state"] = "failed"
            _analyze_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _analyze_tasks[task_id]["finished_at"] = time.time()
            if _active_analyze_task == task_id:
                _active_analyze_task = None

    _active_analyze_task = task_id
    _analyze_tasks[task_id]["_task"] = asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.get("/api/analyze/{task_id}")
async def analyze_status(task_id: str) -> dict:
    t = _analyze_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task_id")
    # Filter private `_`-prefixed fields (e.g. the asyncio.Task handle we
    # stash for cancellation) — they aren't JSON-serializable.
    return {k: v for k, v in t.items() if not k.startswith("_")}


# Cancel a running analyze task. Sets state="cancelled" via CancelledError
# bubbling through the runner. Idempotent — calling on an already-finished
# task is a no-op that returns the current state. The CDP session is
# released by the runner's `finally:` block as part of the unwind.
@app.post("/api/analyze/{task_id}/cancel")
async def analyze_cancel(task_id: str) -> dict:
    t = _analyze_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task_id")
    state = t.get("state")
    if state != "running":
        return {"task_id": task_id, "state": state, "cancelled": False}
    task = t.get("_task")
    if task is not None and not task.done():
        task.cancel()
    audit.log("analyze.cancel_requested",
              task_id=task_id, request_id=t.get("request_id"),
              symbol=t.get("symbol"), mode=t.get("mode"))
    return {"task_id": task_id, "state": "cancelling", "cancelled": True}


# Decision log endpoints — minimal surface for a future journal/
# calibration UI. The CLI at `.venv/bin/python -m tv_automation.reconcile`
# is the primary reconciliation tool for now; these endpoints exist so
# the browser can do the same work when the journal UI ships.

@app.get("/api/decisions/recent")
async def decisions_recent(limit: int = 50) -> dict:
    """Recent decisions — newest first. For a journal view."""
    return {"decisions": decision_log_mod.recent(limit=max(1, min(limit, 500)))}


@app.get("/api/decisions/unreconciled")
async def decisions_unreconciled(limit: int = 50) -> dict:
    """Decisions without an outcome tagged — oldest first (matches the
    CLI's chronological walk)."""
    return {"decisions": decision_log_mod.unreconciled(
        limit=max(1, min(limit, 500)),
    )}


@app.post("/api/decisions/learning/{request_id}")
async def decisions_learning(request_id: str, payload: dict) -> dict:
    """Save/clear a learning note on a decision. Empty string clears.
    Capped at 500 chars — a reflection over that is a journal entry,
    not a one-line lesson; belongs in a separate doc."""
    note = (payload or {}).get("note") or ""
    if len(note) > 500:
        raise HTTPException(400, "note too long (max 500 chars)")
    ok = decision_log_mod.set_learning_note(request_id, note)
    if not ok:
        raise HTTPException(404, "unknown request_id")
    return {"ok": True, "request_id": request_id, "note_len": len(note.strip())}


@app.post("/api/decisions/reconcile/{request_id}")
async def decisions_reconcile(request_id: str, payload: dict) -> dict:
    """Tag an outcome on a specific decision. `payload` is
    `{outcome: str, realized_r: number | null}`. Validates the outcome
    string against the CLI's taxonomy so a typo can't corrupt the DB."""
    p = payload or {}
    outcome = (p.get("outcome") or "").strip()
    valid = {"hit_tp", "hit_stop", "manual_close", "expired", "no_fill",
             "skip_right", "skip_wrong"}
    if outcome not in valid:
        raise HTTPException(400, f"invalid outcome; valid: {sorted(valid)}")
    realized_r = p.get("realized_r")
    if realized_r is not None:
        try:
            realized_r = float(realized_r)
        except (TypeError, ValueError):
            raise HTTPException(400, "realized_r must be a number or null")
    ok = decision_log_mod.set_outcome(request_id, outcome, realized_r)
    if not ok:
        raise HTTPException(404, "unknown request_id")
    return {"ok": True, "request_id": request_id, "outcome": outcome,
            "realized_r": realized_r}


@app.get("/api/decisions/calibration")
async def decisions_calibration() -> dict:
    """Per-provider accuracy bucketed by confidence. The data that
    backs the eventual inline "Opus track: 65% @ 70%+" chip."""
    return {"summary": decision_log_mod.calibration_summary()}


@app.get("/api/decisions/export.csv")
async def decisions_export_csv():
    """Full decision log as CSV — for taxes, external analysis, backup.
    Single flat row-per-decision with all fields. RFC 4180 quoting via
    the stdlib csv module, so rationales/notes containing commas or
    quotes round-trip cleanly into Excel/Numbers/Sheets.

    No filtering by design — if a user wants a subset, they can filter
    in their spreadsheet tool. A single complete export is a cleaner
    contract than N flavors of partial export.

    NOTE: return-type annotation omitted on purpose — FastAPI evaluates
    annotations at route-registration time (before any function-body
    imports run), so `-> "Response"` triggers a `PydanticUndefinedAnnotation`
    error if `Response` isn't in module scope at registration.
    """
    import csv
    import io
    from fastapi.responses import Response

    rows = decision_log_mod.recent(limit=100_000)  # effectively all
    buf = io.StringIO()
    # Column order chosen for human readability when opened in a
    # spreadsheet: identity → decision data → outcome → meta.
    cols = [
        "iso_ts", "request_id", "symbol", "mode", "tf", "optimal_tf",
        "provider", "model", "signal", "confidence",
        "entry", "stop", "tp", "rationale",
        "outcome", "realized_r", "closed_at", "learning_note",
        "pine_path", "cost_usd", "elapsed_s", "llm_elapsed_s",
        "usage_in", "usage_out", "ts",
    ]
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

    # Filename includes a date so repeated exports don't overwrite.
    fname = f"intelligenceos-decisions-{time.strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            # Small but real: some spreadsheet tools need this hint
            # to respect UTF-8 without a BOM.
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


@app.get("/api/decisions/rollup")
async def decisions_rollup(days: int = 7) -> dict:
    """N-day rollup for the Journal's weekly review panel. Includes a
    prior-period comparison (e.g. last 7 days vs. the 7 days before
    that) so drift is visible."""
    return decision_log_mod.rollup_summary(days=max(1, min(days, 90)))


@app.get("/api/decisions/session")
async def decisions_session() -> dict:
    """Today's rollup: total, reconciled, wins/losses, running R.
    Default window is start-of-local-day so "today" matches how the
    user thinks about their trading session. Polled by the Trade tab's
    session strip on every tab-enter + after every reconcile."""
    return decision_log_mod.session_summary()


@app.post("/api/analyze/apply-pine")
async def analyze_apply_pine(payload: dict) -> dict:
    """Apply a previously-generated pine script to the TradingView chart.

    Reuses the existing apply_pine.py orchestration — paste into Pine
    Editor → save → add to chart. Path must be inside the repo's
    `pine/generated/` directory, never an arbitrary file.
    """
    p = payload or {}
    path = (p.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "path required")

    pine_root = Path(__file__).parent / "pine" / "generated"
    try:
        resolved = Path(path).resolve()
    except Exception:
        raise HTTPException(400, "invalid path")
    if not str(resolved).startswith(str(pine_root.resolve())):
        raise HTTPException(403, "path outside allowed pine root")
    if not resolved.exists():
        raise HTTPException(404, "pine file not found")

    # Import lazily — apply_pine module lives at top-level, not under
    # tv_automation, and does Playwright UI work we'd rather only pay
    # for when actually applying.
    import subprocess
    apply_script = Path(__file__).parent / "apply_pine.py"
    venv_python = Path(__file__).parent / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else "python"
    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe, str(apply_script), str(resolved),
            cwd=str(Path(__file__).parent),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        ok = proc.returncode == 0
        return {
            "ok": ok, "path": str(resolved),
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[-2000:],
            "stderr": stderr.decode("utf-8", errors="replace")[-2000:],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "path": str(resolved), "error": "apply_pine timeout (120s)"}
    except Exception as e:
        raise HTTPException(500, f"apply_pine failed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------

@app.post("/api/trade/order")
async def trade_order(payload: dict) -> dict:
    p = payload or {}
    symbol = p.get("symbol", "").strip()
    side = p.get("side", "").strip().lower()
    qty = int(p.get("qty", 0))
    dry_run = bool(p.get("dry_run", False))
    # Optional bracket prices — when either is supplied we route through the
    # order panel (orders.place_market) which supports TP/SL. Plain markets
    # stay on the faster inline quick-trade bar (trading.place_order).
    tp = p.get("take_profit")
    sl = p.get("stop_loss")
    if not symbol or side not in ("buy", "sell") or qty <= 0:
        raise HTTPException(400, "symbol, side=buy|sell, qty>0 required")
    try:
        if tp is not None or sl is not None:
            return await orders_mod.place_market(
                symbol=symbol, side=side, qty=qty,
                take_profit=float(tp) if tp is not None else None,
                stop_loss=float(sl) if sl is not None else None,
                dry_run=dry_run,
            )
        return await trading_mod.place_order(
            symbol=symbol, side=side, qty=qty, dry_run=dry_run,
        )
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.post("/api/trade/close")
async def trade_close(payload: dict) -> dict:
    symbol = (payload or {}).get("symbol", "").strip()
    dry_run = bool((payload or {}).get("dry_run", False))
    if not symbol:
        raise HTTPException(400, "symbol required")
    try:
        return await trading_mod.close_position(symbol, dry_run=dry_run)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.post("/api/trade/flatten")
async def trade_flatten(payload: dict | None = None) -> dict:
    """Close every open position, one at a time.

    Sequential (not parallel) because close_position() drives the TV DOM
    and only one CDP session can interact with the paper-trading panel at
    a time. Errors on a single symbol don't abort the sweep — they're
    collected into `failed` so the UI can surface partial progress.
    """
    dry_run = bool((payload or {}).get("dry_run", False))
    try:
        pos = await trading_mod.positions()
    except Exception as e:
        raise HTTPException(500, f"positions: {type(e).__name__}: {e}")
    symbols: list[str] = []
    for row in (pos.get("positions") or []):
        s = (row.get("symbol") or "").replace("\n", " ").strip()
        if s:
            symbols.append(s)
    closed: list[dict] = []
    failed: list[dict] = []
    for sym in symbols:
        try:
            r = await trading_mod.close_position(sym, dry_run=dry_run)
            closed.append({"symbol": sym, "result": r})
        except Exception as e:
            failed.append({"symbol": sym, "error": f"{type(e).__name__}: {e}"})
    return {
        "total": len(symbols), "closed": len(closed), "failed": len(failed),
        "symbols": symbols, "results": closed, "errors": failed,
        "dry_run": dry_run,
    }


@app.get("/api/trade/positions")
async def trade_positions() -> dict:
    # trading.positions() returns {positions, empty, headers} — pass through.
    try:
        return await trading_mod.positions()
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

@app.get("/api/watchlist")
async def watchlist_get() -> dict:
    try:
        current = await watchlist_mod.current()
        contents = await watchlist_mod.contents()
        return {"current": current, "contents": contents}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/watchlist/add")
async def watchlist_add(payload: dict) -> dict:
    symbol = (payload or {}).get("symbol", "").strip()
    if not symbol:
        raise HTTPException(400, "symbol required")
    try:
        return await watchlist_mod.add_symbol(symbol)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/watchlist/remove")
async def watchlist_remove(payload: dict) -> dict:
    symbol = (payload or {}).get("symbol", "").strip()
    if not symbol:
        raise HTTPException(400, "symbol required")
    try:
        return await watchlist_mod.remove_symbol(symbol)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/watchlist/lists")
async def watchlist_lists() -> dict:
    try:
        return await watchlist_mod.list_lists()
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@app.get("/api/alerts")
async def alerts_list() -> dict:
    try:
        return await alerts_mod.list_alerts()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/alerts/pause")
async def alerts_pause(payload: dict) -> dict:
    identifier = str((payload or {}).get("id", "")).strip()
    if not identifier:
        raise HTTPException(400, "id required")
    try:
        return await alerts_mod.pause_alert(identifier)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/alerts/resume")
async def alerts_resume(payload: dict) -> dict:
    identifier = str((payload or {}).get("id", "")).strip()
    if not identifier:
        raise HTTPException(400, "id required")
    try:
        return await alerts_mod.resume_alert(identifier)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/alerts/create")
async def alerts_create(payload: dict) -> dict:
    p = payload or {}
    symbol = str(p.get("symbol", "")).strip()
    op = str(p.get("op", "")).strip()
    value_raw = p.get("value")
    if not symbol or not op or value_raw in (None, ""):
        raise HTTPException(400, "symbol, op, value required")
    try:
        value = float(value_raw)
    except (TypeError, ValueError):
        raise HTTPException(400, f"value must be numeric, got {value_raw!r}")
    try:
        return await alerts_mod.create_price_alert(
            symbol, op, value,
            message=(p.get("message") or None),
            webhook_url=(p.get("webhook_url") or None),
            name=(p.get("name") or None),
            trigger=(p.get("trigger") or "once-only"),
            notify_app=bool(p.get("notify_app", False)),
            notify_toast=bool(p.get("notify_toast", False)),
            notify_email=bool(p.get("notify_email", False)),
            notify_sound=bool(p.get("notify_sound", False)),
            dry_run=bool(p.get("dry_run", False)),
        )
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.post("/api/alerts/delete")
async def alerts_delete(payload: dict) -> dict:
    p = payload or {}
    identifier = str(p.get("id", "")).strip()
    dry_run = bool(p.get("dry_run", False))
    if not identifier:
        raise HTTPException(400, "id required")
    try:
        return await alerts_mod.delete_alert(identifier, dry_run=dry_run)
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Audit tail — powers live-progress display in the UI
# ---------------------------------------------------------------------------

@app.get("/api/audit/tail")
async def audit_tail(
    n: int = 50,
    request_id: str | None = None,
    event_prefix: str | None = None,
) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    f = _AUDIT_DIR / f"{today}.jsonl"
    if not f.exists():
        return {"entries": []}
    # Cap scan at last 2000 lines — each entry ~200 bytes, keeps I/O bounded.
    raw = f.read_text().splitlines()[-2000:]
    entries: list[dict] = []
    for line in raw:
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if request_id and entry.get("request_id") != request_id:
            continue
        if event_prefix and not entry.get("event", "").startswith(event_prefix):
            continue
        entries.append(entry)
    return {"entries": entries[-n:]}
