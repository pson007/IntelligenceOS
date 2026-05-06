"""1runOS — local web UI for driving TradingView automation.

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
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv()

from tv_automation import alerts as alerts_mod
from tv_automation import act as act_mod
from tv_automation import analyze_mtf as analyze_mtf_mod
from tv_automation import chart as chart_mod
from tv_automation import decision_log as decision_log_mod
from tv_automation import layouts as layouts_mod
from tv_automation import orders as orders_mod
from tv_automation import reconcile as reconcile_mod
from tv_automation import trading as trading_mod
from tv_automation import watchlist as watchlist_mod
from tv_automation.lib import audit
from tv_automation.lib.errors import NotLoggedInError

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: prune screenshots older than _SCREENSHOT_TTL_DAYS. Cheap,
    # runs once per process start. No shutdown cleanup needed — the ASGI
    # app doesn't own any long-lived resources (browser attaches are
    # per-request).
    _prune_old_screenshots()
    yield


app = FastAPI(title="1runOS", lifespan=lifespan)

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


# Patterns Playwright/anyio raise when an `async with` block is cancelled
# mid-flight and the cleanup tries to close a transport that's already
# torn down. These reach `except Exception` instead of `CancelledError`
# because the cancellation propagated through a context-manager exit.
# Reclassify so the UI shows "cancelled" instead of a scary RuntimeError.
_CANCEL_RECLASSIFY_PATTERNS = (
    "WriteUnixTransport closed",
    "the handler is closed",
    "Browser.close",
    "Connection closed while reading",
)


def _is_cancellation_artifact(exc: BaseException) -> bool:
    """True if `exc` looks like a Playwright transport-tear-down raised
    during an in-flight cancellation. Used by analyze runners to map
    these back to "cancelled" state instead of "failed"."""
    msg = str(exc)
    if any(p in msg for p in _CANCEL_RECLASSIFY_PATTERNS):
        return True
    try:
        cur = asyncio.current_task()
        if cur is not None and cur.cancelling():
            return True
    except Exception:
        pass
    return False

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

# Daily-profile range runs (see tv_automation/daily_profile.py). Each run
# can span multiple trading days; it drives the same CDP session as act /
# analyze, so all three are mutually exclusive via _cdp_busy().
_profile_run_tasks: dict[str, dict] = {}
_active_profile_run: str | None = None

# Daily-forecast runs (see tv_automation/daily_forecast.py). Single day per
# run (F1 → F2 → F3 → reconciliation); ~15-20 min wall clock. Same CDP
# exclusivity as the other three.
_forecast_run_tasks: dict[str, dict] = {}
_active_forecast_run: str | None = None


def _prune_act_tasks() -> None:
    """Remove finished tasks older than TTL. Called opportunistically on
    each new run rather than via a background sweeper — keeps footprint
    proportional to activity."""
    cutoff = time.time() - _ACT_TASK_TTL_S
    for reg in (_act_tasks, _analyze_tasks, _profile_run_tasks, _forecast_run_tasks):
        stale = [tid for tid, t in reg.items()
                 if t.get("finished_at") and t["finished_at"] < cutoff]
        for tid in stale:
            reg.pop(tid, None)


# ---------------------------------------------------------------------------
# Kill-switch — single file flag at state/paused.json. Presence ⇒ paused.
# Every long-running endpoint calls _check_not_paused() before _cdp_busy()
# so a paused workspace 503's new starts without affecting in-flight runs.
# ---------------------------------------------------------------------------

_STATE_DIR = (Path(__file__).parent / "state").resolve()
_PAUSED_FLAG = _STATE_DIR / "paused.json"


def _read_paused_state() -> dict | None:
    """Return the paused-state payload {since, reason} when the flag file
    exists, else None. Tolerant of malformed JSON — a stray empty file
    still counts as paused (fail-closed)."""
    if not _PAUSED_FLAG.exists():
        return None
    try:
        data = json.loads(_PAUSED_FLAG.read_text() or "{}")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "since": data.get("since"),
        "reason": data.get("reason") or "",
    }


def _check_not_paused() -> None:
    """Raise 503 if the kill-switch is engaged. Call at the top of every
    endpoint that kicks off a CDP-bound or long-running workflow."""
    state = _read_paused_state()
    if state is not None:
        raise HTTPException(503, {"detail": "kill-switch engaged", **state})


def _cdp_busy() -> dict | None:
    """Return info about any in-flight act / analyze / profile run, or None
    if idle. All three hold the single CDP session exclusively; used to 409
    concurrent starts regardless of which endpoint the conflicting run came
    from."""
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
    if _active_profile_run and _active_profile_run in _profile_run_tasks:
        t = _profile_run_tasks[_active_profile_run]
        if t.get("state") == "running":
            return {"kind": "profile_run", "task_id": _active_profile_run,
                    "started_at": t.get("started_at"),
                    "start": t.get("start"), "end": t.get("end")}
    if _active_forecast_run and _active_forecast_run in _forecast_run_tasks:
        t = _forecast_run_tasks[_active_forecast_run]
        if t.get("state") == "running":
            return {"kind": "forecast_run", "task_id": _active_forecast_run,
                    "started_at": t.get("started_at"),
                    "date": t.get("date"), "symbol": t.get("symbol")}
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

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((_UI_DIR / "index.html").read_text(), headers=_NO_CACHE_HEADERS)


# Serve /ui/* static assets (style.css, app.js) directly from disk.
# Single-user dev console — any caching just gets in the way when we
# iterate on app.js / style.css, so force revalidation on every hit.
@app.get("/ui/{filename:path}")
async def ui_static(filename: str):
    # Bare /ui/ (or /ui//foo etc.) → serve index.html. Common when the
    # PWA is bookmarked at /ui/ instead of /ui/index.html.
    if not filename or filename in ("", "/"):
        return HTMLResponse(
            (_UI_DIR / "index.html").read_text(), headers=_NO_CACHE_HEADERS,
        )
    path = (_UI_DIR / filename).resolve()
    if not str(path).startswith(str(_UI_DIR)) or not path.is_file():
        raise HTTPException(404, "not found")
    mt = {
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".png": "image/png",
        ".svg": "image/svg+xml",
    }.get(path.suffix, "application/octet-stream")
    return FileResponse(str(path), media_type=mt, headers=_NO_CACHE_HEADERS)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


# Kill-switch admin endpoints — pause/resume the workspace from one place.
# `state` is GET so the UI can poll it cheaply without the CSRF gate.
@app.get("/api/admin/state")
async def admin_state() -> dict:
    """Return current pause state for UI polling."""
    p = _read_paused_state()
    return {"paused": p is not None, "state": p}


@app.post("/api/admin/pause")
async def admin_pause(payload: dict | None = None) -> dict:
    """Engage the kill-switch. Writes state/paused.json — every endpoint
    that runs a CDP-bound or long-running workflow will 503 until resumed.
    In-flight runs are NOT cancelled; they finish naturally."""
    p = payload or {}
    reason = (p.get("reason") or "").strip()
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "reason": reason,
    }
    _PAUSED_FLAG.write_text(json.dumps(state, indent=2))
    audit.log("admin.paused", **state)
    return {"ok": True, "paused": True, "state": state}


@app.post("/api/admin/resume")
async def admin_resume() -> dict:
    """Release the kill-switch."""
    existed = _PAUSED_FLAG.exists()
    if existed:
        try:
            _PAUSED_FLAG.unlink()
        except OSError as e:
            raise HTTPException(500, f"failed to clear paused flag: {e}")
    audit.log("admin.resumed", was_paused=existed)
    return {"ok": True, "paused": False, "was_paused": existed}


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
            return {"ok": True, "url": tv.url if tv else None, "err": None}
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}", "url": None}


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
    except NotLoggedInError as e:
        raise HTTPException(401, str(e))
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


_PINE_APPLIED_ROOT = (Path(__file__).parent / "pine" / "applied").resolve()
_PROFILES_IMAGE_ROOT = (Path(__file__).parent / "profiles").resolve()
_IMAGE_ROOTS = (_SCREENSHOT_ROOT, _PINE_APPLIED_ROOT, _PROFILES_IMAGE_ROOT)


@app.get("/api/chart/image")
async def chart_image(path: str):
    """Serve a screenshot PNG. Allowed roots are the TradingView
    screenshot directory (~/Desktop/TradingView) and the post-apply
    pine overlay directory (pine/applied). Path traversal is blocked —
    the resolved path must start with one of the allowed roots."""
    try:
        resolved = Path(path).resolve()
    except Exception:
        raise HTTPException(400, "invalid path")
    if not any(str(resolved).startswith(str(root)) for root in _IMAGE_ROOTS):
        raise HTTPException(403, "path outside allowed roots")
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
    _check_not_paused()
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

    _check_not_paused()
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
                # Browser-subscription default — chatgpt.com via the
                # attached Chrome. Same $0-per-call as the other _web
                # providers but tends to return cleaner JSON for chart
                # analysis. Pass provider="anthropic" explicitly for
                # API calls, "ollama" for local, "claude_web" for the
                # claude.ai route.
                "provider": p.get("provider", "chatgpt_web"),
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
            if _is_cancellation_artifact(e):
                _analyze_tasks[task_id]["state"] = "cancelled"
                audit.log("analyze.cancellation_artifact_reclassified",
                          task_id=task_id, err=str(e)[:200])
            else:
                _analyze_tasks[task_id]["state"] = "failed"
                _analyze_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _analyze_tasks[task_id]["finished_at"] = time.time()
            if _active_analyze_task == task_id:
                _active_analyze_task = None

    _active_analyze_task = task_id
    _analyze_tasks[task_id]["_task"] = asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


# Curated set of vision-capable local models, in display order. Only
# entries that show up in `ollama list` get returned to the UI — keeps
# the dropdown honest about what the user can actually run. Add new
# entries here when a new chart-bench winner emerges; the UI picks them
# up automatically.
_LOCAL_VISION_MODELS: list[dict] = [
    {"id": "gemma4:31b", "label": "Quality — gemma4:31b",
     "note": "proven default (4-bench winner 2026-04-18)"},
    {"id": "gemma4:26b", "label": "Balanced — gemma4:26b",
     "note": "faster, slight signal-quality tradeoff"},
    {"id": "qwen3.6:27b", "label": "Experimental — qwen3.6:27b",
     "note": "newer family, unbenched for chart tasks"},
    {"id": "qwen3.6:latest", "label": "Experimental — qwen3.6:latest",
     "note": "newest tag, larger context"},
]


@app.get("/api/analyze/local_models")
async def analyze_local_models() -> dict:
    """List vision-capable local Ollama models that are actually
    installed. Intersects `_LOCAL_VISION_MODELS` (curated chart-tested
    candidates) with `ollama list` output. Returns the default model
    explicitly so the UI can pre-select it.

    Empty list if Ollama isn't installed/reachable — caller should fall
    back to a free-text input or hide the Ollama provider option."""
    import asyncio as _asyncio
    try:
        proc = await _asyncio.create_subprocess_exec(
            "ollama", "list",
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=4.0)
    except (FileNotFoundError, _asyncio.TimeoutError):
        return {"installed": [], "default": None, "available": False}
    except Exception as e:
        return {"installed": [], "default": None, "available": False,
                "error": f"{type(e).__name__}: {e}"}

    # `ollama list` first column is the NAME (with tag). Skip the header
    # row and pull the first whitespace-delimited token from each line.
    installed_names: set[str] = set()
    for line in stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        installed_names.add(line.split()[0])

    available = [m for m in _LOCAL_VISION_MODELS if m["id"] in installed_names]
    default = next((m["id"] for m in available), None)
    return {"installed": available, "default": default, "available": True}


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

    _check_not_paused()
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
                # chatgpt_web default — single subscription call on the
                # attached Chrome, $0/call, matches Analyze's default so
                # the deck doesn't flip providers between Analyze and
                # Deep. Pass `provider="claude_web"` or `"ollama"` to
                # override from the UI's provider dropdown.
                provider=p.get("provider", "chatgpt_web"),
                model=p.get("model") or None,
                base_url=p.get("base_url") or None,
            )
            _analyze_tasks[task_id]["state"] = "done"
            _analyze_tasks[task_id]["result"] = result
        except asyncio.CancelledError:
            _analyze_tasks[task_id]["state"] = "cancelled"
            raise
        except Exception as e:
            if _is_cancellation_artifact(e):
                _analyze_tasks[task_id]["state"] = "cancelled"
                audit.log("analyze.cancellation_artifact_reclassified",
                          task_id=task_id, err=str(e)[:200])
            else:
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

    _check_not_paused()
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
            if _is_cancellation_artifact(e):
                _analyze_tasks[task_id]["state"] = "cancelled"
                audit.log("analyze.cancellation_artifact_reclassified",
                          task_id=task_id, err=str(e)[:200])
            else:
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


# Export a finished analysis as JSON / Markdown / PDF / PNG. Source is
# the live task's `result` dict (so screenshot paths, per-TF breakdown,
# pine code, calibration all survive). Returns a download with a stable
# filename pattern `analysis-{symbol}-{tf}-{YYYYMMDDTHHMMSS}.{ext}`.
@app.get("/api/analyze/export/{task_id}")
async def analyze_export(task_id: str, fmt: str = "json"):
    from fastapi.responses import Response
    from tv_automation import export_analysis as ex

    t = _analyze_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task_id (may have expired)")
    result = t.get("result")
    if not result:
        raise HTTPException(
            400, f"task has no result (state={t.get('state')})",
        )

    fmt = (fmt or "json").lower()
    if fmt not in ("json", "md", "pdf", "png"):
        raise HTTPException(400, "fmt must be one of: json, md, pdf, png")

    base = ex.filename_base(result)

    if fmt == "json":
        body = ex.to_json(result)
        media = "application/json"
        fname = f"{base}.json"
    elif fmt == "md":
        body = ex.to_markdown(result)
        media = "text/markdown; charset=utf-8"
        fname = f"{base}.md"
    elif fmt == "png":
        body = ex.to_png(result)
        if body is None:
            raise HTTPException(
                404, "screenshot file missing — can't export PNG",
            )
        media = "image/png"
        fname = f"{base}.png"
    else:  # pdf
        try:
            body = await ex.to_pdf(result)
        except Exception as e:
            audit.log("analyze.export_pdf_fail",
                      task_id=task_id,
                      error=f"{type(e).__name__}: {e}")
            raise HTTPException(500, f"pdf render failed: {e}") from e
        media = "application/pdf"
        fname = f"{base}.pdf"

    audit.log("analyze.export",
              task_id=task_id, request_id=t.get("request_id"),
              fmt=fmt, bytes=len(body))

    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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


@app.post("/api/decisions/reconcile-eod")
async def decisions_reconcile_eod(payload: dict | None = None) -> dict:
    """End-of-day batch reconciliation. Grades all unreconciled decisions
    from a target date (default today) against real OHLCV bars from
    yfinance. Same first-touch rules as the replay bench — hit_stop
    tie-breaks over hit_tp when a bar tags both.

    Payload (all optional):
      * `date`: "YYYY-MM-DD" — defaults to today
      * `symbols`: list[str] — filter to specific symbols
      * `tf`: bar interval, default "5m"
      * `dry_run`: bool — compute but don't write outcomes
    """
    from datetime import datetime as _dt
    from tv_automation import reconcile_eod

    p = payload or {}
    target = None
    if p.get("date"):
        try:
            target = _dt.strptime(p["date"], "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
    syms = p.get("symbols")
    symbols = set(syms) if isinstance(syms, list) and syms else None
    tf = (p.get("tf") or "5m").strip()
    dry_run = bool(p.get("dry_run", False))

    # Runs in a worker thread — yfinance is sync and can stall the
    # event loop for a few seconds when fetching a fresh symbol.
    summary = await asyncio.to_thread(
        reconcile_eod.reconcile_day,
        target=target, symbols=symbols, tf=tf, dry_run=dry_run,
    )
    return summary


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
        "pine_path", "applied_screenshot_path",
        "cost_usd", "elapsed_s", "llm_elapsed_s",
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


@app.get("/api/session/today")
async def session_today(symbol: str = "MNQ1") -> dict:
    """Aggregator for the persistent session bar. Combines:
      - today's most-recent forecast (pre_session → 1000 → 1200 → 1400)
        so the bar can show current bias + invalidation trigger
      - open-positions snapshot for unrealized P&L glance
      - decision_log session summary (wins/losses/realized R)

    Polled by every tab — kept lightweight (no LLM, no CDP, just disk
    reads + a positions API hit which itself caches)."""
    from datetime import datetime as _dt
    today = _dt.now().strftime("%Y-%m-%d")

    # Bias + invalidation come from pre_session — that's the only stage
    # with structured tactical_bias / predictions fields. Live stages
    # (1000/1200/1400) carry only raw_response, so we use them just as
    # a freshness indicator (which stage was last completed today).
    today_forecast: dict = {"exists": False}
    pre_path = _FORECASTS_ROOT / f"{symbol}_{today}_pre_session.json"
    if pre_path.exists():
        try:
            pd = json.loads(pre_path.read_text())
            tb = pd.get("tactical_bias") or {}
            preds = pd.get("predictions") or {}
            today_forecast = {
                "exists": True,
                "stage": "pre_session",
                "bias": tb.get("bias"),
                "invalidation": tb.get("invalidation"),
                "direction": preds.get("direction"),
                "direction_confidence": preds.get("direction_confidence"),
                "made_at": pd.get("made_at"),
            }
        except Exception:
            pass

    # Last live-forecast stage that fired today — appended as a freshness
    # chip on the session bar so the user knows whether the bias has been
    # refreshed by an in-session check yet.
    latest_live: str | None = None
    for stage in ("1400", "1200", "1000"):
        if (_FORECASTS_ROOT / f"{symbol}_{today}_{stage}.json").exists():
            latest_live = stage
            break
    today_forecast["latest_live_stage"] = latest_live

    # Pivot state — most-recent `invalidation_HHMM` stage fired today,
    # if any. Presence here tells the session bar to show the pivoted
    # bias overlaid on (or instead of) the pre-session bias.
    pivot_info: dict | None = None
    pivot_files = sorted(
        _FORECASTS_ROOT.glob(f"{symbol}_{today}_invalidation_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if pivot_files:
        try:
            pp = json.loads(pivot_files[0].read_text())
            rb = pp.get("revised_tactical_bias") or {}
            pivot_info = {
                "stage": pp.get("stage"),
                "called_at_et": pp.get("pivot_called_at_et"),
                "classification": pp.get("pivot_classification"),
                "revised_bias": rb.get("bias"),
                "revised_invalidation": rb.get("invalidation"),
                "confidence": pp.get("pivot_confidence"),
                "made_at": pp.get("made_at"),
                # Pine is renderable if we parsed structured output — the
                # pivot_pine generator tolerates missing fields (it uses
                # -1 sentinels) but parse_fail cases have no useful data
                # to render.
                "pine_available": bool(pp.get("parsed_structured")),
            }
        except Exception:
            pass
    today_forecast["pivot"] = pivot_info

    # Open positions — best-effort. Don't block the bar if CDP is busy
    # (e.g., during a profile-run); just report 0/unknown.
    pos_summary = {"open_count": 0, "unrealized_pnl": None, "available": False}
    try:
        # Skip the positions hit if CDP is in use — avoids 409 noise on the bar.
        if not _cdp_busy():
            pos = await trading_mod.positions()
            rows = pos.get("positions") or []
            unreal = 0.0
            for r in rows:
                v = r.get("Unrealized P&L") or r.get("unrealized_pnl") or 0
                try:
                    unreal += float(str(v).replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    pass
            pos_summary = {
                "open_count": len(rows),
                "unrealized_pnl": unreal,
                "available": True,
            }
    except Exception:
        pass

    return {
        "date": today,
        "symbol": symbol,
        "today_forecast": today_forecast,
        "positions": pos_summary,
        "session": decision_log_mod.session_summary(),
    }


@app.post("/api/analyze/apply-pine")
async def analyze_apply_pine(payload: dict) -> dict:
    """Apply a previously-generated pine script to the TradingView chart.

    Applies directly to whatever layout is currently active — no layout
    cloning or switching. Path must be inside the repo's
    `pine/generated/` directory, never an arbitrary file.
    """
    _check_not_paused()
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
    cmd = [python_exe, str(apply_script), str(resolved)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(Path(__file__).parent),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        ok = proc.returncode == 0
        stdout_text = stdout.decode("utf-8", errors="replace")

        # Extract the applied-screenshot path printed by apply_pine.py
        # (marker `APPLIED_SCREENSHOT: /abs/path.png`). When present,
        # tie it to the originating decision via request_id so the
        # Journal tab can show the "levels-drawn" chart alongside the
        # signal/levels/outcome — the image is the highest-signal
        # feedback for rating setup quality.
        applied_screenshot = None
        study_count_delta = None
        for line in stdout_text.splitlines():
            if line.startswith("APPLIED_SCREENSHOT:"):
                applied_screenshot = line.split(":", 1)[1].strip()
            elif line.startswith("STUDY_COUNT_DELTA:"):
                # Format: `STUDY_COUNT_DELTA: before=N after=M delta=K`
                # Captures whether the apply silently no-op'd: a delta
                # of 0 when the indicator name wasn't already on chart
                # implies the subprocess succeeded but the study didn't
                # actually attach.
                m = re.search(
                    r"before=(-?\d+)\s+after=(-?\d+)\s+delta=(-?\d+)", line,
                )
                if m:
                    study_count_delta = {
                        "before": int(m.group(1)),
                        "after": int(m.group(2)),
                        "delta": int(m.group(3)),
                    }
                    audit.log("analyze.apply_pine.study_count",
                              **study_count_delta)

        request_id = (p.get("request_id") or "").strip()
        linked = False
        if ok and applied_screenshot and request_id:
            try:
                linked = decision_log_mod.set_applied_screenshot(
                    request_id, applied_screenshot,
                )
            except Exception as e:
                audit.log("analyze.apply_pine.link_fail",
                          error=f"{type(e).__name__}: {e}",
                          request_id=request_id)

        # Persist the layout after a successful apply — without this,
        # the new study is in-memory only and gets dropped on next
        # chart reload. Best-effort: log and continue if save fails so
        # the caller still sees the apply result.
        layout_saved = False
        if ok:
            try:
                await layouts_mod.save()
                layout_saved = True
                audit.log("analyze.apply_pine.layout_saved")
            except Exception as e:
                audit.log("analyze.apply_pine.layout_save_fail",
                          error=f"{type(e).__name__}: {e}")

        return {
            "ok": ok, "path": str(resolved),
            "returncode": proc.returncode,
            "applied_screenshot": applied_screenshot,
            "linked_to_decision": linked,
            "layout_saved": layout_saved,
            "stdout": stdout_text[-2000:],
            "stderr": stderr.decode("utf-8", errors="replace")[-2000:],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "path": str(resolved),
                "error": "apply_pine timeout (120s)"}
    except Exception as e:
        raise HTTPException(500, f"apply_pine failed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Visual Coach + Sketchpad — AI-proposed chart visuals composed into a
# single Sketchpad Pine indicator that's separate from the Forecast
# Overlay. Coach is mid-session dynamic; the forecast is morning-locked.
# ---------------------------------------------------------------------------

_SKETCHPAD_ROOT = (Path(__file__).parent / "sketchpad").resolve()
_SKETCHPAD_KEY_RX = re.compile(r"^[A-Za-z0-9!_]+$")
_SKETCHPAD_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SKETCHPAD_VID_RX = re.compile(r"^v_[a-f0-9]{4,16}$")
_SKETCHPAD_VALID_PROVIDERS = {"anthropic", "ollama", "claude_web", "chatgpt_web"}

_VISUAL_COACH_VALID_TYPES = {"level", "vline", "cross_alert"}
_VISUAL_COACH_VALID_COLORS = {
    "red", "green", "yellow", "blue", "aqua",
    "orange", "purple", "white", "gray",
}


def _sketchpad_path(symbol: str, date: str) -> Path:
    """JSON path for the sketchpad of (symbol, date). Source of truth —
    the .pine file is regenerated from this on every apply."""
    safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", symbol)
    return _SKETCHPAD_ROOT / f"{safe_sym}_{date}.json"


def _read_sketchpad(symbol: str, date: str) -> dict:
    """Load the sketchpad JSON for (symbol, date), or a fresh empty one.

    Tolerant of missing files / malformed JSON — returns a valid empty
    sketchpad either way so the UI's "current visuals" panel has
    something to render."""
    path = _sketchpad_path(symbol, date)
    if not path.exists():
        return {"symbol": symbol, "date": date,
                "updated_at": None, "visuals": []}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        data.setdefault("symbol", symbol)
        data.setdefault("date", date)
        data.setdefault("updated_at", None)
        if not isinstance(data.get("visuals"), list):
            data["visuals"] = []
        return data
    except Exception as e:
        audit.log("sketchpad.read_fail",
                  path=str(path), err=f"{type(e).__name__}: {e}")
        return {"symbol": symbol, "date": date,
                "updated_at": None, "visuals": []}


def _write_sketchpad(symbol: str, date: str, visuals: list[dict]) -> dict:
    """Persist the sketchpad JSON. Updates `updated_at` to now."""
    _SKETCHPAD_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": symbol, "date": date,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "visuals": visuals,
    }
    _sketchpad_path(symbol, date).write_text(json.dumps(payload, indent=2))
    return payload


def _validate_visual_for_sketchpad(raw: dict) -> dict | None:
    """Same shape as visual_coach._sanitize_visual but preserves the
    incoming `id` instead of minting a new one. Used when accepting
    proposals into the sketchpad — the LLM's id is already
    server-assigned and we want it stable across accept/render cycles.

    Returns None on invalid (caller filters)."""
    if not isinstance(raw, dict):
        return None
    vid = (raw.get("id") or "").strip()
    if not _SKETCHPAD_VID_RX.match(vid):
        return None
    vtype = (raw.get("type") or "").strip().lower()
    if vtype not in _VISUAL_COACH_VALID_TYPES:
        return None
    color = (raw.get("color") or "white").strip().lower()
    if color not in _VISUAL_COACH_VALID_COLORS:
        color = "white"
    label = str(raw.get("label") or "").strip()[:60] or vtype
    confidence = (raw.get("confidence") or "med").strip().lower()
    if confidence not in ("low", "med", "high"):
        confidence = "med"

    visual: dict[str, Any] = {
        "id": vid, "type": vtype, "label": label, "color": color,
        "rationale": str(raw.get("rationale") or "").strip()[:280],
        "confidence": confidence,
    }
    if vtype == "level":
        try:
            visual["price"] = float(raw["price"])
        except (KeyError, TypeError, ValueError):
            return None
        visual["alert_on_cross"] = bool(raw.get("alert_on_cross"))
    elif vtype == "vline":
        time_et = (raw.get("time_et") or "").strip()
        if not re.match(r"^\d{1,2}:\d{2}$", time_et):
            return None
        try:
            hh, mm = (int(p) for p in time_et.split(":", 1))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                return None
        except ValueError:
            return None
        visual["time_et"] = f"{hh:02d}:{mm:02d}"
    elif vtype == "cross_alert":
        try:
            visual["price"] = float(raw["price"])
        except (KeyError, TypeError, ValueError):
            return None
        direction = (raw.get("direction") or "").strip().lower()
        if direction not in ("above", "below"):
            return None
        visual["direction"] = direction
    return visual


# Coach analyze runs as a background task — same pattern as analyze_mtf
# so the UI can poll progress and stream audit events. Holds the CDP
# session for the screenshot, then releases (the LLM call is HTTP/web).
@app.post("/api/coach/analyze")
async def coach_analyze_start(payload: dict) -> dict:
    """Capture the active chart and ask a vision LLM for additive visuals.

    Body: { symbol, timeframe?, provider?, model?, base_url? }

    Provider defaults to claude_web (Opus 4.7 if model unspecified —
    `_resolve_model` upstream picks Sonnet 4.6 by default; the UI
    dropdown sends "opus" to flip to Opus). Returns a task_id for
    polling via /api/coach/{task_id}.
    """
    global _active_analyze_task
    p = payload or {}
    symbol = (p.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(400, "symbol required")
    timeframe = (p.get("timeframe") or "").strip() or "5m"
    provider = (p.get("provider") or "claude_web").strip()
    if provider not in _SKETCHPAD_VALID_PROVIDERS:
        raise HTTPException(400, f"invalid provider {provider!r}")

    _check_not_paused()
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    # Reuse the analyze-task registry — Coach holds the same CDP
    # session as analyze, so it must compete for the same slot. Adding
    # mode="coach" lets _cdp_busy()'s caller distinguish in error UX.
    _analyze_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "symbol": symbol,
        "timeframe": timeframe,
        "mode": "coach",
    }

    async def runner():
        global _active_analyze_task
        try:
            from tv_automation import visual_coach as vc_mod
            result = await vc_mod.analyze_chart_for_visuals(
                symbol,
                timeframe=timeframe,
                provider=provider,
                model=p.get("model") or None,
                base_url=p.get("base_url") or None,
            )
            _analyze_tasks[task_id]["state"] = "done"
            _analyze_tasks[task_id]["result"] = result
        except asyncio.CancelledError:
            _analyze_tasks[task_id]["state"] = "cancelled"
            raise
        except Exception as e:
            if _is_cancellation_artifact(e):
                _analyze_tasks[task_id]["state"] = "cancelled"
                audit.log("coach.cancellation_artifact_reclassified",
                          task_id=task_id, err=str(e)[:200])
            else:
                _analyze_tasks[task_id]["state"] = "failed"
                _analyze_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _analyze_tasks[task_id]["finished_at"] = time.time()
            if _active_analyze_task == task_id:
                _active_analyze_task = None

    _active_analyze_task = task_id
    _analyze_tasks[task_id]["_task"] = asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.get("/api/coach/task/{task_id}")
async def coach_status(task_id: str) -> dict:
    """Poll a Coach analyze task — same shape as /api/analyze/{task_id}."""
    t = _analyze_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task")
    out = {k: v for k, v in t.items() if k != "_task"}
    return out


# Chat — multi-turn brainstorm on top of a Coach analyze. Each chat
# turn replays the full conversation through the same provider/model
# the thread was started with. Stateless on the provider side — no
# Playwright lifecycle to manage between requests.

_chat_tasks: dict[str, dict] = {}  # task_id → {state, thread_id, ...}


@app.get("/api/coach/thread/{thread_id}")
async def coach_thread_get(thread_id: str) -> dict:
    """Return a thread's full transcript + metadata. Used to rehydrate
    the chat panel after a page reload."""
    from tv_automation import visual_coach as vc_mod
    t = vc_mod.get_thread(thread_id)
    if not t:
        raise HTTPException(404, "unknown thread")
    return t


@app.post("/api/coach/chat")
async def coach_chat(payload: dict) -> dict:
    """Send one user message into a chat thread. Long-running (~30s
    typical for a browser-driven provider) — runs as a task so the UI
    can poll progress.

    Body: { thread_id, message }
    Returns: { task_id }  (poll via /api/coach/chat/task/{task_id})
    """
    p = payload or {}
    thread_id = (p.get("thread_id") or "").strip()
    message = (p.get("message") or "").strip()
    if not thread_id:
        raise HTTPException(400, "thread_id required")
    if not message:
        raise HTTPException(400, "message required")

    _check_not_paused()
    # Chat reuses the existing claude.ai/chatgpt.com tab in the
    # attached Chrome — same CDP session as the analyze flow. Keep
    # mutual exclusion via the same _cdp_busy() guard.
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _chat_tasks[task_id] = {
        "state": "running", "request_id": request_id,
        "thread_id": thread_id, "started_at": time.time(),
    }
    # Tag in _analyze_tasks too so _cdp_busy() blocks competing starts
    # while a chat turn is in flight (chat occupies the browser).
    global _active_analyze_task
    _analyze_tasks[task_id] = {
        "state": "running", "request_id": request_id,
        "started_at": time.time(),
        "symbol": _chat_tasks[task_id].get("symbol", ""),
        "mode": "coach_chat",
    }

    async def runner():
        global _active_analyze_task
        try:
            from tv_automation import visual_coach as vc_mod
            result = await vc_mod.chat_turn(thread_id, message)
            _chat_tasks[task_id]["state"] = "done"
            _chat_tasks[task_id]["result"] = result
            _analyze_tasks[task_id]["state"] = "done"
        except KeyError as e:
            _chat_tasks[task_id]["state"] = "failed"
            _chat_tasks[task_id]["error"] = f"thread not found: {e}"
            _analyze_tasks[task_id]["state"] = "failed"
        except asyncio.CancelledError:
            _chat_tasks[task_id]["state"] = "cancelled"
            _analyze_tasks[task_id]["state"] = "cancelled"
            raise
        except Exception as e:
            if _is_cancellation_artifact(e):
                _chat_tasks[task_id]["state"] = "cancelled"
                _analyze_tasks[task_id]["state"] = "cancelled"
            else:
                _chat_tasks[task_id]["state"] = "failed"
                _chat_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
                _analyze_tasks[task_id]["state"] = "failed"
                _analyze_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _chat_tasks[task_id]["finished_at"] = time.time()
            _analyze_tasks[task_id]["finished_at"] = time.time()
            if _active_analyze_task == task_id:
                _active_analyze_task = None

    _active_analyze_task = task_id
    _chat_tasks[task_id]["_task"] = asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id,
            "thread_id": thread_id}


@app.get("/api/coach/chat/task/{task_id}")
async def coach_chat_status(task_id: str) -> dict:
    """Poll a chat-turn task. Same poll-shape as the analyze endpoints."""
    t = _chat_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown chat task")
    return {k: v for k, v in t.items() if k != "_task"}


@app.get("/api/sketchpad/{symbol}/{date}")
async def sketchpad_get(symbol: str, date: str) -> dict:
    """Return the current accepted-visuals sketchpad for (symbol, date).

    Always 200 — empty sketchpad if the file doesn't exist yet."""
    if not _SKETCHPAD_KEY_RX.match(symbol) or not _SKETCHPAD_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")
    return _read_sketchpad(symbol, date)


