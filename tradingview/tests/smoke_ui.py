#!/usr/bin/env python3
"""Smoke tests for the IntelligenceOS Console UI server.

Run against the live server (default http://127.0.0.1:8788). No external
test framework — pure stdlib. Exits non-zero on any failure.

Usage:
    .venv/bin/python tests/smoke_ui.py
    BASE=http://127.0.0.1:8788 .venv/bin/python tests/smoke_ui.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv("BASE", "http://127.0.0.1:8788")
failures: list[str] = []


def req(method: str, path: str, body: dict | None = None,
        headers: dict | None = None) -> tuple[int, dict | str]:
    url = BASE + path
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        req_headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            text = resp.read().decode()
            try: return resp.status, json.loads(text)
            except Exception: return resp.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try: return e.code, json.loads(text)
        except Exception: return e.code, text


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}{(' — ' + detail) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


print(f"Smoke-testing {BASE}")

# 1. Health endpoints
print("health:")
code, body = req("GET", "/api/health")
check("GET /api/health → 200", code == 200)
check("  body has ok:true", isinstance(body, dict) and body.get("ok") is True)

code, body = req("GET", "/api/health/browser")
check("GET /api/health/browser → 200", code == 200)
check("  body has ok field", isinstance(body, dict) and "ok" in body)

# 2. CSRF: POST without X-UI header must be rejected.
print("csrf guard:")
code, body = req("POST", "/api/chart/screenshot", body={"area": "chart"})
check("POST without X-UI → 403", code == 403,
      detail=f"got {code} {body!r}")
check("  body mentions CSRF",
      isinstance(body, dict) and "csrf" in str(body.get("detail", "")).lower())

# 3. CSRF: POST WITH header is accepted (wiring works end-to-end).
#    We avoid browser-touching calls in the default smoke suite since
#    they require TradingView to be signed in.
code, body = req("POST", "/api/alerts/create", body={}, headers={"X-UI": "1"})
check("POST /api/alerts/create with X-UI, missing fields → 400",
      code == 400, detail=f"got {code}")

# 4. GET endpoints that don't hit the browser:
print("read-only routes:")
code, body = req("GET", "/api/audit/tail?n=3")
check("GET /api/audit/tail → 200", code == 200)
check("  body.entries is a list",
      isinstance(body, dict) and isinstance(body.get("entries"), list))

# 5. Static HTML root is served.
print("static:")
code, body = req("GET", "/")
check("GET / → 200", code == 200)
check("  body starts with <!DOCTYPE html>",
      isinstance(body, str) and body.lstrip().lower().startswith("<!doctype html>"))

# 6. OpenAPI is populated.
code, body = req("GET", "/openapi.json")
check("GET /openapi.json → 200", code == 200)
paths = (body or {}).get("paths") if isinstance(body, dict) else {}
expected = [
    "/api/health", "/api/health/browser",
    "/api/chart/metadata", "/api/chart/screenshot",
    "/api/act", "/api/trade/order", "/api/trade/close",
    "/api/watchlist", "/api/alerts", "/api/alerts/create",
    "/api/audit/tail",
]
for p in expected:
    check(f"  route registered: {p}", p in paths)

# 7. UI_TOKEN wiring — if server was started with UI_TOKEN set, GETs
#    without the token must fail. Skip if the env var isn't set.
if os.getenv("UI_TOKEN"):
    code, _ = req("GET", "/api/health")
    check("UI_TOKEN set: GET without token → 401", code == 401)
    code, _ = req("GET", "/api/health", headers={"X-UI-Token": os.getenv("UI_TOKEN", "")})
    check("UI_TOKEN set: GET with correct token → 200", code == 200)

print("\n" + ("FAIL: " + ", ".join(failures) if failures else "all smoke tests passed"))
sys.exit(1 if failures else 0)
