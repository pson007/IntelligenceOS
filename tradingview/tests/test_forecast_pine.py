#!/usr/bin/env python3
"""Snapshot-style tests for `tv_automation.forecast_pine.render_pine`.

Behavior tests rather than strict golden-file snapshots — golden files are
brittle when the Pine evolves and tend to get blanket-updated on diff,
defeating their purpose. Instead, assert the invariants that, if violated,
would have caught the actual bugs that shipped:

  - `in_target_day` uses NY-timezone-qualified `year/month/dayofmonth`
    calls (the 2026-05-05 evening bug — bare exchange-tz identifiers
    silently disabled the indicator for ~1h each night).
  - All wall-clock anchors go through `timestamp("America/New_York", ...)`.
  - The `fyear/fmonth/fday` inputs are populated from the forecast JSON's
    date field.
  - The `indicator()` declaration is present (otherwise TV refuses to
    load the script).

Pure stdlib; no pytest. Prints PASS/FAIL per check. Exit non-zero on any
fail. Run: `.venv/bin/python tests/test_forecast_pine.py`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tv_automation.forecast_pine import render_pine


def _fixture_forecast() -> dict:
    """Load the most recent committed pre_session forecast as fixture
    input. Falls back to a minimal hand-rolled dict if no artifact is
    available (e.g., on a fresh checkout before any forecast ran)."""
    fcasts = sorted((ROOT / "forecasts").glob("MNQ1_*_pre_session.json"))
    if fcasts:
        return json.loads(fcasts[-1].read_text())
    # Minimal fixture — covers every field render_pine looks at.
    return {
        "symbol": "MNQ1!", "date": "2026-05-06", "dow": "Wed",
        "predictions": {
            "direction": "up", "direction_confidence": "med",
            "open_type": "gap_up_rotational_reclaim",
            "structure": "open_dip_reclaim",
            "expected_move_size": "med",
            "predicted_net_pct_lo": 0.10, "predicted_net_pct_hi": 0.55,
        },
        "tactical_bias": {
            "bias": "buy_dips_on_reclaim",
            "invalidation": "Invalid if 09:30-10:00 cannot reclaim 28300.",
        },
        "probable_goat": {
            "direction": "long", "time_window": "opening",
            "rationale": "Best risk/reward after gap-up pullback holds demand.",
        },
        "regime_read": "bullish rotational",
    }


def _check(name: str, ok: bool, detail: str = "") -> bool:
    flag = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{flag}] {name}{suffix}")
    return ok


def main() -> int:
    forecast = _fixture_forecast()
    pine = render_pine(forecast)

    fails = 0

    # 1. NY-timezone-qualified date-component reads (the bug from
    #    commit 8ec236f). Bare `year ==` / `month ==` / `dayofmonth ==`
    #    in `in_target_day` would disable the indicator for an hour
    #    each evening when CT day != ET day.
    if not _check(
        "in_target_day uses NY-tz year/month/dayofmonth calls",
        bool(re.search(
            r'in_target_day\s*=\s*year\(\s*time\s*,\s*"America/New_York"\s*\)\s*==\s*fyear\s+and\s+month\(\s*time\s*,\s*"America/New_York"\s*\)\s*==\s*fmonth\s+and\s+dayofmonth\(\s*time\s*,\s*"America/New_York"\s*\)\s*==\s*fday',
            pine,
        )),
        detail="bare year/month/dayofmonth would disable indicator at night",
    ):
        fails += 1

    # 2. All wall-clock anchors use NY tz. timestamp() with ANY other
    #    timezone string is a smell. (Empty timezone uses exchange tz.)
    bad_anchors = re.findall(
        r'timestamp\(\s*"([^"]*)"\s*,', pine,
    )
    bad = [tz for tz in bad_anchors if tz != "America/New_York"]
    if not _check(
        f"all timestamp() anchors use America/New_York ({len(bad_anchors)} found)",
        not bad,
        detail=f"non-NY anchors: {bad}" if bad else "",
    ):
        fails += 1

    # 3. Date components flowed through from JSON to fyear/fmonth/fday
    #    inputs (so a forecast for 2026-05-06 produces fyear=2026,
    #    fmonth=5, fday=6 in the rendered Pine). Catches off-by-one
    #    parsing mistakes in the substitution layer.
    date = forecast.get("date", "")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ok = (
            f'fyear  = input.int({y},' in pine
            and f'fmonth = input.int({mo},' in pine
            and f'fday   = input.int({d},' in pine
        )
        if not _check(
            f"fyear/fmonth/fday substituted from forecast date {date}",
            ok,
            detail=f"expected y={y} m={mo} d={d}",
        ):
            fails += 1

    # 4. indicator() declaration present — TV refuses to load a Pine
    #    script that doesn't declare itself. Trivial to break with a
    #    template substitution typo; trivial to catch.
    if not _check(
        "indicator() declaration with overlay=true",
        'indicator(' in pine and 'overlay=true' in pine,
    ):
        fails += 1

    # 5. //@version=6 directive — Pine v6 features used throughout
    #    this file (e.g., box.merge_cells, str.replace_all) require
    #    explicit v6. v5 fallback would silently lose half the visuals.
    if not _check(
        "//@version=6 declared",
        pine.lstrip().startswith("//@version=6"),
    ):
        fails += 1

    print()
    if fails:
        print(f"FAILED: {fails} check(s)")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