@app.post("/api/sketchpad/{symbol}/{date}/accept")
async def sketchpad_accept(symbol: str, date: str, payload: dict) -> dict:
    """Append accepted visuals to the sketchpad. Replaces any existing
    visual with the same id (idempotent on re-accept).

    Body: { visuals: [ {id, type, label, color, ...} ] }
    """
    if not _SKETCHPAD_KEY_RX.match(symbol) or not _SKETCHPAD_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")
    p = payload or {}
    incoming = p.get("visuals") or []
    if not isinstance(incoming, list):
        raise HTTPException(400, "visuals must be a list")

    accepted: list[dict] = []
    rejected = 0
    for raw in incoming[:20]:  # cap one accept call to a sane batch size
        v = _validate_visual_for_sketchpad(raw)
        if v:
            accepted.append(v)
        else:
            rejected += 1

    sketch = _read_sketchpad(symbol, date)
    by_id = {v["id"]: v for v in sketch["visuals"]}
    for v in accepted:
        by_id[v["id"]] = v  # last-write-wins per id

    merged = list(by_id.values())
    payload_out = _write_sketchpad(symbol, date, merged)
    audit.log("sketchpad.accept", symbol=symbol, date=date,
              accepted=len(accepted), rejected=rejected,
              total=len(merged))
    return {**payload_out, "accepted": len(accepted), "rejected": rejected}


