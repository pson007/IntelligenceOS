"""Canary thesis — pre-committed morning trip-wires.

A canary is a small set (3–5) of falsifiable observations the chart
must satisfy by mid-morning for the pre-session bias to remain
actionable. Pre-session forecast emits the canary block at 08:30 ET;
this module evaluates each check against the live chart at the
pre-committed evaluate_at timestamps and emits an aggregate state
the UI surfaces in the session bar.

Architecture goals:

  * Every check is binary (pass | fail | not_yet_evaluable |
    evaluate_failed) — no fuzzy "partial." Aggregation across multiple
    weighted checks gives the partial state.
  * Status writes are idempotent — `forecasts/{symbol}_{date}_canary
    _status.json`. Re-evaluating a check whose `evaluate_after` has
    passed overwrites the entry; re-evaluating before that passes
    no-ops with `not_yet_evaluable`.
  * No LLM calls. The whole evaluation pipeline is deterministic
    against TV's chart API.
  * Soft auto-pause — if `auto_pause_if_failing` is true AND the
    aggregate state just transitioned into `failing` AND there's an
    open position (read from trading.positions()), engage the
    workspace kill-switch with reason "canary failed: <ids>". Pure
    state-driven: re-running evaluation while still failing is a
    no-op, the pause only fires on the transition edge.

Check types implemented in this commit:
  - price_level   (price_above / price_below at evaluate_at)

Coming in subsequent commits:
  - price_level_window  (low/high of HH:MM–HH:MM window vs threshold)
  - open_pattern        (5-bar open classification)
  - vwap_relationship   (close above/below/at session VWAP)
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from playwright.async_api import Page

from .lib import audit


_FORECASTS_DIR = (Path(__file__).parent.parent / "forecasts").resolve()
_ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


def _canary_path(symbol: str, date: str) -> Path:
    return _FORECASTS_DIR / f"{symbol}_{date}_canary.json"


def _canary_status_path(symbol: str, date: str) -> Path:
    return _FORECASTS_DIR / f"{symbol}_{date}_canary_status.json"


def load_canary(symbol: str, date: str) -> dict | None:
    """Return the canary thesis written by the pre-session forecast,
    or None if absent (no pre-session run yet, or pre-session ran
    against a model that didn't emit a canary block)."""
    p = _canary_path(symbol, date)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:
        audit.log("canary.load_fail", path=str(p), err=str(e))
        return None


def load_status(symbol: str, date: str) -> dict | None:
    p = _canary_status_path(symbol, date)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def write_status(symbol: str, date: str, status: dict) -> None:
    _FORECASTS_DIR.mkdir(parents=True, exist_ok=True)
    _canary_status_path(symbol, date).write_text(json.dumps(status, indent=2))


# ---------------------------------------------------------------------------
# Chart reads — pure thin wrappers around TV's main-series bars buffer.
# ---------------------------------------------------------------------------


async def _latest_bar(page: Page) -> dict | None:
    """Return {time_epoch, open, high, low, close} for the most recent
    bar on the active chart, or None if the bars buffer isn't
    readable. Doesn't engage Replay — assumes live chart."""
    try:
        result = await page.evaluate(
            r"""() => {
              try {
                const c = window.TradingViewApi
                  && window.TradingViewApi._activeChartWidgetWV
                  && window.TradingViewApi._activeChartWidgetWV.value();
                if (!c) return null;
                const b = c._chartWidget.model().mainSeries().bars();
                if (!b) return null;
                const li = b.lastIndex();
                const v = b.valueAt(li);
                if (!v) return null;
                return {
                  time_epoch: v[0],
                  open: v[1], high: v[2], low: v[3], close: v[4],
                };
              } catch (e) { return null; }
            }"""
        )
        return result
    except Exception as e:
        audit.log("canary.latest_bar.eval_fail", err=str(e))
        return None


async def _bars_in_window(
    page: Page, start_epoch: int, end_epoch: int,
) -> list[dict] | None:
    """Return [{time_epoch, open, high, low, close}, ...] for every bar
    whose timestamp is in [start_epoch, end_epoch). None on read
    failure; empty list when no bars match (window outside loaded
    history). Used by `price_level_window` and `open_pattern`."""
    try:
        return await page.evaluate(
            r"""(args) => {
              try {
                const c = window.TradingViewApi
                  && window.TradingViewApi._activeChartWidgetWV
                  && window.TradingViewApi._activeChartWidgetWV.value();
                if (!c) return null;
                const b = c._chartWidget.model().mainSeries().bars();
                if (!b) return null;
                const lo = b.firstIndex();
                const hi = b.lastIndex();
                const out = [];
                for (let i = lo; i <= hi; i++) {
                  const v = b.valueAt(i);
                  if (!v) continue;
                  if (v[0] < args.start) continue;
                  if (v[0] >= args.end) break;
                  out.push({
                    time_epoch: v[0],
                    open: v[1], high: v[2], low: v[3], close: v[4],
                  });
                }
                return out;
              } catch (e) { return null; }
            }""",
            {"start": start_epoch, "end": end_epoch},
        )
    except Exception as e:
        audit.log("canary.bars_in_window.eval_fail", err=str(e))
        return None


async def _vwap_value(page: Page) -> float | None:
    """Read the current session VWAP from any VWAP study on the chart.
    Returns None if no VWAP indicator is present or its lastValueData
    isn't available (which is the Replay-mode caveat — but canary
    runs on live chart, so this is fine)."""
    try:
        items = await page.evaluate(
            r"""() => {
              try {
                const c = window.TradingViewApi
                  && window.TradingViewApi._activeChartWidgetWV
                  && window.TradingViewApi._activeChartWidgetWV.value();
                if (!c) return null;
                if (typeof c.dataWindowView === 'function') {
                  const dwv = c.dataWindowView();
                  if (dwv && typeof dwv.items === 'function') {
                    const items = dwv.items();
                    if (Array.isArray(items)) {
                      return items.map(g => ({
                        title: g.title || g.name || '',
                        values: (g.values || []).map(v => ({
                          name: v.name || '',
                          value: (v.value && v.value.value !== undefined)
                                  ? v.value.value : v.value,
                        })),
                      }));
                    }
                  }
                }
                return [];
              } catch (e) { return []; }
            }"""
        )
        if not items:
            return None
        for g in items:
            title = (g.get("title") or "").lower()
            if "vwap" in title:
                for v in (g.get("values") or []):
                    name = (v.get("name") or "").lower()
                    if name == "" or "vwap" in name or name == "vwap":
                        val = v.get("value")
                        if isinstance(val, (int, float)):
                            return float(val)
        return None
    except Exception as e:
        audit.log("canary.vwap.eval_fail", err=str(e))
        return None


_HHMM_RX = __import__("re").compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


def _window_to_epochs(window: str | None, date_str: str) -> tuple[int, int] | None:
    """Convert "HH:MM-HH:MM" + date string → (start_epoch, end_epoch)
    in ET-relative seconds. None if the window isn't parseable."""
    if not window or not isinstance(window, str):
        return None
    m = _HHMM_RX.match(window.strip())
    if not m:
        return None
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    start = datetime(d.year, d.month, d.day, h1, m1, 0, tzinfo=_ET)
    end = datetime(d.year, d.month, d.day, h2, m2, 0, tzinfo=_ET)
    return (int(start.timestamp()), int(end.timestamp()))


# ---------------------------------------------------------------------------
# Per-check evaluators. Each returns the same shape:
#   {id, status, evidence, evaluated_at}
# Status semantics:
#   pass               — check satisfied
#   fail               — check disproven
#   not_yet_evaluable  — `evaluate_after` hasn't passed yet
#   evaluate_failed    — the chart read itself failed (no bars, API
#                        not exposed, malformed params, etc.)
# Evidence is a small dict that explains *why* — actual price seen,
# threshold, timestamp. Logged to audit and surfaced in the UI.
# ---------------------------------------------------------------------------


def _now_iso_et() -> str:
    return datetime.now(_ET).strftime("%Y-%m-%dT%H:%M:%S%z")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


async def _eval_price_level(page: Page, check: dict) -> dict:
    """`price_level` check — pass when latest close satisfies the
    inequality. Params: {price_above: N} or {price_below: N}."""
    params = check.get("params") or {}
    above = params.get("price_above")
    below = params.get("price_below")
    if above is None and below is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "no price_above or price_below in params"}}

    bar = await _latest_bar(page)
    if not bar:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "could not read latest bar"}}

    close = bar.get("close")
    if close is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "latest bar has no close",
                             "bar": bar}}

    if above is not None:
        passed = close > above
        return {
            "status": "pass" if passed else "fail",
            "evidence": {"close": close, "threshold": above,
                         "comparison": ">", "bar_time_epoch": bar.get("time_epoch")},
        }
    passed = close < below
    return {
        "status": "pass" if passed else "fail",
        "evidence": {"close": close, "threshold": below,
                     "comparison": "<", "bar_time_epoch": bar.get("time_epoch")},
    }


