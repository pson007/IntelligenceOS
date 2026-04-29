"""Day-arc journal — close the feedback loop between forecasts and reality.

For a given trading day, assemble the full chain in chronological order:

  pre_session forecast (08:30 ET)
    → 10:00 live forecast
    → 12:00 live forecast
    → 14:00 live forecast
    → pivot (if invalidation fired)
    → applied-Pine screenshots
    → live decisions logged in decisions.db
    → daily profile (16:00 ET — the ground-truth artifact)

Each forecast stage is graded *deterministically* against the profile
(no extra LLM call). Pre-session has full structured fields so its
grading is exact: direction match, span hit, %-range hit, prediction-
tag matches. Live stages (1000/1200/1400) and pivot only have free-form
`raw_response` text; the grader regex-extracts the `Projected close
price range`, `Rest-of-day HOD/LOD range`, and `direction:` tag from
the PREDICTION TAGS block, then compares to profile.summary.{close,
hod,lod,direction}_approx.

This is the missing layer that turns a corpus of isolated artifacts
into a "what survived contact with reality?" view. Compounds:
yesterday's reconciliation seeds tomorrow's pre-session priors.

Intentionally read-only — no writes, no side effects. The endpoint
(`/api/journal/{symbol}/{date}`) renders this dict directly.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import decision_log


_FORECASTS_DIR = (Path(__file__).parent.parent / "forecasts").resolve()
_PROFILES_DIR = (Path(__file__).parent.parent / "profiles").resolve()
_APPLIED_DIR = (Path(__file__).parent.parent / "pine" / "applied").resolve()


# -----------------------------------------------------------------------------
# Loading — file lookup with graceful "missing" semantics.
# -----------------------------------------------------------------------------


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _profile_for(symbol: str, date: str) -> dict | None:
    return _load_json(_PROFILES_DIR / f"{symbol}_{date}.json")


def _forecast_for(symbol: str, date: str, stage: str) -> dict | None:
    return _load_json(_FORECASTS_DIR / f"{symbol}_{date}_{stage}.json")


def _all_pivots_for(symbol: str, date: str) -> list[dict]:
    """Pivot artifacts are timestamped (`pivot_HH-MM-SS`). Return all of
    them for the day, sorted by stage name (which sorts chronologically
    because the timestamp is the suffix)."""
    out = []
    for p in sorted(_FORECASTS_DIR.glob(f"{symbol}_{date}_pivot*.json")):
        d = _load_json(p)
        if d:
            out.append({"path": str(p), "stage": p.stem.split(f"{date}_", 1)[-1],
                        "data": d})
    return out


def _applied_screenshots_for(date: str) -> list[dict]:
    """Applied Pine screenshots that mention the date. Naming varies —
    `forecast_overlay_DATE.png`, `pivot_overlay_DATE_*.png`,
    `MNQ1__analysis_YYYYMMDD-HHMMSS.png`. Match by date occurrence."""
    if not _APPLIED_DIR.exists():
        return []
    compact = date.replace("-", "")
    out = []
    for p in sorted(_APPLIED_DIR.glob("*.png")):
        name = p.name
        if date in name or compact in name:
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = None
            out.append({"path": str(p), "name": name, "mtime": mtime})
    out.sort(key=lambda r: r.get("mtime") or 0)
    return out


def _decisions_for(date: str) -> list[dict]:
    """Decisions made on this date, oldest first."""
    try:
        decision_log.init_db()
        con = sqlite3.connect(decision_log.DB_PATH)
        con.row_factory = sqlite3.Row
        try:
            start = datetime.fromisoformat(f"{date}T00:00:00").timestamp()
            end = start + 86400
            cur = con.execute(
                "SELECT * FROM decisions WHERE ts >= ? AND ts < ? ORDER BY ts ASC",
                (start, end),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            con.close()
    except Exception:
        return []


# -----------------------------------------------------------------------------
# Grading — deterministic. No LLM calls.
# -----------------------------------------------------------------------------


def _direction_match(predicted: str | None, actual: str | None) -> bool | None:
    """Tolerant direction comparison. Pre-session uses 'up'/'down'/'sideways';
    live forecasts use 'bullish'/'bearish'; profile uses 'up'/'down'.
    Normalize before compare. Returns None when either side is missing."""
    if not predicted or not actual:
        return None
    norm = {"up": "up", "long": "up", "bullish": "up",
            "down": "down", "short": "down", "bearish": "down",
            "sideways": "sideways", "flat": "sideways", "balance": "sideways"}
    p = norm.get(str(predicted).strip().lower())
    a = norm.get(str(actual).strip().lower())
    if not p or not a:
        return None
    return p == a


def _band_hit(actual: float | None,
              lo: float | None, hi: float | None) -> dict | None:
    """Did `actual` land inside the [lo, hi] band? Return None if any
    input missing; else {hit, miss_pts, side}.
       side = 'in'   when lo ≤ actual ≤ hi
       side = 'over' when actual > hi (miss_pts = actual − hi, positive)
       side = 'under' when actual < lo (miss_pts = lo − actual, positive)"""
    if actual is None or lo is None or hi is None:
        return None
    if lo > hi:
        lo, hi = hi, lo
    if lo <= actual <= hi:
        return {"hit": True, "side": "in", "miss_pts": 0.0}
    if actual > hi:
        return {"hit": False, "side": "over", "miss_pts": round(actual - hi, 2)}
    return {"hit": False, "side": "under", "miss_pts": round(lo - actual, 2)}


def _grade_pre_session(forecast: dict, profile: dict) -> dict:
    """Pre-session forecast has full structured data. Grade six axes
    where the data exists, leave the rest as None for the UI to show as
    'n/a'. The total `score` is fraction-of-axes-passed for axes that
    were actually gradable."""
    summary = (profile.get("summary") or {})
    profile_tags = (profile.get("tags") or {})
    predictions = (forecast.get("predictions") or {})
    forecast_tags = (forecast.get("prediction_tags") or {})

    direction = _direction_match(
        predictions.get("direction"), summary.get("direction"),
    )
    span = _band_hit(
        summary.get("intraday_span_pts"),
        predictions.get("predicted_intraday_span_lo_pts"),
        predictions.get("predicted_intraday_span_hi_pts"),
    )
    pct = _band_hit(
        summary.get("net_range_pct_open_to_close"),
        predictions.get("predicted_net_pct_lo"),
        predictions.get("predicted_net_pct_hi"),
    )

    # Tag-by-tag match — count, don't gate. Surfaces "got direction
    # right but mis-read structure" patterns over time.
    tag_matches: list[dict] = []
    for k in ("direction", "structure", "open_type", "lunch_behavior",
              "afternoon_drive", "goat_direction", "close_near_extreme"):
        f = forecast_tags.get(k)
        a = profile_tags.get(k)
        if f is not None or a is not None:
            tag_matches.append({"key": k, "predicted": f, "actual": a,
                                "match": (f == a) if (f and a) else None})

    axes_passed = sum(1 for x in [direction] if x is True) + \
                  sum(1 for x in [span, pct] if x and x.get("hit") is True)
    axes_gradable = sum(1 for x in [direction] if x is not None) + \
                    sum(1 for x in [span, pct] if x is not None)
    tag_pass = sum(1 for t in tag_matches if t["match"] is True)
    tag_total = sum(1 for t in tag_matches if t["match"] is not None)

    return {
        "stage": "pre_session",
        "direction": {
            "predicted": predictions.get("direction"),
            "actual": summary.get("direction"),
            "match": direction,
        },
        "span_pts": {
            "predicted_lo": predictions.get("predicted_intraday_span_lo_pts"),
            "predicted_hi": predictions.get("predicted_intraday_span_hi_pts"),
            "actual": summary.get("intraday_span_pts"),
            **(span or {"hit": None}),
        },
        "net_pct": {
            "predicted_lo": predictions.get("predicted_net_pct_lo"),
            "predicted_hi": predictions.get("predicted_net_pct_hi"),
            "actual": summary.get("net_range_pct_open_to_close"),
            **(pct or {"hit": None}),
        },
        "tags": tag_matches,
        "axes_score": (f"{axes_passed}/{axes_gradable}"
                       if axes_gradable else None),
        "tags_score": (f"{tag_pass}/{tag_total}" if tag_total else None),
        "invalidation": (forecast.get("tactical_bias") or {}).get("invalidation"),
        "invalidation_check_note": "Manual review — text condition; not auto-evaluated.",
    }


# Live-forecast text parsers. Forecasts are free-form prose plus a
# fixed-format PREDICTION TAGS block; we extract three numeric ranges
# and the direction tag.
# Header formats vary between forecast generations:
#   "Projected close price range: 27,490–27,545"      (newer)
#   "Projected close: 26,920 – 26,980"                (older)
# Match either, plus assorted Unicode dashes (en-, em-, hyphen, minus).
_RX_CLOSE = re.compile(
    r"Projected close(?:\s+price)?(?:\s+range)?[:\s]+"
    r"([\d,\.]+)\s*[–—\-−]\s*([\d,\.]+)", re.I,
)
_RX_HOD = re.compile(
    r"Rest-of-day HOD(?:\s+range)?[:\s]+"
    r"([\d,\.]+)\s*[–—\-−]\s*([\d,\.]+)", re.I,
)
_RX_LOD = re.compile(
    r"Rest-of-day LOD(?:\s+range)?[:\s]+"
    r"([\d,\.]+)\s*[–—\-−]\s*([\d,\.]+)", re.I,
)
_RX_DIR = re.compile(r"^\s*direction[:\s]+([A-Za-z_]+)", re.M | re.I)
_RX_PRIMARY_BIAS = re.compile(
    r"Primary bias[:\s]+([A-Za-z]+)[,\s]*(\d{1,3})?\s*%?", re.I,
)


def _parse_band(rx: re.Pattern, text: str) -> tuple[float, float] | None:
    m = rx.search(text or "")
    if not m:
        return None
    try:
        lo = float(m.group(1).replace(",", ""))
        hi = float(m.group(2).replace(",", ""))
        return (lo, hi)
    except ValueError:
        return None


def _grade_live_text(forecast: dict, profile: dict, *, stage_label: str) -> dict:
    """Live-forecast / pivot grading. Regex-pulls the three predicted
    ranges and direction from `raw_response`; compares to the profile's
    actual close/HOD/LOD/direction. Forecasts that lack the expected
    blocks just show fewer axes."""
    summary = (profile.get("summary") or {})
    text = forecast.get("raw_response") or ""

    close_band = _parse_band(_RX_CLOSE, text)
    hod_band = _parse_band(_RX_HOD, text)
    lod_band = _parse_band(_RX_LOD, text)

    dir_match = _RX_DIR.search(text)
    primary = _RX_PRIMARY_BIAS.search(text)
    predicted_dir = (dir_match.group(1).strip().lower() if dir_match
                     else (primary.group(1).strip().lower() if primary else None))

    close_grade = _band_hit(summary.get("close_approx"),
                            close_band[0] if close_band else None,
                            close_band[1] if close_band else None)
    hod_grade = _band_hit(summary.get("hod_approx"),
                          hod_band[0] if hod_band else None,
                          hod_band[1] if hod_band else None)
    lod_grade = _band_hit(summary.get("lod_approx"),
                          lod_band[0] if lod_band else None,
                          lod_band[1] if lod_band else None)
    direction = _direction_match(predicted_dir, summary.get("direction"))

    bands = [
        {"key": "close", "label": "Close", "actual": summary.get("close_approx"),
         "predicted_lo": close_band[0] if close_band else None,
         "predicted_hi": close_band[1] if close_band else None,
         **(close_grade or {"hit": None})},
        {"key": "hod", "label": "HOD", "actual": summary.get("hod_approx"),
         "predicted_lo": hod_band[0] if hod_band else None,
         "predicted_hi": hod_band[1] if hod_band else None,
         **(hod_grade or {"hit": None})},
        {"key": "lod", "label": "LOD", "actual": summary.get("lod_approx"),
         "predicted_lo": lod_band[0] if lod_band else None,
         "predicted_hi": lod_band[1] if lod_band else None,
         **(lod_grade or {"hit": None})},
    ]

    axes_passed = sum(1 for b in bands if b["hit"] is True) + \
                  (1 if direction is True else 0)
    axes_gradable = sum(1 for b in bands if b["hit"] is not None) + \
                    (1 if direction is not None else 0)

    primary_pct = None
    if primary and primary.group(2):
        try: primary_pct = int(primary.group(2))
        except ValueError: pass

    return {
        "stage": stage_label,
        "direction": {
            "predicted": predicted_dir,
            "actual": summary.get("direction"),
            "match": direction,
            "confidence_pct": primary_pct,
        },
        "bands": bands,
        "axes_score": (f"{axes_passed}/{axes_gradable}"
                       if axes_gradable else None),
    }


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def assemble_day(symbol: str, date: str) -> dict:
    """Build the full day-arc payload. Always returns a dict — missing
    pieces are explicit None / empty list, never raise. The UI is
    responsible for rendering "n/a" rather than a fatal error.

    The returned shape is intentionally flat enough that you could JSON-
    diff two days side-by-side to see how the calibration moved.
    """
    profile = _profile_for(symbol, date)
    profile_complete = bool(
        profile and (profile.get("summary") or {}).get("direction")
    )

    stages: list[dict] = []

    # Pre-session — grade only when both sides are present.
    pre_fc = _forecast_for(symbol, date, "pre_session")
    if pre_fc:
        graded = (_grade_pre_session(pre_fc, profile)
                  if profile_complete else None)
        stages.append({
            "key": "pre_session",
            "label": "Pre-session",
            "made_at": pre_fc.get("made_at"),
            "screenshot_path": pre_fc.get("screenshot_path"),
            "regime_read": pre_fc.get("regime_read"),
            "tactical_bias": pre_fc.get("tactical_bias"),
            "predictions": pre_fc.get("predictions"),
            "prediction_tags": pre_fc.get("prediction_tags"),
            "grading": graded,
        })

    for stage_key, label in (("1000", "10:00"), ("1200", "12:00"),
                             ("1400", "14:00")):
        fc = _forecast_for(symbol, date, stage_key)
        if not fc:
            continue
        graded = (_grade_live_text(fc, profile, stage_label=stage_key)
                  if profile_complete else None)
        stages.append({
            "key": stage_key,
            "label": label,
            "made_at": fc.get("made_at"),
            "cursor_time": fc.get("cursor_time"),
            "screenshot_path": fc.get("screenshot_path"),
            "raw_response": fc.get("raw_response"),
            "grading": graded,
        })

    for piv in _all_pivots_for(symbol, date):
        # Skip pre_session — already collected above.
        if piv["stage"] == "pre_session":
            continue
        if piv["stage"] in {"1000", "1200", "1400"}:
            continue
        fc = piv["data"]
        graded = (_grade_live_text(fc, profile, stage_label=piv["stage"])
                  if profile_complete else None)
        stages.append({
            "key": piv["stage"],
            "label": piv["stage"].replace("_", " "),
            "made_at": fc.get("made_at"),
            "screenshot_path": fc.get("screenshot_path"),
            "raw_response": fc.get("raw_response"),
            "reason": fc.get("reason"),
            "grading": graded,
        })

    # Roll up: how many axes did we get right across every gradable stage?
    rollup_pass = 0
    rollup_total = 0
    for s in stages:
        g = s.get("grading") or {}
        sc = g.get("axes_score")
        if sc and "/" in sc:
            try:
                p, t = sc.split("/")
                rollup_pass += int(p)
                rollup_total += int(t)
            except ValueError:
                pass

    return {
        "symbol": symbol,
        "date": date,
        "profile": ({
            "available": True,
            "summary": profile.get("summary"),
            "tags": profile.get("tags"),
            "takeaway": profile.get("takeaway"),
            "screenshot_path": profile.get("screenshot_path"),
        } if profile else {"available": False}),
        "stages": stages,
        "applied_screenshots": _applied_screenshots_for(date),
        "decisions": _decisions_for(date),
        "rollup": {
            "axes_passed": rollup_pass,
            "axes_gradable": rollup_total,
            "score": (f"{rollup_pass}/{rollup_total}"
                      if rollup_total else None),
            "stages_count": len(stages),
            "graded_stages": sum(1 for s in stages if s.get("grading")),
        },
    }