@app.delete("/api/sketchpad/{symbol}/{date}/visual/{visual_id}")
async def sketchpad_remove(symbol: str, date: str, visual_id: str) -> dict:
    """Remove one visual from the sketchpad by id. 404 if not present."""
    if not _SKETCHPAD_KEY_RX.match(symbol) or not _SKETCHPAD_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")
    if not _SKETCHPAD_VID_RX.match(visual_id):
        raise HTTPException(400, "invalid visual_id")

    sketch = _read_sketchpad(symbol, date)
    before = len(sketch["visuals"])
    sketch["visuals"] = [v for v in sketch["visuals"] if v.get("id") != visual_id]
    if len(sketch["visuals"]) == before:
        raise HTTPException(404, "visual_id not found")
    payload = _write_sketchpad(symbol, date, sketch["visuals"])
    audit.log("sketchpad.remove", symbol=symbol, date=date,
              visual_id=visual_id, remaining=len(sketch["visuals"]))
    return payload


@app.post("/api/sketchpad/{symbol}/{date}/clear")
async def sketchpad_clear(symbol: str, date: str) -> dict:
    """Drop all visuals. The sketchpad JSON file remains, with an empty
    visuals list. Apply after this to scrub the chart indicator."""
    if not _SKETCHPAD_KEY_RX.match(symbol) or not _SKETCHPAD_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")
    payload = _write_sketchpad(symbol, date, [])
    audit.log("sketchpad.clear", symbol=symbol, date=date)
    return payload