async def _eval_price_level_window(page: Page, check: dict) -> dict:
    """`price_level_window` — pass when the window's extreme respects
    the threshold. Two flavors:
      params: { window: "HH:MM-HH:MM",
                low_of_window_above: N }   — low > N (no break)
      params: { window: "HH:MM-HH:MM",
                high_of_window_below: N }  — high < N (no break)"""
    params = check.get("params") or {}
    window = params.get("window")
    low_above = params.get("low_of_window_above")
    high_below = params.get("high_of_window_below")
    if low_above is None and high_below is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "params missing low_of_window_above or high_of_window_below"}}

    # Date for window resolution comes from `evaluate_after`.
    eval_after = _parse_iso(check.get("evaluate_after"))
    if eval_after is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "no evaluate_after to derive date"}}
    date_str = eval_after.strftime("%Y-%m-%d")

    epochs = _window_to_epochs(window, date_str)
    if epochs is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "could not parse window",
                             "window": window}}

    bars = await _bars_in_window(page, epochs[0], epochs[1])
    if bars is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "bars read failed"}}
    if not bars:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "no bars in window",
                             "window": window, "n_bars": 0}}

    if low_above is not None:
        actual_low = min(b["low"] for b in bars)
        passed = actual_low > low_above
        return {
            "status": "pass" if passed else "fail",
            "evidence": {"actual_low": actual_low, "threshold": low_above,
                         "comparison": ">", "window": window,
                         "n_bars": len(bars)},
        }
    actual_high = max(b["high"] for b in bars)
    passed = actual_high < high_below
    return {
        "status": "pass" if passed else "fail",
        "evidence": {"actual_high": actual_high, "threshold": high_below,
                     "comparison": "<", "window": window,
                     "n_bars": len(bars)},
    }


