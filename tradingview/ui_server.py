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
from tv_automation import chart as chart_mod
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


@app.middleware("http")
async def guard(request: Request, call_next):
    """CSRF + optional shared-secret guard on /api/* routes.

    * Any non-GET request must carry `X-UI: 1`. A malicious site you
      visit in the same browser cannot set custom headers cross-origin
      without triggering a CORS preflight — which we never respond to
      with Access-Control-Allow-*, so the attack fails.
    * If UI_TOKEN is set in .env, every /api/* request (GET and POST)
      must also match `X-UI-Token`. Constant-time compare.
    * Non-/api/* (HTML, static assets) is unrestricted.
    """
    path = request.url.path
    if path.startswith("/api/"):
        if request.method != "GET":
            if request.headers.get("X-UI") != "1":
                return JSONResponse({"detail": "CSRF: missing X-UI header"}, status_code=403)
        if _UI_TOKEN:
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


def _prune_act_tasks() -> None:
    """Remove finished tasks older than TTL. Called opportunistically on
    each new run rather than via a background sweeper — keeps footprint
    proportional to activity."""
    cutoff = time.time() - _ACT_TASK_TTL_S
    stale = [tid for tid, t in _act_tasks.items()
             if t.get("finished_at") and t["finished_at"] < cutoff]
    for tid in stale:
        _act_tasks.pop(tid, None)


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
    goal = (payload or {}).get("goal", "").strip()
    if not goal:
        raise HTTPException(400, "goal required")

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
# Trade
# ---------------------------------------------------------------------------

@app.post("/api/trade/order")
async def trade_order(payload: dict) -> dict:
    symbol = (payload or {}).get("symbol", "").strip()
    side = (payload or {}).get("side", "").strip().lower()
    qty = int((payload or {}).get("qty", 0))
    dry_run = bool((payload or {}).get("dry_run", False))
    if not symbol or side not in ("buy", "sell") or qty <= 0:
        raise HTTPException(400, "symbol, side=buy|sell, qty>0 required")
    try:
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