@app.post("/api/sketchpad/{symbol}/{date}/apply")
async def sketchpad_apply(symbol: str, date: str) -> dict:
    """Render the sketchpad JSON to Pine, write to pine/generated/, and
    apply to the live TV chart via apply_pine.py. Long-running (~30-60s).

    Mirrors `forecast_apply` — same subprocess shape, same timeout."""
    _check_not_paused()
    if not _SKETCHPAD_KEY_RX.match(symbol) or not _SKETCHPAD_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")

    sketch = _read_sketchpad(symbol, date)
    visuals = sketch.get("visuals") or []

    from tv_automation.sketchpad_pine import render_sketchpad
    pine_text = render_sketchpad(visuals, symbol, date)

    pine_dir = (Path(__file__).parent / "pine" / "generated").resolve()
    pine_dir.mkdir(parents=True, exist_ok=True)
    pine_path = pine_dir / f"sketchpad_{date}.pine"
    pine_path.write_text(pine_text)
    audit.log("sketchpad.render", symbol=symbol, date=date,
              n_visuals=len(visuals), pine_path=str(pine_path),
              bytes=len(pine_text))

    apply_script = Path(__file__).parent / "apply_pine.py"
    venv_python = Path(__file__).parent / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else "python"
    cmd = [python_exe, str(apply_script), str(pine_path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(Path(__file__).parent),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        ok = proc.returncode == 0
        stdout_text = stdout.decode("utf-8", errors="replace")
        applied_screenshot = None
        for line in stdout_text.splitlines():
            if line.startswith("APPLIED_SCREENSHOT:"):
                applied_screenshot = line.split(":", 1)[1].strip()
                break
        audit.log("sketchpad.apply_done", symbol=symbol, date=date,
                  ok=ok, returncode=proc.returncode,
                  applied_screenshot=applied_screenshot)
        return {
            "ok": ok, "pine_path": str(pine_path),
            "n_visuals": len(visuals),
            "returncode": proc.returncode,
            "applied_screenshot": applied_screenshot,
            "stdout_tail": stdout_text[-1500:],
            "stderr_tail": stderr.decode("utf-8", errors="replace")[-1500:],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "pine_path": str(pine_path),
                "error": "apply_pine timeout (120s)"}
    except Exception as e:
        raise HTTPException(500, f"apply_pine failed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Recording — capture every keystroke + click on the user's TradingView
# tab plus free-form intent notes, into one JSONL file per session.
# Pure teaching aid: lets us study how the user actually drives Replay
# so we can replicate the workflow in code.
# ---------------------------------------------------------------------------


@app.post("/api/recording/start")
async def recording_start() -> dict:
    """Begin recording the user's TradingView tab. Requires CDP-attach
    mode (TV_CDP_URL set) — there's no point recording a private
    Chromium we drive ourselves."""
    cdp_url = os.getenv("TV_CDP_URL", "").strip()
    if not cdp_url:
        raise HTTPException(400, "TV_CDP_URL not set — recording needs CDP-attach mode")
    from tv_automation import record_session as rec_mod
    try:
        return await rec_mod.start_recording(cdp_url)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/recording/note")
async def recording_note(payload: dict) -> dict:
    """Append a free-form intent note to the active recording."""
    from tv_automation import record_session as rec_mod
    text = (payload or {}).get("text") or ""
    res = await rec_mod.add_note(text)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "note failed"))
    return res


@app.post("/api/recording/stop")
async def recording_stop() -> dict:
    """End the active recording and disconnect from Chrome."""
    from tv_automation import record_session as rec_mod
    res = await rec_mod.stop_recording()
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "stop failed"))
    return res


