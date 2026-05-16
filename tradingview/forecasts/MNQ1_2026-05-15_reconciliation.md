---
symbol: MNQ1
date: 2026-05-15
dow: Fri
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-15.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-15.json
made_at: 2026-05-15T16:51:54
---
ACTUAL OUTCOME

MNQ opened near 29,281, rallied to an exact HOD near 29,487, failed the reclaim/continuation attempt, rotated lower to 29,208 LOD, and closed weak near 29,231, about -0.17% from open. Shape: failed-reclaim bearish rotation lower into a near-LOD close.

STAGE GRADES
PRE-SESSION

Direction: ✓

Close range hit: ✗ — miss by ~9 pts above the forecast net-pct band

HOD captured: ✓ — rejection below 29,520 / 29,476 reclaim-risk zone was well framed

LOD captured: ✓ — downside pressure below 29,245 was correctly identified

Tags correct: direction down, afternoon failed reclaim then lower, GOAT down, below prior-value short bias

Tags wrong: gap-down acceptance, morning-probe/midday-balance emphasis, close not near extreme

Bias profitable if traded: ✓

Invalidation check: Correct. The key invalidations did not cleanly fire: price probed 29,476 but did not accept above 29,520.

Overall score: 5/7

F1

Direction: ✓

Close range hit: ✗ — miss by ~111 pts above the forecast close band

HOD captured: ✗ — actual HOD exceeded rest-of-day HOD band by ~212 pts

LOD captured: ✗ — actual LOD was ~148 pts above forecast LOD band

Tags correct: direction down, bearish rotation, lower close pressure

Tags wrong: compressed below value, close not near extreme, afternoon GOAT timing

Bias profitable if traded: ✗ — short thesis was invalidated by acceptance above 29,230–29,250

Invalidation check: Correct level, and it fired.

Overall score: 3/7

F2

Direction: ✗

Close range hit: ✗ — miss by ~64 pts below the forecast close band

HOD captured: ✗ — actual HOD exceeded forecast HOD band by ~57 pts

LOD captured: ✗ — actual LOD missed forecast LOD band by ~12 pts below

Tags correct: failed liquidation/reclaim then rotation, value compression

Tags wrong: slightly up, upside GOAT, mid-upper close, upside probe base case

Bias profitable if traded: ✗ — neutral-to-long failed once 29,250 broke

Invalidation check: Correct. Acceptance below 29,250 fired and invalidated the long bias.

Overall score: 2/7

F3

Direction: ✗

Close range hit: ✗ — miss by ~279 pts below the forecast close band

HOD captured: ✗ — actual failed below the projected upper continuation band

LOD captured: ✗ — actual LOD missed forecast LOD band by ~162 pts below

Tags correct: noon failed-breakdown/reclaim context

Tags wrong: up direction, afternoon breakout grind, upside continuation, GOAT up, upper-quartile close

Bias profitable if traded: ✗ — long bias stopped out below 29,370–29,380

Invalidation check: Correct. Sustained loss of 29,370–29,380 fired.

Overall score: 2/7

FORECAST EVOLUTION

Forecast quality degraded after pre-session. The pre-session forecast caught the real signal first: bearish bias below prior value, failed reclaim risk, and afternoon rotation lower. F1 kept the right bearish direction but used levels far too low and missed the squeeze to 29,487. F2 flipped too early to neutral/long. F3 overfit the 14:00 breakout and failed to treat the rejection as a regime reset.

LESSONS

When price probes above a reclaim level but fails to accept above the next supply shelf, keep the bearish thesis alive; do not treat a wick through reclaim as confirmation.

At 10:00, do not project deep downside targets if the actual session has already reclaimed above the short invalidation shelf; reset the range upward before forecasting LOD.

At noon, separate "failed liquidation reclaim" from "bullish continuation"; require acceptance above the late-morning supply shelf before flipping long.

At 14:00, a breakout into supply is not a GOAT long unless it holds above the breakout base after the first pullback.

Close-near-extreme tags need stricter evidence: if afternoon rejection breaks demand into the final hour, forecast near-LOD close rather than midrange.

JSON
{
  "actual_summary": {
    "direction": "down",
    "open_approx": 29281.0,
    "close_approx": 29231.0,
    "hod_approx": 29487.0,
    "lod_approx": 29208.0,
    "net_range_pct_open_to_close": -0.1708,
    "intraday_span_pts": 279
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 9,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction down",
        "afternoon failed_reclaim_then_rotation_lower",
        "goat_direction down",
        "sell_reclaims_below_prior_value"
      ],
      "tags_wrong": [
        "gap_down_acceptance_morning_probe_midday_balance",
        "gap_down_probe_then_rotation",
        "close_near_extreme no_mid_lower_range"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Close was slightly stronger than the predicted net-pct band and the session was more failed-reclaim liquidation than simple gap-down acceptance."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 111,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 148,
      "tags_correct": [
        "direction down",
        "failed_reclaim_lower_high_bearish_rotation",
        "downside_probe_or_lower_close"
      ],
      "tags_wrong": [
        "compressed_below_value",
        "close_near_extreme no",
        "afternoon goat timing"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "Forecast anchored too low after 10:00 and missed the rally to 29487 before the final bearish rotation."
    },
    "F2": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 64,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 12,
      "tags_correct": [
        "failed_liquidation_reclaim_then_rotation",
        "chop_value_compression"
      ],
      "tags_wrong": [
        "slightly_up",
        "goat_direction up",
        "upside_probe_then_fade_or_midrange_close",
        "no_mid_upper_range"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "It flipped neutral-to-long into a failed reclaim day and underestimated the late downside break."
    },
    "F3": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 279,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 162,
      "tags_correct": [
        "noon_failed_breakdown_reclaim"
      ],
      "tags_wrong": [
        "direction up",
        "afternoon_breakout_then_grind",
        "upside_continuation_with_pullbacks",
        "goat_direction up",
        "yes_upper_quartile close"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "It treated the 14:00 push as continuation instead of a supply rejection/regime reset."
    }
  },
  "evolution": "Forecasts did not improve as the day progressed. The pre-session forecast had the best read: bearish below prior value, failed reclaim risk, and afternoon rotation lower. F1 kept direction but had poor level placement. F2 and F3 overreacted to reclaim/breakout behavior and missed the failed-reclaim reversal into a near-LOD close.",
  "summary": "The correct signal was bearish failed-reclaim rotation, first captured pre-session. Later forecasts increasingly overfit intraday upside probes and failed to respect supply rejection near the session high.",
  "lessons": [
    "When price probes above a reclaim level but fails to accept above the next supply shelf, keep the bearish thesis alive; do not treat a wick through reclaim as confirmation.",
    "At 10:00, do not project deep downside targets if the actual session has already reclaimed above the short invalidation shelf; reset the range upward before forecasting LOD.",
    "At noon, separate failed liquidation reclaim from bullish continuation; require acceptance above the late-morning supply shelf before flipping long.",
    "At 14:00, a breakout into supply is not a GOAT long unless it holds above the breakout base after the first pullback.",
    "Close-near-extreme tags need stricter evidence: if afternoon rejection breaks demand into the final hour, forecast near-LOD close rather than midrange."
  ]
}
