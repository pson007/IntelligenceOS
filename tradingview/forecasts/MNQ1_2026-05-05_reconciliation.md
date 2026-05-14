---
symbol: MNQ1
date: 2026-05-05
dow: Tue
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-05.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-05.json
made_at: 2026-05-14T19:11:32
---
ACTUAL OUTCOME

MNQ opened around 27,988, closed 28,135, made HOD 28,189 and LOD 27,970.5; shape was a gap-up/open-drive trend day with midday consolidation/flush, afternoon new highs, then late pullback into a higher close.

STAGE GRADES
PRE-SESSION

Direction: ✓

Close range hit: ✓

HOD captured: ✗

LOD captured: ✗

Tags correct: direction up, goat_direction up, afternoon upside continuation

Tags wrong: gap_up_pullback_reclaim, opening_dip_then_afternoon_trend_up, bullish_hold_above_breakout_base, close_near_extreme yes

Bias profitable if traded: ✓

Invalidation check: ✗ — the 28,240 reclaim trigger was miscalibrated far above the actual session. It would have falsely invalidated a profitable long day.

Overall score: 3/7

F1

Direction: ✓

Close range hit: ✓

HOD captured: ✗ — actual HOD 28,189 was 14 pts above the 28,175 top

LOD captured: ✗ — post-forecast pullback low was about 28,045, roughly 5 pts above the 28,015–28,040 band

Tags correct: bullish, early_drive_to_upper_balance, controlled_upside_extension, goat long

Tags wrong: close_near_extreme yes

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained trade below 28,015 did not occur

Overall score: 5/7

F2

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✗ — post-forecast LOD was about 28,095, roughly 10 pts above the 28,045–28,085 band

Tags correct: bullish, open_drive_to_high_balance_continuation, upper_balance_with_dip_buys, bullish_breakout_or_high_grind, goat long

Tags wrong: close_near_extreme yes_high_close

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained acceptance below 28,030 did not occur

Overall score: 6/7

F3

Direction: ✓

Close range hit: ✗ — actual close 28,135 was 10 pts below the 28,145–28,180 band

HOD captured: ✓

LOD captured: ✓

Tags correct: bullish, rotational_morning_to_afternoon_breakout, controlled_breakout_attempt, goat long

Tags wrong: high_balance_above_value missed the lunch flush/reclaim, close_near_extreme yes_upper_third overstated finish quality

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained break below 28,075 did not occur

Overall score: 6/7

FORECAST EVOLUTION

Forecast quality improved after live structure appeared. Pre-session had the correct bullish direction but its level map was badly too high and would have invalidated the correct thesis. F1 caught the real signal first: bullish open drive, shallow pullbacks, and long bias. F2 was the cleanest forecast overall, capturing close, HOD, direction, structure, and trade bias, with only a slightly too-deep LOD expectation and overstated high-close call. F3 kept the bullish read but pushed the close too high and underweighted late supply rejection risk.

LESSONS

When the session opens far below the pre-session ladder but immediately drives, re-anchor levels to RTH open/demand, not stale overnight references like 28,240.

After a clean open-drive GOAT, do not require an arbitrary higher reclaim to validate longs; use VWAP, higher lows, and defended pullback shelves instead.

For post-10:30 forecasts, raise LOD expectations after higher-low confirmation; F2 still looked for 28,045–28,085 even though buyers were defending closer to 28,095.

When afternoon targets sit inside supply, separate HOD projection from close projection; today hit 28,189 but closed 54 pts off the high.

If lunch produces a flush and reclaim, tag it explicitly as range_then_flush_and_reclaim, not generic high balance.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 27988.0,
    "close_approx": 28135.0,
    "hod_approx": 28189.0,
    "lod_approx": 27970.5,
    "net_range_pct_open_to_close": 0.5252,
    "intraday_span_pts": 218.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": null,
      "tags_correct": [
        "direction up",
        "goat_direction up",
        "afternoon upside continuation"
      ],
      "tags_wrong": [
        "gap_up_pullback_reclaim",
        "opening_dip_then_afternoon_trend_up",
        "bullish_hold_above_breakout_base",
        "close_near_extreme yes"
      ],
      "bias_profitable": true,
      "invalidation_correct": false,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "Level map was too high; the 28240 reclaim invalidation would have falsely rejected a bullish trend day."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 5,
      "tags_correct": [
        "bullish",
        "early_drive_to_upper_balance",
        "controlled_upside_extension",
        "goat long"
      ],
      "tags_wrong": [
        "close_near_extreme yes"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Underestimated upside extension and expected a slightly deeper pullback than the market gave."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 10,
      "tags_correct": [
        "bullish",
        "open_drive_to_high_balance_continuation",
        "upper_balance_with_dip_buys",
        "bullish_breakout_or_high_grind",
        "goat long"
      ],
      "tags_wrong": [
        "close_near_extreme yes_high_close"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "LOD band stayed too deep after higher-low confirmation; close quality was also overstated."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 10,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "bullish",
        "rotational_morning_to_afternoon_breakout",
        "controlled_breakout_attempt",
        "goat long"
      ],
      "tags_wrong": [
        "high_balance_above_value",
        "close_near_extreme yes_upper_third"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Close projection was too high because late rejection from supply was underweighted."
    }
  },
  "evolution": "The pre-session forecast got the direction but missed the usable level framework. F1 caught the live bullish open-drive signal first. F2 was the strongest forecast because it aligned direction, close, HOD, structure, and trade bias. F3 stayed directionally correct but overestimated the closing strength after afternoon supply rejection risk appeared.",
  "summary": "The forecasts correctly leaned bullish, and live updates improved materially once RTH structure replaced the stale pre-session ladder. The main miss was not direction but finish quality: the day made new highs, then rejected late instead of closing near the extreme.",
  "lessons": [
    "When RTH opens far below the forecast ladder but immediately drives, re-anchor levels to RTH open/demand instead of stale overnight references.",
    "After a clean open-drive GOAT, validate longs through VWAP, higher lows, and defended pullback shelves rather than requiring an arbitrary higher reclaim.",
    "After post-10:30 higher-low confirmation, raise the LOD forecast; do not keep targeting deep demand unless the reclaim shelf breaks.",
    "Separate HOD projection from close projection when price is approaching afternoon supply; a target hit does not imply a high close.",
    "Tag lunch explicitly as range_then_flush_and_reclaim when the midday low is swept and recovered, rather than calling it generic high balance."
  ]
}