@app.get("/api/recording/status")
async def recording_status() -> dict:
    """Cheap probe — returns {active, path, events, notes} when
    recording, {active: false} otherwise."""
    from tv_automation import record_session as rec_mod
    return rec_mod.status()


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------

_NOTES_ROOT = (Path(__file__).parent / "notes").resolve()


def _append_trade_note(*, symbol: str, side: str, qty: int, note: str,
                       result: dict, dry_run: bool) -> None:
    """Persist a trader's entry-note alongside the order outcome.

    One JSONL file per day at notes/YYYY-MM-DD.jsonl. Each line:
      {ts, iso_ts, symbol, side, qty, dry_run, note, ok, final_status,
       observed_delta}

    Failures are logged + swallowed — we never want a notes-file write
    error to mask a successful trade response."""
    if not note:
        return
    try:
        from datetime import datetime as _dt
        _NOTES_ROOT.mkdir(parents=True, exist_ok=True)
        now = _dt.now()
        path = _NOTES_ROOT / f"{now.strftime('%Y-%m-%d')}.jsonl"
        line = {
            "ts": now.timestamp(),
            "iso_ts": now.isoformat(timespec="seconds"),
            "symbol": symbol, "side": side, "qty": qty,
            "dry_run": dry_run,
            "note": note,
            "ok": bool(result.get("ok")),
            "final_status": result.get("final_status"),
            "observed_delta": result.get("observed_delta"),
        }
        with path.open("a") as fh:
            fh.write(json.dumps(line) + "\n")
        audit.log("trade.note", **{k: line[k] for k in ("symbol", "side", "qty", "ok")})
    except Exception as e:
        audit.log("trade.note_write_fail", err=f"{type(e).__name__}: {e}")


@app.post("/api/trade/order")
async def trade_order(payload: dict) -> dict:
    p = payload or {}
    symbol = p.get("symbol", "").strip()
    side = p.get("side", "").strip().lower()
    qty = int(p.get("qty", 0))
    dry_run = bool(p.get("dry_run", False))
    # Optional micro-journal entry — captured at order time so post-trade
    # reconciliation has the trader's reasoning. Empty/missing skips the
    # notes-file write entirely.
    note = (p.get("note") or "").strip()[:200]
    # Optional bracket prices — when either is supplied we route through the
    # order panel (orders.place_market) which supports TP/SL. Plain markets
    # stay on the faster inline quick-trade bar (trading.place_order).
    tp = p.get("take_profit")
    sl = p.get("stop_loss")
    if not symbol or side not in ("buy", "sell") or qty <= 0:
        raise HTTPException(400, "symbol, side=buy|sell, qty>0 required")
    try:
        if tp is not None or sl is not None:
            result = await orders_mod.place_market(
                symbol=symbol, side=side, qty=qty,
                take_profit=float(tp) if tp is not None else None,
                stop_loss=float(sl) if sl is not None else None,
                dry_run=dry_run,
            )
        else:
            result = await trading_mod.place_order(
                symbol=symbol, side=side, qty=qty, dry_run=dry_run,
            )
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")

    _append_trade_note(symbol=symbol, side=side, qty=qty, note=note,
                       result=result, dry_run=dry_run)
    return result


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


# ---------------------------------------------------------------------------
# Daily Profiles — comparison-day reference DB
# ---------------------------------------------------------------------------

_PROFILES_ROOT = (Path(__file__).parent / "profiles").resolve()
_PROFILE_KEY_RX = __import__("re").compile(r"^[A-Za-z0-9_\-]+$")


@app.get("/api/profiles")
async def profiles_list() -> dict:
    """List all saved daily profiles — summary fields only, sorted newest-first."""
    if not _PROFILES_ROOT.exists():
        return {"profiles": []}
    results = []
    for jf in sorted(_PROFILES_ROOT.glob("*.json"), reverse=True):
        try:
            data = json.loads(jf.read_text())
        except Exception:
            continue
        results.append({
            "key": jf.stem,
            "date": data.get("date"),
            "dow": data.get("dow"),
            "symbol": data.get("symbol"),
            "session_complete": data.get("session_complete"),
            "summary": {
                "direction": (data.get("summary") or {}).get("direction"),
                "box_color": (data.get("summary") or {}).get("box_color"),
                "open": (data.get("summary") or {}).get("open_approx"),
                "close": (data.get("summary") or {}).get("close_approx"),
                "net_range_pct": (data.get("summary") or {}).get("net_range_pct_open_to_close"),
                "shape_sentence": (data.get("summary") or {}).get("shape_sentence"),
            },
            "tags": data.get("tags", {}),
        })
    return {"profiles": results}


@app.get("/api/profiles/{key}")
async def profile_get(key: str) -> dict:
    """Full profile — JSON payload + raw markdown narrative."""
    if not _PROFILE_KEY_RX.match(key):
        raise HTTPException(400, "invalid key")
    jf = _PROFILES_ROOT / f"{key}.json"
    mf = _PROFILES_ROOT / f"{key}.md"
    if not jf.exists():
        raise HTTPException(404, "profile not found")
    return {
        "key": key,
        "json": json.loads(jf.read_text()),
        "markdown": mf.read_text() if mf.exists() else "",
    }


@app.get("/api/profiles/{key}/screenshot")
async def profile_screenshot(key: str):
    """Serve the reference-day screenshot PNG for a profile.

    Prefers the in-repo archived copy at `profiles/{key}.png` (always
    present for runs after the screenshot-archive change; backfilled
    for older profiles). Falls back to the recorded `screenshot_path`
    so we still serve anything that hasn't been archived yet."""
    if not _PROFILE_KEY_RX.match(key):
        raise HTTPException(400, "invalid key")
    jf = _PROFILES_ROOT / f"{key}.json"
    if not jf.exists():
        raise HTTPException(404, "profile not found")
    bundled = _PROFILES_ROOT / f"{key}.png"
    if bundled.exists():
        return FileResponse(str(bundled), media_type="image/png")
    data = json.loads(jf.read_text())
    path = data.get("screenshot_path")
    if not path:
        raise HTTPException(404, "no screenshot_path in profile")
    try:
        resolved = Path(path).resolve()
    except Exception:
        raise HTTPException(400, "invalid screenshot path")
    if not any(str(resolved).startswith(str(root)) for root in _IMAGE_ROOTS):
        raise HTTPException(403, "screenshot path outside allowed roots")
    if not resolved.exists():
        raise HTTPException(404, "screenshot file missing")
    return FileResponse(str(resolved), media_type="image/png")


# ---------------------------------------------------------------------------
# Daily Profile RUN — kick off tv_automation.daily_profile in-process
# ---------------------------------------------------------------------------

_PROFILE_DATE_RX = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")
_PROFILE_SYMBOL_RX = __import__("re").compile(r"^[A-Za-z0-9]{1,12}$")


@app.post("/api/profiles/run")
async def profile_run_start(payload: dict) -> dict:
    """Kick off a daily-profile run.

    Two body shapes:
      * Range: {start: "YYYY-MM-DD", end?: "YYYY-MM-DD", symbol?, resume?}
        Profiles each weekday in [start, end] (single day if end omitted).
      * Explicit dates: {dates: ["YYYY-MM-DD", ...], symbol?, resume?}
        Profiles exactly those days — supports non-contiguous picks
        (e.g. Mon + Wed + Fri, or two non-adjacent weeks). The UI's
        multi-select calendar uses this shape.

    Returns {task_id, request_id} — poll /api/profiles/runs/{task_id} for
    status and /api/audit/tail?request_id=... for live events."""
    global _active_profile_run
    p = payload or {}
    dates_raw = p.get("dates")
    symbol = (p.get("symbol") or "MNQ1").strip()
    resume = bool(p.get("resume", True))

    dates: list[str] | None = None
    start: str | None = None
    end: str | None = None
    if dates_raw is not None:
        if not isinstance(dates_raw, list) or not dates_raw:
            raise HTTPException(400, "dates must be a non-empty list")
        dates = []
        for d in dates_raw:
            if not isinstance(d, str) or not _PROFILE_DATE_RX.match(d):
                raise HTTPException(400, f"invalid date in list: {d!r}")
            dates.append(d)
        # Sort + dedupe so the run order is deterministic and the audit
        # log reads chronologically.
        dates = sorted(set(dates))
    else:
        start = (p.get("start") or "").strip()
        end = (p.get("end") or "").strip() or None
        if not _PROFILE_DATE_RX.match(start):
            raise HTTPException(400, "start must be YYYY-MM-DD (or supply dates: [...])")
        if end is not None and not _PROFILE_DATE_RX.match(end):
            raise HTTPException(400, "end must be YYYY-MM-DD")
    if not _PROFILE_SYMBOL_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")

    _check_not_paused()
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()

    # Contextvar: background runner inherits so all daily_profile.* audit
    # events tag with this request_id for /api/audit/tail streaming.
    audit.current_request_id.set(request_id)

    _profile_run_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "start": start, "end": end, "dates": dates,
        "symbol": symbol, "resume": resume,
    }

    async def runner():
        global _active_profile_run
        try:
            if dates is not None:
                from tv_automation.daily_profile import run_profile_dates
                results = await run_profile_dates(
                    dates, symbol=symbol, resume=resume,
                )
            else:
                from tv_automation.daily_profile import run_profile_range
                results = await run_profile_range(
                    start, end, symbol=symbol, resume=resume,
                )
            _profile_run_tasks[task_id]["state"] = "done"
            _profile_run_tasks[task_id]["results"] = results
        except Exception as e:
            _profile_run_tasks[task_id]["state"] = "failed"
            _profile_run_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _profile_run_tasks[task_id]["finished_at"] = time.time()
            if _active_profile_run == task_id:
                _active_profile_run = None

    _active_profile_run = task_id
    asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.get("/api/profiles/runs/{task_id}")
async def profile_run_status(task_id: str) -> dict:
    t = _profile_run_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task_id")
    return {k: v for k, v in t.items() if not callable(v)}