def _classify_open_pattern(bars: list[dict]) -> str:
    """Classify the first ~5 bars (09:30–09:35) into one of:
       dip_then_reclaim | rotational_open | trend_break_up |
       trend_break_down | gap_and_go | inside_bar_open

    Heuristic, not perfect — matches the labels the LLM is asked to
    use in the canary's `tolerated` list. The thresholds are tuned
    for MNQ (1-min bars span 10–60 pts in a normal session)."""
    if not bars:
        return "no_bars"
    open_p = bars[0]["open"]
    high = max(b["high"] for b in bars)
    low = min(b["low"] for b in bars)
    last_close = bars[-1]["close"]
    rng = high - low
    if rng <= 0:
        return "inside_bar_open"

    up_thrust = (high - open_p) / rng
    down_thrust = (open_p - low) / rng
    drift_up = (last_close - open_p) >= 0
    drift_down = (last_close - open_p) <= 0

    # Bar-by-bar — was there a dip (low set in first 1-2 bars)
    # followed by a reclaim (later bars made higher highs)?
    low_idx = min(range(len(bars)), key=lambda i: bars[i]["low"])
    high_idx = max(range(len(bars)), key=lambda i: bars[i]["high"])

    # Classification priority:
    if low_idx < high_idx and drift_up and down_thrust > 0.3:
        return "dip_then_reclaim"
    if high_idx < low_idx and drift_down and up_thrust > 0.3:
        return "dip_then_reclaim"  # mirror — should be "rip_then_reject" but using same label
    if drift_up and up_thrust > 0.7 and down_thrust < 0.2:
        return "trend_break_up"
    if drift_down and down_thrust > 0.7 and up_thrust < 0.2:
        return "trend_break_down"
    if up_thrust > 0.4 and down_thrust > 0.4:
        return "rotational_open"
    if drift_up and up_thrust > 0.5:
        return "gap_and_go"
    if rng < 0.1 * abs(open_p) * 0.001 + 5:  # very small range
        return "inside_bar_open"
    return "rotational_open"


