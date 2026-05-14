---
symbol: MNQ1
date: 2026-05-11
dow: Mon
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-11.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-11.json
made_at: 2026-05-14T19:22:24
---
ACTUAL OUTCOME

Open 29,305 / Close 29,429 / HOD 29,480.5 / LOD 29,247. Shape: wide two-way green session with early flush, late-morning upside trend, upper balance, 15:00 breakdown attempt, and late reclaim.

STAGE GRADES
PRE-SESSION

Direction: ✓

Close range hit: ✓

HOD captured: ✗

LOD captured: ✗

Tags correct: direction up, gap-up pullback/reclaim, GOAT up, close not near extreme, upper balance risk

Tags wrong: expected larger span, demand hold above 29,240, cleaner high-balance continuation

Bias profitable if traded: ✓

Invalidation check: Mostly correct. The 29,240 lower-demand break did not accept; VWAP/reclaim logic kept the long thesis alive. It underestimated the depth of the early flush.

Overall score: 5/7

F1 — 10:00

Direction: ✓

Close range hit: ✗ — missed by 19 pts above range

HOD captured: ✗ — missed by 25.5 pts above range

LOD captured: ✗ — missed by 13 pts below range

Tags correct: gap-up drive then reversal, late reclaim attempt, GOAT up

Tags wrong: lower-to-sideways balance, range compression, demand floor too high

Bias profitable if traded: ✗

Invalidation check: Incorrect. The 29,295 invalidation fired, but it was a false liquidation break, not trend-down acceptance.

Overall score: 2/7

F2 — 12:00

Direction: ✓

Close range hit: ✗ — missed by 81 pts below range

HOD captured: ✗ — missed by 59.5 pts below range

LOD captured: ✓

Tags correct: early_flush_to_midday_trend_then_upper_balance, GOAT long, shallow lunch pullback, failed early selling

Tags wrong: afternoon breakout-drive, close near extreme, 29,540+ extension

Bias profitable if traded: ✓

Invalidation check: Correct. Sustained trade below 29,360 did not occur after noon; pullbacks held above the lower invalidation.

Overall score: 5/7

F3 — 14:00

Direction: ✓

Close range hit: ✗ — missed by 26 pts below range

HOD captured: ✗ — missed by about 4.5 pts below range

LOD captured: ✗ — late selloff undercut the expected rest-of-day LOD band

Tags correct: upper balance, held higher balance, failed_breakdown_late_reclaim, GOAT long

Tags wrong: controlled upside continuation, close near extreme, clean retest/extension through supply

Bias profitable if traded: ✗

Invalidation check: Partly wrong. The 29,380 area was tested/undercut enough to punish longs, but the break failed and reclaimed instead of producing clean bearish acceptance.

Overall score: 3/7

FORECAST EVOLUTION

Forecast quality improved sharply from F1 to F2. The pre-session forecast caught the broad bullish-reclaim thesis, but its LOD/span levels were stale against the actual deeper flush. F1 misread the 10:00 weakness as potential lower balance and placed demand too high. F2 caught the real signal first: failed liquidation into late-morning trend and upper balance. F3 retained the right structure label but overpaid for upside continuation and missed the late breakdown/reclaim risk.

LESSONS

When the first demand shelf breaks but immediately reclaims, mark it as failed liquidation, not bearish acceptance; today's 29,295 break flushed to 29,247 and then produced the GOAT long.

At 12:00, after a strong reclaim into supply, cap upside targets at the active supply band unless price accepts above it; 29,480 capped the day, so 29,540–29,610 was too aggressive.

For 14:00 forecasts inside upper balance, require actual acceptance above HOD/supply before projecting controlled continuation; otherwise keep close targets midrange.

When using "buy pullback" logic after noon, anchor stops below the true reclaim shelf, not just the visible higher-low band; shallow stops near 29,380 were vulnerable to the 15:00 flush.

Keep close-near-extreme tags separate from direction; a green day with a late reclaim is not automatically an upper-extreme close.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 29305.0,
    "close_approx": 29429.0,
    "hod_approx": 29480.5,
    "lod_approx": 29247.0,
    "net_range_pct_open_to_close": 0.4231,
    "intraday_span_pts": 233.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 7,
      "tags_correct": [
        "direction up",
        "gap-up pullback/reclaim",
        "GOAT up",
        "close not near extreme",
        "upper balance risk"
      ],
      "tags_wrong": [
        "expected larger span",
        "demand hold above 29240",
        "cleaner high-balance continuation"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Underestimated the early flush depth and overestimated total intraday span."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 19,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 13,
      "tags_correct": [
        "gap-up drive then reversal",
        "late reclaim attempt",
        "GOAT up"
      ],
      "tags_wrong": [
        "lower-to-sideways balance",
        "range compression",
        "demand floor too high"
      ],
      "bias_profitable": false,
      "invalidation_correct": false,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "Treated the 29295 break as bearish invalidation instead of a false liquidation/reclaim setup."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 81,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "early_flush_to_midday_trend_then_upper_balance",
        "GOAT long",
        "shallow lunch pullback",
        "failed early selling"
      ],
      "tags_wrong": [
        "afternoon breakout-drive",
        "close near extreme",
        "29540+ extension"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Correctly identified the regime but projected an upside breakout beyond supply that never accepted."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 26,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 10,
      "tags_correct": [
        "upper balance",
        "held higher balance",
        "failed_breakdown_late_reclaim",
        "GOAT long"
      ],
      "tags_wrong": [
        "controlled upside continuation",
        "close near extreme",
        "clean retest/extension through supply"
      ],
      "bias_profitable": false,
      "invalidation_correct": false,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "Expected late upside continuation instead of a 15:00 breakdown attempt followed by reclaim."
    }
  },
  "evolution": "The pre-session forecast caught the broad bullish reclaim idea but missed the true flush depth. F1 degraded by placing demand too high and misclassifying the false liquidation break. F2 was the best forecast and caught the real signal first: early flush to midday trend then upper balance. F3 preserved the structure read but overprojected continuation and failed to respect late-day whipsaw risk.",
  "summary": "The day rewarded bullish-reclaim logic, not clean trend-day extension logic. The best read was F2: structurally accurate and tactically usable, but too aggressive on upside targets and close location.",
  "lessons": [
    "When the first demand shelf breaks but immediately reclaims, classify it as failed liquidation, not bearish acceptance.",
    "At noon, cap upside targets at active supply unless price accepts above it; 29480 capped the day, so 29540+ was unjustified.",
    "For 14:00 upper-balance forecasts, require acceptance above HOD/supply before projecting controlled continuation.",
    "After noon, place long invalidation below the true reclaim shelf, not just the nearest higher-low band.",
    "Do not equate green direction with close-near-extreme; late reclaim days often close mid-upper range, not at highs."
  ]
}
