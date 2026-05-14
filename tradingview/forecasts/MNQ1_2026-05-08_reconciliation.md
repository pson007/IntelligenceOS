---
symbol: MNQ1
date: 2026-05-08
dow: Fri
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-08.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-08.json
made_at: 2026-05-14T19:16:02
---
ACTUAL OUTCOME

MNQ opened near 28878, printed an early LOD near 28863.5, then ran a bullish open-drive trend day to a 29340.75 HOD and 29339.5 close, finishing essentially at the high after a stair-step higher-low grind.

STAGE GRADES
PRE-SESSION

Direction: ✓

Close range hit: ✗ — miss by ~230.5 pts above implied +0.80% upper band

HOD captured: ✗

LOD captured: ✓

Tags correct: direction up, GOAT up, morning long bias, opening pullback/reclaim concept, demand hold

Tags wrong: high balance, no close near extreme, late pullback risk, capped 28950–28980 continuation caution

Bias profitable if traded: ✓

Invalidation check: ✓ — bearish invalidations did not fire; 28820/28790 held and VWAP acceptance stayed bullish

Overall score: 4/7

F1

Direction: ✓

Close range hit: ✗ — miss by 244.5 pts above 29095

HOD captured: ✗ — miss by 215.75 pts above 29125

LOD captured: ✗ — actual full-session LOD was 51.5 pts below 28915

Tags correct: bullish, early impulse, shallow pullback, long GOAT, close near highs

Tags wrong: high balance framing, muted continuation target, 29065–29125 HOD ceiling

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained trade below 28900 did not occur after the bullish reclaim

Overall score: 4/7

F2

Direction: ✓

Close range hit: ✗ — miss by 94.5 pts above 29245

HOD captured: ✗ — miss by 65.75 pts above 29275

LOD captured: ✓ — post-forecast pullbacks held near the projected 29045–29085 zone

Tags correct: bullish morning, higher balance, afternoon upside breakout attempt, long GOAT, upper-third close

Tags wrong: undercalled close strength, undercalled full trend-day extension

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained trade below 29040 did not fire

Overall score: 5/7

F3

Direction: ✓

Close range hit: ✗ — miss by 9.5 pts above 29330

HOD captured: ✓

LOD captured: ✓

Tags correct: controlled trend-up, higher lows, late upside probe, long GOAT, close near extreme

Tags wrong: upper-balance caution slightly overstated; close pushed through the upper edge

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained trade below 29195 did not fire

Overall score: 6/7

FORECAST EVOLUTION

Forecasts improved steadily. Pre-session caught the bullish direction and correct opening long idea, but badly undercalled range expansion and close location. F1 still capped the day too low. F2 first recognized the trend-continuation structure, but still underestimated afternoon extension. F3 caught the real signal best: persistent trend-up with higher lows, late upside attempt, HOD near 29340, and close near the extreme.

LESSONS

When the open-drive holds above the first pullback low and reclaims quickly, upgrade from "pullback/reclaim into balance" to "trend-day candidate" before 10:30.

Do not cap HOD near early supply after price accepts above it with higher lows; absorbed supply should become the next demand reference.

At noon, if the morning has made multiple higher highs and no VWAP loss, widen close/HOD bands instead of projecting only a modest upper-third finish.

At 14:00, when price is already stair-stepping above rising demand, keep the long bias but allow for a close through the projected upper band.

Reinforce prior lesson: after a confirmed upside breakout, anchor pullback expectations to the new demand shelf, not old lower balance levels.

STRUCTURED JSON
JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 28878.0,
    "close_approx": 29339.5,
    "hod_approx": 29340.75,
    "lod_approx": 28863.5,
    "net_range_pct_open_to_close": 1.5981,
    "intraday_span_pts": 477
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 230.5,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction up",
        "GOAT up",
        "morning long bias",
        "opening pullback/reclaim",
        "demand held"
      ],
      "tags_wrong": [
        "high balance",
        "no close near extreme",
        "late pullback risk",
        "28950-28980 cap emphasis"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "Correct bullish thesis but treated the day as capped high balance instead of a full open-drive trend day closing at HOD."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 244.5,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 51.5,
      "tags_correct": [
        "bullish",
        "early impulse",
        "shallow pullback",
        "long GOAT",
        "close near highs"
      ],
      "tags_wrong": [
        "high balance above reclaimed supply",
        "controlled upside grind too small",
        "HOD ceiling too low"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "Projected continuation but anchored targets far too close to early supply."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 94.5,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "bullish morning",
        "higher balance",
        "afternoon upside breakout attempt",
        "long GOAT",
        "upper-third close"
      ],
      "tags_wrong": [
        "close band too low",
        "HOD band too low",
        "undercalled trend-day extension"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Recognized continuation but failed to expand the afternoon target range enough."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 9.5,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "controlled trend-up",
        "higher lows",
        "late upside probe",
        "long GOAT",
        "close near extreme"
      ],
      "tags_wrong": [
        "upper-balance caution slightly overstated"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Close band was slightly too conservative; actual close exceeded the top by 9.5 pts."
    }
  },
  "evolution": "The forecast sequence improved materially through the day. Pre-session and F1 were directionally right but underestimated trend strength. F2 first caught the continuation regime, though still with compressed targets. F3 was the best forecast because it identified the active trend-up structure, defended demand, late upside probe, and near-HOD close.",
  "summary": "All forecasts correctly leaned long, and every tactical long bias was profitable. The repeated miss was range compression: each forecast until F3 underestimated how strongly absorbed supply would convert into a full bullish open-drive trend day.",
  "lessons": [
    "When the open-drive holds above the first pullback low and reclaims quickly, upgrade from pullback/reclaim into balance to trend-day candidate before 10:30.",
    "Do not cap HOD near early supply after price accepts above it with higher lows; absorbed supply should become the next demand reference.",
    "At noon, if the morning has made multiple higher highs and no VWAP loss, widen close/HOD bands instead of projecting only a modest upper-third finish.",
    "At 14:00, when price is already stair-stepping above rising demand, keep the long bias but allow for a close through the projected upper band.",
    "After a confirmed upside breakout, anchor pullback expectations to the new demand shelf, not old lower balance levels."
  ]
}