async def _eval_open_pattern(page: Page, check: dict) -> dict:
    """`open_pattern` — classify the 09:30–09:35 5-bar print and
    pass if the classification is in the `tolerated` list."""
    params = check.get("params") or {}
    expected = params.get("expected")
    tolerated = params.get("tolerated") or ([expected] if expected else [])
    if not tolerated:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "no tolerated list in params"}}

    eval_after = _parse_iso(check.get("evaluate_after"))
    if eval_after is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "no evaluate_after"}}
    date_str = eval_after.strftime("%Y-%m-%d")

    # 09:30–09:35 (5 minutes, 5 bars on 1m TF).
    epochs = _window_to_epochs("09:30-09:35", date_str)
    if epochs is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "could not derive open window"}}
    bars = await _bars_in_window(page, epochs[0], epochs[1])
    if not bars:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "no bars in 09:30-09:35 window",
                             "n_bars": 0 if bars == [] else None}}

    classification = _classify_open_pattern(bars)
    passed = classification in tolerated
    return {
        "status": "pass" if passed else "fail",
        "evidence": {
            "observed": classification,
            "expected": expected,
            "tolerated": tolerated,
            "n_bars": len(bars),
        },
    }


async def _eval_vwap_relationship(page: Page, check: dict) -> dict:
    """`vwap_relationship` — pass when latest close is on the named
    side of session VWAP. params: {side: "above"|"below"|"at"}.
    The "at" tolerance is 2 ticks (0.5 pts on MNQ).

    Requires a VWAP study to be on the chart. Otherwise the read
    fails — visible to the user as `evaluate_failed`, with the fix
    being "add VWAP to your active layout."""
    params = check.get("params") or {}
    side = (params.get("side") or "").lower()
    if side not in ("above", "below", "at"):
        return {"status": "evaluate_failed",
                "evidence": {"reason": "side must be above/below/at",
                             "side": params.get("side")}}

    bar = await _latest_bar(page)
    if not bar or bar.get("close") is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "could not read latest bar"}}
    close = bar["close"]

    vwap = await _vwap_value(page)
    if vwap is None:
        return {"status": "evaluate_failed",
                "evidence": {"reason": "no VWAP indicator on chart "
                                       "or value unavailable"}}

    delta = close - vwap
    if side == "above":
        passed = delta > 0
    elif side == "below":
        passed = delta < 0
    else:  # at — within 2 ticks (0.5 pts on MNQ)
        passed = abs(delta) <= 0.5

    return {
        "status": "pass" if passed else "fail",
        "evidence": {
            "close": close, "vwap": round(vwap, 2),
            "delta": round(delta, 2),
            "side_required": side,
        },
    }


_EVALUATORS = {
    "price_level": _eval_price_level,
    "price_level_window": _eval_price_level_window,
    "open_pattern": _eval_open_pattern,
    "vwap_relationship": _eval_vwap_relationship,
}