# ---------------------------------------------------------------------------
# Daily Forecasts — replay forecast workflow artifacts
# ---------------------------------------------------------------------------

_FORECASTS_ROOT = (Path(__file__).parent / "forecasts").resolve()
# Forecast filenames: SYMBOL_YYYY-MM-DD_STAGE.{md,json}
# Stage may be HHMM (e.g. 1000), `reconciliation`, `pre_session`,
# `pre_session_reconciliation`, etc. The stem-parser below pulls the date
# explicitly via regex so it doesn't get confused by multi-word stages.
_FORECAST_DATE_RX = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")
_FORECAST_STAGE_RX = __import__("re").compile(r"^[a-z0-9_]{2,40}$")
_FORECAST_STEM_RX = __import__("re").compile(
    r"^(?P<symbol>[A-Za-z0-9]+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<stage>[a-z0-9_]+)$"
)


@app.post("/api/forecasts/run")
async def forecast_run_start(payload: dict) -> dict:
    """Kick off a daily-forecast run for one trading day.

    Body: {date: "YYYY-MM-DD", symbol?: "MNQ1", resume?: bool, adhoc?: bool}
    Returns {task_id, request_id}. Poll /api/forecasts/runs/{task_id} for
    status and /api/audit/tail?request_id=... for live stage events.

    `resume=true` skips stages whose .json already exists (F1/F2/F3/recon);
    `resume=false` re-runs all stages, overwriting existing files.

    `adhoc=true` makes the run time-aware: stages whose cursor time
    hasn't arrived are skipped rather than gate-failing, and
    reconciliation is skipped if RTH isn't closed or the profile is
    missing. Recommended default when invoking from the UI mid-day."""
    global _active_forecast_run
    p = payload or {}
    date = (p.get("date") or "").strip()
    symbol = (p.get("symbol") or "MNQ1").strip()
    resume = bool(p.get("resume", True))
    adhoc = bool(p.get("adhoc", False))

    if not _PROFILE_DATE_RX.match(date):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if not _PROFILE_SYMBOL_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")

    _check_not_paused()
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _forecast_run_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "date": date, "symbol": symbol, "resume": resume, "adhoc": adhoc,
    }

    async def runner():
        global _active_forecast_run
        try:
            from tv_automation.daily_forecast import run_forecast_day
            result = await run_forecast_day(
                date, symbol=symbol, resume=resume, adhoc=adhoc,
            )
            _forecast_run_tasks[task_id]["state"] = "done"
            _forecast_run_tasks[task_id]["result"] = result
        except Exception as e:
            _forecast_run_tasks[task_id]["state"] = "failed"
            _forecast_run_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _forecast_run_tasks[task_id]["finished_at"] = time.time()
            if _active_forecast_run == task_id:
                _active_forecast_run = None

    _active_forecast_run = task_id
    asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.get("/api/forecasts/runs/{task_id}")
async def forecast_run_status(task_id: str) -> dict:
    t = _forecast_run_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task_id")
    return {k: v for k, v in t.items() if not callable(v)}


