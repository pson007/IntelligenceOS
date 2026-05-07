---
symbol: MNQ1
date: 2026-04-30
dow: Thu
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-30.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-30.json
made_at: 2026-05-06T19:46:53
---
ACTUAL OUTCOME

Open 27,486.5 / Close 27,578.25 / HOD 27,624.5 / LOD 27,163.0. Shape: violent gap-up failed open flush into a 10:30 LOD, then stair-step recovery, lunch higher-low build, and sustained afternoon reclaim into a near-HOD close. 

Pasted text

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✗ — expected support above ~27,365–27,390; actual LOD was 27,163, about 202 pts below the core defended zone.

Tags correct: direction up, close_near_extreme yes_closer_to_HOD, bullish higher-low/reclaim concept, afternoon continuation concept

Tags wrong: open_dip_then_reclaim, stop_hunt_reclaim_then_afternoon_grind, controlled_upside_continuation, goat_direction up

Bias profitable if traded: ✗ — early long bias was invalidated by the opening liquidation; only a later reset after 10:30 would have worked.

Invalidation check: Correct. The stated invalidations did fire: 09:30–10:00 accepted below 27,365, price failed VWAP, and the first rally failed below 27,475 into the 10:30 low.

Overall score: 4/7

FORECAST EVOLUTION

Only the pre-session forecast was provided, so there was no staged improvement to evaluate. It caught the final bullish direction and close zone, but missed the executable path: the real signal was not an opening long reclaim, but the 10:30 defended-demand reversal after the deep liquidation flush.

LESSONS

When the first 30 minutes loses 27,365 and remains below VWAP, immediately suspend the pre-session long thesis instead of treating the flush as a standard dip-buy.

For gap-up failed opens, widen the downside LOD band materially; today's 27,163 LOD was far below the forecast's 27,365–27,390 support.

Separate "green close" from "profitable long bias": the final direction was right, but early long execution would likely have stopped out.

Use opening_flush_to_afternoon_reclaim when the day makes LOD around 10:30 and only trends higher after a lunch higher-low base.

Do not assign GOAT long to the open when the opening impulse is liquidation; today's GOAT direction was down at 09:35, with the long opportunity only after the washout stabilized.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 27486.5,
    "close_approx": 27578.25,
    "hod_approx": 27624.5,
    "lod_approx": 27163.0,
    "net_range_pct_open_to_close": 0.3338,
    "intraday_span_pts": 461.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 202,
      "tags_correct": [
        "direction: up",
        "close_near_extreme: yes_closer_to_HOD",
        "bullish higher-low/reclaim concept",
        "afternoon continuation concept"
      ],
      "tags_wrong": [
        "structure: stop_hunt_reclaim_then_afternoon_grind",
        "open_type: open_dip_then_reclaim",
        "afternoon_drive: controlled_upside_continuation",
        "goat_direction: up"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "Forecast got final direction and close zone right, but missed the violent opening liquidation depth and the true 10:30 LOD reversal setup."
    }
  },
  "evolution": "Only the pre-session forecast was provided, so there was no forecast progression to compare. The pre-session forecast caught the final bullish close but not the tradable path: its long thesis invalidated early, while the actual opportunity emerged after the deep 10:30 washout and later higher-low build.",
  "summary": "The forecast was directionally right and close-price accurate, but structurally too clean and too early. The main failure was treating the open as a manageable dip-reclaim instead of a gap-up failed open flush that required standing down until defended demand formed near 27,163.",
  "lessons": [
    "When the first 30 minutes loses 27365 and remains below VWAP, immediately suspend the pre-session long thesis instead of treating the flush as a standard dip-buy.",
    "For gap-up failed opens, widen the downside LOD band materially; today's 27163 LOD was far below the forecast's 27365-27390 support.",
    "Separate green close from profitable long bias: the final direction was right, but early long execution would likely have stopped out.",
    "Use opening_flush_to_afternoon_reclaim when the day makes LOD around 10:30 and only trends higher after a lunch higher-low base.",
    "Do not assign GOAT long to the open when the opening impulse is liquidation; today's GOAT direction was down at 09:35, with the long opportunity only after the washout stabilized."
  ]
}