async def evaluate_check(page: Page, check: dict) -> dict:
    """Evaluate one check against the live chart. Always returns a
    dict of shape {id, status, evidence, evaluated_at} — never raises.

    Honors the check's `evaluate_after` window: returns
    `not_yet_evaluable` when now < evaluate_after, regardless of
    chart state. (We don't fail-evaluate before the deadline because
    early data is often misleading — the canary's whole point is to
    commit to a *time* of judgment, not a hair-trigger.)"""
    cid = check.get("id") or "unknown"
    eval_after = _parse_iso(check.get("evaluate_after"))
    now = datetime.now(_ET)
    if eval_after and now < eval_after:
        return {
            "id": cid, "status": "not_yet_evaluable",
            "evidence": {"evaluate_after": check.get("evaluate_after"),
                         "now": _now_iso_et()},
            "evaluated_at": _now_iso_et(),
        }

    fn = _EVALUATORS.get(check.get("check_type"))
    if fn is None:
        return {
            "id": cid, "status": "evaluate_failed",
            "evidence": {"reason": "unknown check_type",
                         "check_type": check.get("check_type")},
            "evaluated_at": _now_iso_et(),
        }

    try:
        result = await fn(page, check)
    except Exception as e:
        result = {"status": "evaluate_failed",
                  "evidence": {"reason": "evaluator raised",
                               "err": f"{type(e).__name__}: {e}"}}

    return {
        "id": cid,
        "status": result.get("status", "evaluate_failed"),
        "evidence": result.get("evidence") or {},
        "evaluated_at": _now_iso_et(),
    }


# ---------------------------------------------------------------------------
# Aggregation — turn a list of per-check results into one state label
# the UI / kill-switch can act on.
# ---------------------------------------------------------------------------


def _aggregate(canary: dict, results: list[dict]) -> dict:
    """Compute the aggregate state from per-check results.

    Weighted: each check's `weight` (default 1) is added to the
    numerator if it passed and to the denominator regardless of
    status, EXCEPT `not_yet_evaluable` which is counted in
    `pending_weight` but not in either of the others. This way an
    incomplete morning never falls into `failing` purely because
    we haven't reached the 12:00 deadline yet."""
    by_id = {r["id"]: r for r in results}
    pass_w = 0
    fail_w = 0
    pending_w = 0
    failed_w = 0
    snoozed_w = 0
    failing_ids: list[str] = []
    for c in canary.get("checks") or []:
        cid = c.get("id")
        w = int(c.get("weight") or 1)
        r = by_id.get(cid)
        if r is None:
            pending_w += w
            continue
        s = r.get("status")
        if s == "pass":
            pass_w += w
        elif s == "fail":
            fail_w += w
            failing_ids.append(cid)
        elif s == "not_yet_evaluable":
            pending_w += w
        elif s == "snoozed":
            # Snoozed checks are excluded from the score entirely —
            # they don't help, hurt, or count toward the denominator.
            snoozed_w += w
        else:  # evaluate_failed
            failed_w += w

    decided_w = pass_w + fail_w  # weight for which we have a verdict
    total_w = decided_w + pending_w + failed_w
    pass_ratio = (pass_w / decided_w) if decided_w else None

    # State derivation:
    #   passing  — every decided check passed AND nothing is pending
    #   failing  — pass ratio < 50% across decided checks
    #   partial  — 50% ≤ pass ratio < 100%, or some checks still pending
    #   pending  — nothing decided yet
    if decided_w == 0:
        state = "pending"
    elif pass_ratio is not None and pass_ratio < 0.5:
        state = "failing"
    elif pending_w > 0 or pass_ratio < 1.0:
        state = "partial"
    else:
        state = "passing"

    # Recommended action — uses the canary's pre-committed mapping.
    action_map = {
        "passing": canary.get("default_action_if_passing") or "trade_full_size",
        "partial": canary.get("default_action_if_partial") or "trade_half_size",
        "failing": canary.get("default_action_if_failing") or "stand_down",
        "pending": "wait",
    }

    return {
        "state": state,
        "recommended_action": action_map.get(state, "wait"),
        "pass_weight": pass_w,
        "fail_weight": fail_w,
        "pending_weight": pending_w,
        "evaluate_failed_weight": failed_w,
        "snoozed_weight": snoozed_w,
        "total_weight": total_w,
        "pass_ratio": pass_ratio,
        "failing_check_ids": failing_ids,
    }


# ---------------------------------------------------------------------------
# Top-level — evaluate every check, write status, optionally engage
# soft auto-pause via the kill-switch.
# ---------------------------------------------------------------------------