def _latest_pivot_path(symbol: str, date: str) -> Path | None:
    """Return the most-recent `invalidation_HHMM.json` for this day, if any."""
    files = sorted(
        _FORECASTS_ROOT.glob(f"{symbol}_{date}_invalidation_*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return files[0] if files else None


@app.delete("/api/forecasts/{symbol}/{date}/pivot")
async def forecast_pivot_clear(symbol: str, date: str) -> dict:
    """Soft-delete the most-recent pivot for this day by moving its JSON
    + MD artifacts into `forecasts/cleared/`. Nothing is truly deleted —
    you can inspect or restore the files from there later. The session
    bar stops showing the pivoted bias as soon as the JSON is gone from
    the canonical glob path."""
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")
    latest = _latest_pivot_path(symbol, date)
    if not latest:
        raise HTTPException(404, "no pivot to clear")
    cleared_dir = _FORECASTS_ROOT / "cleared"
    cleared_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    stem = latest.stem
    # Move both the .json and the matching .md file.
    for suffix in (".json", ".md"):
        src = _FORECASTS_ROOT / f"{stem}{suffix}"
        if src.exists():
            dst = cleared_dir / src.name
            # If a same-named file already exists in cleared/, append a
            # timestamp so we never silently clobber prior clears.
            if dst.exists():
                from datetime import datetime as _dt
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                dst = cleared_dir / f"{src.stem}.cleared{ts}{src.suffix}"
            src.rename(dst)
            moved.append(str(dst))
    audit.log("forecast_pivot.clear", stem=stem, moved=moved)
    return {"ok": True, "moved": moved}


@app.get("/api/forecasts/{symbol}/{date}/pivot/pine")
async def forecast_pivot_pine(symbol: str, date: str) -> Response:
    """Generate + return the Pine overlay for the latest pivot on this day.

    Mirrors `/api/forecasts/{symbol}/{date}/{stage}/pine` — writes the .pine
    into `pine/generated/` and returns it as a file attachment so the UI
    can offer a Download button."""
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")
    pivot_jf = _latest_pivot_path(symbol, date)
    if not pivot_jf:
        raise HTTPException(404, "no pivot forecast for this day")
    try:
        data = json.loads(pivot_jf.read_text())
    except Exception as e:
        raise HTTPException(500, f"pivot json malformed: {e}")

    from tv_automation.pivot_pine import render_pivot_pine
    pine_text = render_pivot_pine(data)

    pine_dir = (Path(__file__).parent / "pine" / "generated").resolve()
    pine_dir.mkdir(parents=True, exist_ok=True)
    stage = data.get("stage", "pivot")
    pine_path = pine_dir / f"pivot_overlay_{date}_{stage}.pine"
    pine_path.write_text(pine_text)
    return Response(
        content=pine_text,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{pine_path.name}"'},
    )


@app.post("/api/forecasts/{symbol}/{date}/pivot/apply")
async def forecast_pivot_apply(
    symbol: str, date: str, payload: dict | None = None,
) -> dict:
    """Render the pivot Pine + push it to the TradingView chart via the
    apply_pine.py subprocess. Long-running (~30-60s). Applies to
    whatever layout is currently active."""
    _check_not_paused()
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date):
        raise HTTPException(400, "invalid params")
    pivot_jf = _latest_pivot_path(symbol, date)
    if not pivot_jf:
        raise HTTPException(404, "no pivot forecast for this day")
    try:
        data = json.loads(pivot_jf.read_text())
    except Exception as e:
        raise HTTPException(500, f"pivot json malformed: {e}")

    from tv_automation.pivot_pine import render_pivot_pine
    pine_text = render_pivot_pine(data)

    pine_dir = (Path(__file__).parent / "pine" / "generated").resolve()
    pine_dir.mkdir(parents=True, exist_ok=True)
    stage = data.get("stage", "pivot")
    pine_path = pine_dir / f"pivot_overlay_{date}_{stage}.pine"
    pine_path.write_text(pine_text)

    import subprocess
    apply_script = Path(__file__).parent / "apply_pine.py"
    venv_python = Path(__file__).parent / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else "python"
    cmd = [python_exe, str(apply_script), str(pine_path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(Path(__file__).parent),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        ok = proc.returncode == 0
        stdout_text = stdout.decode("utf-8", errors="replace")
        applied_screenshot = None
        for line in stdout_text.splitlines():
            if line.startswith("APPLIED_SCREENSHOT:"):
                applied_screenshot = line.split(":", 1)[1].strip()
                break
        return {
            "ok": ok,
            "pine_path": str(pine_path),
            "returncode": proc.returncode,
            "applied_screenshot": applied_screenshot,
            "stdout_tail": stdout_text[-1500:],
            "stderr_tail": stderr.decode("utf-8", errors="replace")[-1500:],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "pine_path": str(pine_path),
                "error": "apply_pine timeout (120s)"}
    except Exception as e:
        raise HTTPException(500, f"apply_pine failed: {type(e).__name__}: {e}")


@app.post("/api/forecasts/pivot")
async def forecast_pivot_start(payload: dict) -> dict:
    """Run an intraday pivot re-forecast for today. Fires when the pre-
    session's invalidation condition has broken — gives the trader a
    fresh read (REVERSAL / FLAT / SHAKEOUT) from a state the original
    thesis didn't anticipate.

    Body: {symbol?: "MNQ1", reason?: "broke 26964 on 8.3x vol at 13:02"}
    Returns {task_id, request_id}. Status polled via the same
    /api/forecasts/runs/{task_id} endpoint as other forecast runs."""
    global _active_forecast_run
    p = payload or {}
    symbol = (p.get("symbol") or "MNQ1").strip()
    reason = (p.get("reason") or "").strip() or None

    if not _PROFILE_SYMBOL_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")

    _check_not_paused()
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _forecast_run_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "symbol": symbol, "reason": reason, "kind": "pivot",
    }

    async def runner():
        global _active_forecast_run
        try:
            from tv_automation.pivot_forecast import run_pivot
            result = await run_pivot(symbol=symbol, reason=reason)
            _forecast_run_tasks[task_id]["state"] = "done"
            _forecast_run_tasks[task_id]["result"] = result
        except Exception as e:
            _forecast_run_tasks[task_id]["state"] = "failed"
            _forecast_run_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _forecast_run_tasks[task_id]["finished_at"] = time.time()
            if _active_forecast_run == task_id:
                _active_forecast_run = None

    _active_forecast_run = task_id
    asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.post("/api/forecasts/reconcile")
async def forecast_reconcile_start(payload: dict) -> dict:
    """Run standalone reconciliation for one day — grade saved forecast
    stages against the completed-day profile. No Bar Replay needed.

    Body: {date: "YYYY-MM-DD", symbol?: "MNQ1"}
    Returns {task_id, request_id}; poll the same /api/forecasts/runs/{task_id}
    + /api/audit/tail endpoints used by the full run."""
    global _active_forecast_run
    p = payload or {}
    date = (p.get("date") or "").strip()
    symbol = (p.get("symbol") or "MNQ1").strip()

    if not _PROFILE_DATE_RX.match(date):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if not _PROFILE_SYMBOL_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")

    _check_not_paused()
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _forecast_run_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "date": date, "symbol": symbol, "kind": "reconcile",
    }

    async def runner():
        global _active_forecast_run
        try:
            from tv_automation.forecast_reconcile import run_reconciliation
            result = await run_reconciliation(symbol=symbol, date_str=date)
            _forecast_run_tasks[task_id]["state"] = "done"
            _forecast_run_tasks[task_id]["result"] = result
        except Exception as e:
            _forecast_run_tasks[task_id]["state"] = "failed"
            _forecast_run_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _forecast_run_tasks[task_id]["finished_at"] = time.time()
            if _active_forecast_run == task_id:
                _active_forecast_run = None

    _active_forecast_run = task_id
    asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.post("/api/forecasts/pre_session")
async def forecast_pre_session_start(payload: dict) -> dict:
    """Run the pre-session forecast for a given date (default: today).

    Body: {date?: "YYYY-MM-DD", symbol?: "MNQ1"}
    Returns {task_id, request_id}. Poll /api/forecasts/runs/{task_id}
    and /api/audit/tail?request_id=... as usual."""
    global _active_forecast_run
    p = payload or {}
    date = (p.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
    symbol = (p.get("symbol") or "MNQ1").strip()

    if not _PROFILE_DATE_RX.match(date):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if not _PROFILE_SYMBOL_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")

    _check_not_paused()
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _forecast_run_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "date": date, "symbol": symbol, "kind": "pre_session",
    }

    async def runner():
        global _active_forecast_run
        try:
            from tv_automation.pre_session_forecast import run_pre_session
            result = await run_pre_session(symbol=symbol, date_str=date)
            _forecast_run_tasks[task_id]["state"] = "done"
            _forecast_run_tasks[task_id]["result"] = result
        except Exception as e:
            _forecast_run_tasks[task_id]["state"] = "failed"
            _forecast_run_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _forecast_run_tasks[task_id]["finished_at"] = time.time()
            if _active_forecast_run == task_id:
                _active_forecast_run = None

    _active_forecast_run = task_id
    asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.post("/api/forecasts/live")
async def forecast_live_stage_start(payload: dict) -> dict:
    """Run one live forecast stage (F1/F2/F3) against the LIVE chart.

    Body: {stage: "F1"|"F2"|"F3", date?: "YYYY-MM-DD", symbol?: "MNQ1", force?: bool}
    Returns {task_id, request_id}. `force=true` bypasses the >30 min
    staleness guard (useful when re-running by hand a few minutes late)."""
    global _active_forecast_run
    p = payload or {}
    stage = (p.get("stage") or "").strip().upper()
    date = (p.get("date") or "").strip() or None
    symbol = (p.get("symbol") or "MNQ1").strip()
    force = bool(p.get("force", False))

    if stage not in ("F1", "F2", "F3"):
        raise HTTPException(400, "stage must be F1, F2, or F3")
    if date and not _PROFILE_DATE_RX.match(date):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if not _PROFILE_SYMBOL_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")

    _check_not_paused()
    busy = _cdp_busy()
    if busy:
        raise HTTPException(409, {
            "detail": f"another {busy['kind']} run is in progress", **busy,
        })

    _prune_act_tasks()
    task_id = secrets.token_hex(6)
    request_id = audit.new_request_id()
    audit.current_request_id.set(request_id)

    _forecast_run_tasks[task_id] = {
        "state": "running",
        "request_id": request_id,
        "started_at": time.time(),
        "stage": stage, "date": date, "symbol": symbol,
        "kind": f"live_{stage.lower()}",
    }

    async def runner():
        global _active_forecast_run
        try:
            from tv_automation.live_forecast import run_live_stage
            result = await run_live_stage(
                stage, symbol=symbol, date_str=date, force=force,
            )
            _forecast_run_tasks[task_id]["state"] = "done"
            _forecast_run_tasks[task_id]["result"] = result
        except Exception as e:
            _forecast_run_tasks[task_id]["state"] = "failed"
            _forecast_run_tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            _forecast_run_tasks[task_id]["finished_at"] = time.time()
            if _active_forecast_run == task_id:
                _active_forecast_run = None

    _active_forecast_run = task_id
    asyncio.create_task(runner())
    return {"task_id": task_id, "request_id": request_id}


@app.get("/api/forecasts/calibration")
async def forecasts_calibration(min_n: int = 2) -> dict:
    """Per-pattern accuracy across all reconciliations.

    Returns the model's track record by predicted tag value (direction,
    structure, open_type, etc.) so the user can see *which* prediction
    patterns to weight more or less. Defaults to filtering out
    one-off occurrences (min_n=2) to focus on patterns with signal."""
    from tv_automation.lessons import collect_calibration
    stats = collect_calibration(min_occurrences=max(1, min_n))
    # Group by field for the UI's "by-dimension" rendering.
    by_field: dict[str, list[dict]] = {}
    for s in stats:
        by_field.setdefault(s.field, []).append({
            "value": s.value,
            "correct": s.correct,
            "wrong": s.wrong,
            "total": s.total,
            "pct": round(s.pct_correct * 100),
            "sources": s.sources,
        })
    # Sort each field's list by total desc.
    for fld in by_field:
        by_field[fld].sort(key=lambda x: x["total"], reverse=True)
    return {
        "min_occurrences": max(1, min_n),
        "by_field": by_field,
        "total_patterns": len(stats),
    }


@app.get("/api/forecasts/lessons")
async def forecasts_lessons(n: int = 20) -> dict:
    """Aggregate `lessons[]` from all reconciliation JSONs, deduped + ranked.

    Defined BEFORE the more general `/api/forecasts/{symbol}/{date}/{stage}`
    route so FastAPI's path-matching doesn't try to interpret "lessons"
    as a symbol value."""
    from tv_automation.lessons import collect_lessons, to_dicts
    lessons = collect_lessons()
    return {
        "count_unique": len(lessons),
        "count_reconciliations": len(list(_FORECASTS_ROOT.glob("*_reconciliation.json"))) if _FORECASTS_ROOT.exists() else 0,
        "lessons": to_dicts(lessons[:n]),
    }


@app.get("/api/forecasts")
async def forecasts_list() -> dict:
    """Group forecasts by date. Each date returns its F1/F2/F3 + reconciliation presence."""
    if not _FORECASTS_ROOT.exists():
        return {"days": []}
    by_date: dict[str, dict] = {}
    for jf in sorted(_FORECASTS_ROOT.glob("*.json")):
        m = _FORECAST_STEM_RX.match(jf.stem)
        if not m:
            continue
        symbol, date, stage = m.group("symbol"), m.group("date"), m.group("stage")
        try:
            data = json.loads(jf.read_text())
        except Exception:
            continue
        key = f"{symbol}|{date}"
        if key not in by_date:
            by_date[key] = {
                "symbol": symbol, "date": date,
                "stages": {}, "has_reconciliation": False,
            }
        # Reconciliation stages: in-session is `reconciliation`; pre-session
        # version is `pre_session_reconciliation`. Both flagged so the UI
        # can show a single "recon ✓" badge per day.
        if stage.endswith("reconciliation"):
            by_date[key]["has_reconciliation"] = True
            by_date[key].setdefault("reconciliation", {}).update({
                stage: {
                    "made_at": data.get("made_at"),
                    "ground_truth_profile": data.get("ground_truth_profile"),
                }
            })
            # Surface accuracy at the day level so the UI can render scores on
            # the calendar + list without an extra fetch. `reconciliation` wins
            # over `pre_session_reconciliation` since the former grades all 4 stages.
            if stage == "reconciliation" or "accuracy" not in by_date[key]:
                grades = data.get("grades") or {}
                scores = [g.get("overall_score") for g in grades.values()
                          if isinstance(g, dict) and isinstance(g.get("overall_score"), (int, float))]
                max_list = [g.get("overall_max") for g in grades.values()
                            if isinstance(g, dict) and isinstance(g.get("overall_max"), (int, float))]
                by_date[key]["accuracy"] = {
                    "actual_summary": data.get("actual_summary"),
                    "grades": grades,
                    "best_score": max(scores) if scores else None,
                    "avg_score": (sum(scores) / len(scores)) if scores else None,
                    "overall_max": max(max_list) if max_list else 7,
                }
        else:
            by_date[key]["stages"][stage] = {
                "cursor_time": data.get("cursor_time"),
                "made_at": data.get("made_at"),
                "gate_ok": (data.get("gate") or {}).get("ok"),
            }
    days = sorted(by_date.values(), key=lambda d: d["date"], reverse=True)
    return {"days": days}


@app.get("/api/forecasts/{symbol}/{date}/{stage}")
async def forecast_get(symbol: str, date: str, stage: str) -> dict:
    """Return a single forecast stage (F1/F2/F3 at cursor HHMM, or reconciliation)."""
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date) or not _FORECAST_STAGE_RX.match(stage):
        raise HTTPException(400, "invalid params")
    stem = f"{symbol}_{date}_{stage}"
    jf = _FORECASTS_ROOT / f"{stem}.json"
    mf = _FORECASTS_ROOT / f"{stem}.md"
    if not jf.exists():
        raise HTTPException(404, "forecast not found")
    return {
        "symbol": symbol, "date": date, "stage": stage,
        "json": json.loads(jf.read_text()),
        "markdown": mf.read_text() if mf.exists() else "",
    }


