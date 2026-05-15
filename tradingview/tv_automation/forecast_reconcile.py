"""Standalone forecast reconciliation — grade saved forecasts against the
completed-day profile. No Bar Replay needed (profile is ground truth).

Not to be confused with `reconcile.py`, which is the trade-outcome tagger.

Inputs (at least 1 stage required):
    forecasts/{SYMBOL}_{YYYY-MM-DD}_pre_session.json
    forecasts/{SYMBOL}_{YYYY-MM-DD}_1000.json  (F1 live)
    forecasts/{SYMBOL}_{YYYY-MM-DD}_1200.json  (F2 live)
    forecasts/{SYMBOL}_{YYYY-MM-DD}_1400.json  (F3 live)
Ground truth:
    profiles/{SYMBOL}_{YYYY-MM-DD}.json  (required — run daily_profile first)

Output:
    forecasts/{SYMBOL}_{YYYY-MM-DD}_reconciliation.{md,json}

The JSON is structured (grades, summary, lessons array) so the
`lessons` module's aggregator picks it up automatically.

CLI:
    python -m tv_automation.forecast_reconcile                    # today
    python -m tv_automation.forecast_reconcile --date 2026-04-21  # specific day
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date, datetime
from pathlib import Path

from . import lessons as lessons_mod
from .chatgpt_web import analyze_via_chatgpt_web
from .lib import audit


_FORECASTS_ROOT = (Path(__file__).parent.parent / "forecasts").resolve()
_PROFILES_ROOT = (Path(__file__).parent.parent / "profiles").resolve()
_PARSE_FAIL_ROOT = (Path(__file__).parent.parent / "pine" / "parse_failures").resolve()

# Stages to reconcile, in order. Filename suffix → human label.
STAGE_FILES: list[tuple[str, str]] = [
    ("pre_session", "PRE-SESSION (made before open)"),
    ("1000", "F1 (made at 10:00 ET)"),
    ("1200", "F2 (made at 12:00 ET)"),
    ("1400", "F3 (made at 14:00 ET)"),
]


_RECONCILE_SYSTEM = """You are a forecast-accuracy adjudicator for day-trading predictions on MNQ1! (Micro E-mini Nasdaq-100 futures, CME). You will be given:
- Up to 4 DIRECTIONAL forecasts made at different times (pre-session, 10:00, 12:00, 14:00 ET), as their raw text + parsed fields
- Zero or more PIVOT re-forecasts (`invalidation_HHMM`) fired mid-session when the pre-session's invalidation triggered. These classify as REVERSAL / FLAT / SHAKEOUT with their own revised bias + levels.
- The actual completed-day profile as structured JSON (ground truth)
- A screenshot of the completed session (from the profile)

Grade DIRECTIONAL forecasts on:
1. Direction (hit/miss)
2. Close price — did actual close fall within the predicted range? If not, how far outside (pts)?
3. HOD / LOD coverage
4. Structure tags match
5. Tactical bias — would the predicted bias have been profitable?
6. Invalidation conditions — if the forecast named specific invalidation triggers, did they correctly fire / not fire?

Grade PIVOT forecasts differently — a pivot was fired AFTER the original thesis already broke, so judge it on:
1. Classification correctness — was REVERSAL/FLAT/SHAKEOUT the right call given what actually happened after the pivot time?
2. Level quality (for REVERSAL) — was the entry/stop/target band workable, and did price hit target before stop?
3. Reclaim check (for SHAKEOUT) — did price actually reclaim the named threshold by the deadline?
4. Flat discipline (for FLAT) — did standing aside avoid a whipsaw that an active trade would have suffered?
5. Revised-invalidation fire check — same as directional, just against the meta-invalidation.

REQUIRED OUTPUT — narrative sections first, then a fenced JSON block.

## ACTUAL OUTCOME
Open / Close / HOD / LOD / Shape (1 sentence).

## STAGE GRADES
For each forecast provided, a bullet block:
- Direction: ✓/✗
- Close range hit: ✓/✗ (miss pts if not)
- HOD captured: ✓/✗
- LOD captured: ✓/✗
- Tags correct: comma list
- Tags wrong: comma list
- Bias profitable if traded: ✓/✗
- Invalidation check: did the forecast's stated invalidation conditions play out accurately?
- Overall score: X/7

## FORECAST EVOLUTION
Did forecasts improve as the day progressed? Which stage caught the real signal first?