async def _has_open_position() -> bool:
    """For soft auto-pause: only engage the kill-switch if the trader
    has open exposure right now. Reads via tv_automation.trading."""
    try:
        from . import trading
        pos = await trading.positions()
        rows = pos.get("positions") or []
        return len(rows) > 0
    except Exception as e:
        audit.log("canary.position_read_fail", err=str(e))
        # Fail-safe: if we can't tell, treat as no exposure → don't
        # auto-pause. Users who want hard auto-pause can re-evaluate
        # this default after seeing a few weeks of canary data.
        return False


def _engage_pause_if_needed(
    *, prev_state: str | None, new_state: str, failing_ids: list[str],
    has_open_position: bool, auto_pause_if_failing: bool,
) -> dict | None:
    """Soft auto-pause — fires only on the *transition edge* into
    failing AND when there's open exposure. Returns the kill-switch
    payload that was written, or None if no action taken."""
    if not auto_pause_if_failing:
        return None
    if new_state != "failing":
        return None
    if prev_state == "failing":
        # Already failing on the prior evaluation — don't re-engage.
        return None
    if not has_open_position:
        audit.log("canary.auto_pause.skipped",
                  reason="no_open_position", failing_ids=failing_ids)
        return None

    # Engage the workspace kill-switch directly — same flag file
    # ui_server.py reads.
    state_dir = Path(__file__).parent.parent / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    flag_path = state_dir / "paused.json"
    if flag_path.exists():
        # Already paused for some other reason — don't overwrite.
        audit.log("canary.auto_pause.skipped",
                  reason="already_paused", failing_ids=failing_ids)
        return None
    payload = {
        "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "reason": f"canary failed: {', '.join(failing_ids)}",
    }
    flag_path.write_text(json.dumps(payload, indent=2))
    audit.log("canary.auto_paused", **payload)
    return payload


async def evaluate_canary(
    page: Page, symbol: str, date: str,
) -> dict:
    """Top-level orchestration. Loads canary, evaluates every check
    whose deadline has arrived, writes status, fires soft auto-pause
    if needed. Idempotent — call as often as you like."""
    canary = load_canary(symbol, date)
    if not canary:
        return {"ok": False, "reason": "no_canary",
                "symbol": symbol, "date": date}

    prev_status = load_status(symbol, date) or {}
    prev_state = (prev_status.get("aggregate") or {}).get("state")
    snoozes = prev_status.get("snoozes") or {}

    results: list[dict] = []
    for check in canary.get("checks") or []:
        cid = check.get("id")
        if cid in snoozes:
            results.append({
                "id": cid,
                "status": "snoozed",
                "evidence": {
                    "snoozed_at": snoozes[cid].get("snoozed_at"),
                    "reason": snoozes[cid].get("reason"),
                },
                "evaluated_at": _now_iso_et(),
            })
            continue
        results.append(await evaluate_check(page, check))

    aggregate = _aggregate(canary, results)
    new_state = aggregate["state"]

    pause_payload = None
    if aggregate["failing_check_ids"]:
        has_open = await _has_open_position()
        pause_payload = _engage_pause_if_needed(
            prev_state=prev_state,
            new_state=new_state,
            failing_ids=aggregate["failing_check_ids"],
            has_open_position=has_open,
            auto_pause_if_failing=bool(canary.get("auto_pause_if_failing")),
        )

    status = {
        "symbol": symbol,
        "date": date,
        "evaluated_at": _now_iso_et(),
        "aggregate": aggregate,
        "results": results,
        "auto_pause_engaged": bool(pause_payload),
        "auto_pause_payload": pause_payload,
        "canary_summary": canary.get("thesis_summary"),
    }
    write_status(symbol, date, status)
    audit.log("canary.evaluated",
              symbol=symbol, date=date,
              state=new_state, prev_state=prev_state,
              pass_w=aggregate["pass_weight"],
              fail_w=aggregate["fail_weight"],
              auto_paused=bool(pause_payload))
    return {"ok": True, **status}