@app.get("/api/forecasts/{symbol}/{date}/{stage}/pine")
async def forecast_pine(symbol: str, date: str, stage: str):
    """Render a Pine v6 forecast-overlay indicator from a saved forecast JSON.

    Returns the .pine source as plain text. UI fetches this and offers a
    download. Currently only meaningful for `pre_session` stage — intraday
    F1/F2/F3 stages don't have a clear visual analog yet."""
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date) or not _FORECAST_STAGE_RX.match(stage):
        raise HTTPException(400, "invalid params")
    jf = _FORECASTS_ROOT / f"{symbol}_{date}_{stage}.json"
    if not jf.exists():
        raise HTTPException(404, "forecast not found")
    try:
        data = json.loads(jf.read_text())
    except Exception as e:
        raise HTTPException(500, f"forecast json malformed: {e}")
    from tv_automation.forecast_pine import render_pine
    from fastapi.responses import PlainTextResponse
    pine_text = render_pine(data)
    filename = f"forecast_overlay_{date}.pine"
    return PlainTextResponse(
        content=pine_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/forecasts/{symbol}/{date}/{stage}/regenerate")
async def forecast_regenerate(symbol: str, date: str, stage: str) -> dict:
    """Render Pine from the forecast JSON and overwrite
    pine/generated/forecast_overlay_{date}.pine, without applying to chart.

    Use when the template has changed and you want the on-disk file synced
    without paying the ~30-60s Apply subprocess cost."""
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date) or not _FORECAST_STAGE_RX.match(stage):
        raise HTTPException(400, "invalid params")
    jf = _FORECASTS_ROOT / f"{symbol}_{date}_{stage}.json"
    if not jf.exists():
        raise HTTPException(404, "forecast not found")
    try:
        data = json.loads(jf.read_text())
    except Exception as e:
        raise HTTPException(500, f"forecast json malformed: {e}")

    from tv_automation.forecast_pine import render_pine
    pine_text = render_pine(data)
    pine_dir = (Path(__file__).parent / "pine" / "generated").resolve()
    pine_dir.mkdir(parents=True, exist_ok=True)
    pine_path = pine_dir / f"forecast_overlay_{date}.pine"
    pine_path.write_text(pine_text)
    return {"ok": True, "pine_path": str(pine_path), "bytes": len(pine_text)}


@app.post("/api/forecasts/{symbol}/{date}/{stage}/apply")
async def forecast_apply(
    symbol: str, date: str, stage: str, payload: dict | None = None,
) -> dict:
    """Render Pine from the forecast JSON, write to pine/generated/, and
    apply to the TradingView chart via the existing apply_pine.py
    subprocess. Applies to whatever layout is currently active.

    Long-running (~30-60s for the browser-driving Playwright work).
    Blocks until done with a 120s timeout — matches the pattern of
    `/api/analyze/apply-pine`. UI should disable the button while
    waiting."""
    _check_not_paused()
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date) or not _FORECAST_STAGE_RX.match(stage):
        raise HTTPException(400, "invalid params")
    jf = _FORECASTS_ROOT / f"{symbol}_{date}_{stage}.json"
    if not jf.exists():
        raise HTTPException(404, "forecast not found")
    try:
        data = json.loads(jf.read_text())
    except Exception as e:
        raise HTTPException(500, f"forecast json malformed: {e}")

    from tv_automation.forecast_pine import render_pine
    pine_text = render_pine(data)

    # Write to pine/generated/ — that's the directory the apply_pine.py
    # subprocess (and its security model in /api/analyze/apply-pine) trusts.
    pine_dir = (Path(__file__).parent / "pine" / "generated").resolve()
    pine_dir.mkdir(parents=True, exist_ok=True)
    pine_path = pine_dir / f"forecast_overlay_{date}.pine"
    pine_path.write_text(pine_text)

    import subprocess
    apply_script = Path(__file__).parent / "apply_pine.py"
    venv_python = Path(__file__).parent / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else "python"
    cmd = [python_exe, str(apply_script), str(pine_path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(Path(__file__).parent),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        ok = proc.returncode == 0
        stdout_text = stdout.decode("utf-8", errors="replace")
        applied_screenshot = None
        for line in stdout_text.splitlines():
            if line.startswith("APPLIED_SCREENSHOT:"):
                applied_screenshot = line.split(":", 1)[1].strip()
                break
        return {
            "ok": ok,
            "pine_path": str(pine_path),
            "returncode": proc.returncode,
            "applied_screenshot": applied_screenshot,
            "stdout_tail": stdout_text[-1500:],
            "stderr_tail": stderr.decode("utf-8", errors="replace")[-1500:],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "pine_path": str(pine_path),
                "error": "apply_pine timeout (120s)"}
    except Exception as e:
        raise HTTPException(500, f"apply_pine failed: {type(e).__name__}: {e}")


@app.get("/api/forecasts/{symbol}/{date}/{stage}/screenshot")
async def forecast_screenshot(symbol: str, date: str, stage: str):
    """Serve the screenshot for a forecast stage."""
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date) or not _FORECAST_STAGE_RX.match(stage):
        raise HTTPException(400, "invalid params")
    jf = _FORECASTS_ROOT / f"{symbol}_{date}_{stage}.json"
    if not jf.exists():
        raise HTTPException(404)
    data = json.loads(jf.read_text())
    path = data.get("screenshot_path")
    if not path:
        raise HTTPException(404, "no screenshot")
    try:
        resolved = Path(path).resolve()
    except Exception:
        raise HTTPException(400, "invalid path")
    if not any(str(resolved).startswith(str(root)) for root in _IMAGE_ROOTS):
        raise HTTPException(403, "path outside allowed roots")
    if not resolved.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(str(resolved), media_type="image/png")


@app.get("/api/forecasts/{symbol}/{date}/{stage}/speak")
async def forecast_speak(symbol: str, date: str, stage: str, voice: str | None = None):
    """Synthesize a spoken read-aloud of the forecast as 24 kHz WAV.

    Routed through the local Qwen3-TTS sidecar (start with
    ./start_qwen3_tts.sh). Default voice is the Sophia clone; override
    with ?voice=<clone-name> from clones.json. Returns 503 if the
    sidecar isn't running, 422 if the forecast has nothing speakable."""
    if not _PROFILE_KEY_RX.match(symbol) or not _FORECAST_DATE_RX.match(date) or not _FORECAST_STAGE_RX.match(stage):
        raise HTTPException(400, "invalid params")
    jf = _FORECASTS_ROOT / f"{symbol}_{date}_{stage}.json"
    if not jf.exists():
        raise HTTPException(404, "forecast not found")
    try:
        data = json.loads(jf.read_text())
    except Exception as e:
        raise HTTPException(500, f"forecast json malformed: {e}")
    from tv_automation import tts as tts_mod
    script = tts_mod.forecast_script(data, stage, date)
    if not script:
        raise HTTPException(422, "nothing speakable in this forecast")
    try:
        wav = await tts_mod.synthesize(script, voice=voice)
    except tts_mod.TTSUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"tts failed: {e}")
    return Response(content=wav, media_type="audio/wav")


# ---------------------------------------------------------------------------
# Journal — day-arc reconciliation. Closes the loop between every forecast
# stage and the daily profile (the 16:00 ET ground-truth artifact).
# ---------------------------------------------------------------------------


@app.get("/api/journal/{symbol}/{date}")
async def journal_day(symbol: str, date: str) -> dict:
    """Assemble the full forecast → reality chain for one trading day.

    Returns the pre-session forecast, every live forecast (10/12/14),
    any pivots, applied-Pine screenshots, decisions logged in
    decisions.db, and the daily profile — with deterministic per-stage
    grading where possible. Pure read; no LLM calls."""
    if not _PROFILE_KEY_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")
    if not _FORECAST_DATE_RX.match(date):
        raise HTTPException(400, "invalid date (YYYY-MM-DD)")
    from tv_automation import journal as journal_mod
    return journal_mod.assemble_day(symbol, date)


# ---------------------------------------------------------------------------
# Canary thesis — pre-committed morning trip-wires written by the
# pre-session forecast and evaluated on a 5-min cron between 09:00–12:00 ET.
# Soft auto-pause: failing canary engages the kill-switch only when the
# trader has open exposure, so a sit-out morning isn't surprised by a
# pause.
# ---------------------------------------------------------------------------


def _validate_canary_path(symbol: str, date: str) -> None:
    if not _PROFILE_KEY_RX.match(symbol):
        raise HTTPException(400, "invalid symbol")
    if not _FORECAST_DATE_RX.match(date):
        raise HTTPException(400, "invalid date (YYYY-MM-DD)")


@app.get("/api/canary/{symbol}/{date}")
async def canary_status(symbol: str, date: str) -> dict:
    """Return the canary thesis + most recent evaluation status. Empty
    when no pre-session canary exists for this date. Pure read."""
    _validate_canary_path(symbol, date)
    from tv_automation import canary as canary_mod
    canary = canary_mod.load_canary(symbol, date)
    if not canary:
        return {"available": False, "symbol": symbol, "date": date}
    return {
        "available": True,
        "symbol": symbol, "date": date,
        "canary": canary,
        "status": canary_mod.load_status(symbol, date),
    }


@app.post("/api/canary/{symbol}/{date}/evaluate")
async def canary_evaluate(symbol: str, date: str) -> dict:
    """Re-evaluate every canary check whose `evaluate_after` has
    passed against the live chart. Idempotent. Long-ish (~3-5s for
    the chart read); UI should call sparingly. Cron runs this every
    5 min between 09:00 and 12:00 ET."""
    _validate_canary_path(symbol, date)
    _check_not_paused()
    from tv_automation import canary as canary_mod
    from session import tv_context as _tv_context
    async with _tv_context() as ctx:
        page = next((p for p in ctx.pages if "/chart/" in (p.url or "")), None)
        if page is None:
            raise HTTPException(503, "no /chart/ tab attached")
        return await canary_mod.evaluate_canary(page, symbol, date)


@app.post("/api/canary/{symbol}/{date}/snooze/{check_id}")
async def canary_snooze(
    symbol: str, date: str, check_id: str, payload: dict | None = None,
) -> dict:
    """Manually mark one check as ignored. Mandatory `reason` body
    field — the discipline escape hatch that gets logged to audit.
    Re-running evaluation will leave the snoozed check at status
    `snoozed` instead of re-evaluating it. Reading these reasons six
    weeks later is half the calibration value."""
    _validate_canary_path(symbol, date)
    if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", check_id):
        raise HTTPException(400, "invalid check_id")
    p = payload or {}
    reason = (p.get("reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(400, "reason required (≥5 chars)")
    from tv_automation import canary as canary_mod
    status = canary_mod.load_status(symbol, date) or {
        "symbol": symbol, "date": date, "results": [],
    }
    snoozes = status.setdefault("snoozes", {})
    snoozes[check_id] = {
        "snoozed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "reason": reason,
    }
    canary_mod.write_status(symbol, date, status)
    audit.log("canary.snoozed",
              symbol=symbol, date=date,
              check_id=check_id, reason=reason)
    return {"ok": True, "snoozes": snoozes}