## LESSONS
List 3–5 SPECIFIC, ACTIONABLE lessons (not generic). Each lesson should tell a future forecaster exactly what to do differently. If a recurring lesson already exists from prior days, reinforce it with today's concrete evidence rather than rephrase.

## STRUCTURED JSON
```json
{
  "actual_summary": {
    "direction": "up|down|flat",
    "open_approx": 0.0,
    "close_approx": 0.0,
    "hod_approx": 0.0,
    "lod_approx": 0.0,
    "net_range_pct_open_to_close": 0.0,
    "intraday_span_pts": 0
  },
  "grades": {
    "<stage_name>": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [],
      "tags_wrong": [],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 0,
      "overall_max": 7,
      "biggest_miss": "..."
    }
  },
  "evolution": "one-paragraph comparison of how forecasts evolved",
  "summary": "two-sentence overall reconciliation summary",
  "lessons": [
    "specific actionable lesson 1",
    "specific actionable lesson 2"
  ]
}
```

{ACCUMULATED_LESSONS}

Return ONLY the narrative sections followed by the fenced JSON block. No preamble."""


def _render_lessons_block() -> str:
    body = lessons_mod.format_for_prompt(n=10)
    if not body:
        return ""
    return "## ACCUMULATED LESSONS (from prior reconciliations — apply these)\n" + body


def _load_available_stages(symbol: str, date_str: str) -> list[tuple[str, str, dict]]:
    """Return list of (stage_tag, human_label, data) for every stage file
    that exists — fixed-name stages (pre_session/F1/F2/F3) plus any
    dynamic pivot stages (`invalidation_HHMM`) fired mid-session.
    Pivots are grouped after the directional stages in chronological
    order so the LLM sees them in the order they happened."""
    found: list[tuple[str, str, dict]] = []
    for tag, label in STAGE_FILES:
        p = _FORECASTS_ROOT / f"{symbol}_{date_str}_{tag}.json"
        if p.exists():
            try:
                found.append((tag, label, json.loads(p.read_text())))
            except Exception as e:
                audit.log("forecast_reconcile.stage_load_fail", stage=tag, err=str(e))
    # Dynamic pivot stages — `invalidation_HHMM.json`, sorted ascending
    # so an earlier pivot appears before a later re-pivot.
    pivot_files = sorted(
        _FORECASTS_ROOT.glob(f"{symbol}_{date_str}_invalidation_*.json"),
        key=lambda p: p.name,
    )
    for pf in pivot_files:
        m = re.match(r".*_invalidation_(\d{2})(\d{2})\.json$", pf.name)
        if not m:
            continue
        hhmm = f"{m.group(1)}:{m.group(2)}"
        tag = f"invalidation_{m.group(1)}{m.group(2)}"
        label = f"PIVOT @ {hhmm} ET (intraday re-forecast)"
        try:
            found.append((tag, label, json.loads(pf.read_text())))
        except Exception as e:
            audit.log("forecast_reconcile.stage_load_fail", stage=tag, err=str(e))
    return found


def _compact_forecast(data: dict) -> dict:
    """Trim a forecast dict to the fields most useful for grading.
    Handles directional forecasts (pre_session/F1-F3) AND pivot
    re-forecasts (invalidation_HHMM) — pivot-specific fields
    (pivot_classification, reversal/shakeout/flat subtrees,
    revised_tactical_bias) are preserved so the grader sees what the
    pivot said in its own terms."""
    keep = {}
    for k in ("stage", "cursor_time", "made_at", "raw_response", "predictions",
              "time_window_expectations", "probable_goat", "tactical_bias",
              "prediction_tags", "regime_read", "confidence_notes",
              # Pivot-specific fields
              "pivot_classification", "pivot_confidence", "pivot_called_at_et",
              "operator_reason", "reversal", "shakeout_reclaim",
              "flat_conditions", "revised_tactical_bias", "break_context"):
        if k in data:
            keep[k] = data[k]
    return keep


_STRUCTURED_HEADER_RX = re.compile(r"^#{1,3}\s*STRUCTURED\s+JSON\s*$", re.MULTILINE)


def _extract_balanced_json(text: str, start: int) -> dict | None:
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i : j + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _split_response(text: str) -> tuple[str, dict | None]:
    header = _STRUCTURED_HEADER_RX.search(text)
    narrative_end = header.start() if header else len(text)
    search_start = header.end() if header else 0
    structured = _extract_balanced_json(text, search_start)
    return text[:narrative_end].strip(), structured


# Tag weights for "similar profile" scoring. Tuned empirically against
# the 65-profile corpus: `structure`, `lunch_behavior`, `afternoon_drive`
# are free-form LLM prose with ~1 unique value per day — they NEVER
# match across days and were dead weight. The signals that actually
# discriminate are bucketed tags: direction (3 buckets), open_type
# (30 unique but `rotational_open` is 29/65), goat_direction (binary),
# close_near_extreme (3 buckets). _SIMILAR_MIN_SCORE filters out
# spurious single-tag matches (e.g. just sharing goat_direction).
_SIMILARITY_WEIGHTS = {
    "direction": 3,
    "open_type": 2,
    "goat_direction": 2,
    "close_near_extreme": 2,
}
_SIMILAR_MIN_SCORE = 3  # at minimum direction must match, OR multiple lesser tags


def _profile_tag(profile: dict, key: str) -> str | None:
    """Read a tag from either profile.tags (canonical) or profile.summary
    (some fields like `direction` live in summary instead)."""
    tags = profile.get("tags") or {}
    if key in tags:
        return tags[key]
    summary = profile.get("summary") or {}
    return summary.get(key)


def _compute_similar_days(
    symbol: str, target_date: str, n: int = 5,
    profiles_root: Path | None = None,
) -> list[dict]:
    """Return up to N profile dates whose tags most overlap with target_date's.

    Deterministic — no LLM. Walks all sibling profiles, scores by
    weighted-tag-match against the target, drops zero-score candidates,
    sorts (score desc, date desc) so ties favor recent days. Stores
    enough metadata for the UI to render a clickable row per match
    without re-fetching each profile."""
    root = profiles_root or _PROFILES_ROOT
    target_path = root / f"{symbol}_{target_date}.json"
    if not target_path.exists():
        return []
    try:
        target = json.loads(target_path.read_text())
    except Exception:
        return []
    target_vals = {k: _profile_tag(target, k) for k in _SIMILARITY_WEIGHTS}

    candidates: list[dict] = []
    for f in sorted(root.glob(f"{symbol}_*.json")):
        if "metadata" in f.stem:
            continue
        cand_date = f.stem.removeprefix(f"{symbol}_")
        if cand_date == target_date:
            continue
        try:
            cand = json.loads(f.read_text())
        except Exception:
            continue
        score = 0
        matched: list[str] = []
        for key, weight in _SIMILARITY_WEIGHTS.items():
            tv = target_vals.get(key)
            cv = _profile_tag(cand, key)
            if tv is not None and tv == cv:
                score += weight
                matched.append(key)
        if score < _SIMILAR_MIN_SCORE:
            continue
        summary = cand.get("summary") or {}
        candidates.append({
            "date": cand_date,
            "dow": cand.get("dow"),
            "score": score,
            "max_score": sum(_SIMILARITY_WEIGHTS.values()),
            "matched_tags": matched,
            "direction": summary.get("direction"),
            "structure": _profile_tag(cand, "structure"),
            "shape_sentence": summary.get("shape_sentence", ""),
        })

    candidates.sort(key=lambda c: (c["score"], c["date"]), reverse=True)
    return candidates[:n]


async def run_reconciliation(
    *, symbol: str = "MNQ1", date_str: str | None = None,
) -> dict:
    target_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    )
    date_str = target_date.strftime("%Y-%m-%d")
    dow = target_date.strftime("%a")

    profile_path = _PROFILES_ROOT / f"{symbol}_{date_str}.json"
    if not profile_path.exists():
        raise FileNotFoundError(
            f"Completed-day profile not found: {profile_path}. Run daily_profile first."
        )
    profile = json.loads(profile_path.read_text())
    screenshot = profile.get("screenshot_path")
    if not screenshot or not Path(screenshot).exists():
        raise FileNotFoundError(
            f"Profile screenshot missing: {screenshot}. Re-run daily_profile."
        )

    stages = _load_available_stages(symbol, date_str)
    if not stages:
        raise FileNotFoundError(
            f"No forecast stages found for {symbol}_{date_str}. "
            f"Run pre_session_forecast and/or live_forecast first."
        )
    audit.log("forecast_reconcile.stages_loaded",
              stages=[s[0] for s in stages], date=date_str)

    base = _FORECASTS_ROOT / f"{symbol}_{date_str}_reconciliation"
    md_path, json_path = base.with_suffix(".md"), base.with_suffix(".json")

    with audit.timed("forecast_reconcile.run", date=date_str,
                     stage_count=len(stages)) as ac:
        ac["screenshot"] = screenshot

        # When the profile was built with `bar_reader`, prefer the
        # numerical OHLC over the LLM's vision read — vision misreads
        # HOD/LOD points by 50pt regularly on busy charts.
        actual_block = {
            "summary": profile.get("summary", {}),
            "tags": profile.get("tags", {}),
            "pivots": (profile.get("pivots") or [])[:8],
            "takeaway": profile.get("takeaway", ""),
        }
        if profile.get("actual_summary_api"):
            actual_block["actual_summary_api"] = profile["actual_summary_api"]
            actual_block["_note"] = (
                "actual_summary_api is exact OHLC from chart memory — "
                "prefer it over `summary.*_approx` for HOD/LOD/close grading."
            )
            ac["actual_summary_source"] = "api"
        else:
            ac["actual_summary_source"] = "vision"

        parts = [
            f"# RECONCILIATION TARGET: {symbol}! {date_str} ({dow})", "",
            "## ACTUAL OUTCOME (from completed-day profile — ground truth)",
            json.dumps(actual_block, indent=2),
            "",
        ]
        for tag, label, data in stages:
            parts.append(f"## FORECAST: {label}")
            parts.append(json.dumps(_compact_forecast(data), indent=2))
            parts.append("")
        parts.append(
            "Grade each forecast against the actual outcome. Use the exact output "
            "format from the system prompt, ending with the fenced JSON block."
        )
        user_prompt = "\n".join(parts)

        system_prompt = _RECONCILE_SYSTEM.replace(
            "{ACCUMULATED_LESSONS}", _render_lessons_block()
        )
        text, _, _ = await analyze_via_chatgpt_web(
            image_path=screenshot,
            system_prompt=system_prompt,
            user_text=user_prompt,
            model="Thinking",
            timeout_s=300,
        )
        ac["response_chars"] = len(text)

        narrative, structured = _split_response(text)
        if structured is None:
            _PARSE_FAIL_ROOT.mkdir(parents=True, exist_ok=True)
            dump = _PARSE_FAIL_ROOT / f"reconcile_{symbol}_{date_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            dump.write_text(text)
            audit.log("forecast_reconcile.parse_fail", dump_path=str(dump))

        fm = "\n".join([
            "---",
            f"symbol: {symbol}",
            f"date: {date_str}",
            f"dow: {dow}",
            "stage: reconciliation",
            f"screenshot: {screenshot}",
            f"forecasts_graded: {[s[0] for s in stages]}",
            f"ground_truth_profile: {profile_path}",
            f"made_at: {datetime.now().isoformat(timespec='seconds')}",
            "---",
            "",
        ])
        md_path.write_text(fm + text.strip() + "\n")

        saved = {
            "symbol": symbol,
            "date": date_str,
            "dow": dow,
            "stage": "reconciliation",
            "screenshot_path": screenshot,
            "forecasts_graded": [s[0] for s in stages],
            "ground_truth_profile": str(profile_path),
            "model": "chatgpt_thinking",
            "made_at": datetime.now().isoformat(timespec="seconds"),
            "raw_response": text,
        }
        if structured:
            saved.update(structured)
            saved["parsed_structured"] = True
        else:
            saved["parsed_structured"] = False
        # Cache top-N similar prior profiles so the reconciliation card
        # can surface them in the UI without per-render computation.
        # Pure tag-overlap — no LLM, safe to recompute by re-reconciling
        # or by the standalone backfill script.
        try:
            saved["similar_days"] = _compute_similar_days(symbol, date_str, n=5)
        except Exception as e:
            audit.log("forecast_reconcile.similar_days.fail", err=str(e))
            saved["similar_days"] = []
        json_path.write_text(json.dumps(saved, indent=2))
        ac["saved_to"] = str(json_path)
        ac["stages_graded"] = len(stages)
        return saved


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.forecast_reconcile")
    p.add_argument("--symbol", default="MNQ1")
    p.add_argument("--date", dest="date_str", default=None,
                   help="Trading date (default: today)")
    args = p.parse_args()
    result = asyncio.run(run_reconciliation(symbol=args.symbol, date_str=args.date_str))
    out = {k: v for k, v in result.items() if k != "raw_response"}
    print(json.dumps(out, indent=2)[:3000])


if __name__ == "__main__":
    _main()
