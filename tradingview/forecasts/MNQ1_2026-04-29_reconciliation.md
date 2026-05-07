---
symbol: MNQ1
date: 2026-04-29
dow: Wed
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-29.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-29.json
made_at: 2026-05-06T19:46:23
---
ACTUAL OUTCOME

Open 27206.75 / Close 27334.75 / HOD 27338.25 / LOD 27124.25. Bullish recovery day: opening flush held demand, midday weakness was absorbed, then a late drive broke supply and closed near HOD.

STAGE GRADES

pre_session_forecast

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✓

Tags correct: direction up, goat_direction up, close_near_extreme yes_closer_to_HOD, defended demand, bullish reclaim

Tags wrong: open_type open_dip_then_reclaim, structure stop_hunt_reclaim_then_afternoon_grind, lunch_behavior bullish balance above 27200, afternoon_drive controlled_upside_grind

Bias profitable if traded: ✓

Invalidation check: mostly correct. Price did not sustain below 27120 after 09:45, reclaimed 27240 before noon, and did not form a VWAP lower-high breakdown through the opening low. The thesis stayed valid.

Overall score: 6/7

FORECAST EVOLUTION

Only the pre-session forecast was provided, so there is no intra-day evolution to compare. It caught the main signal early: opening demand hold, reclaim, bullish close near HOD. The main miss was structural precision: the actual day was less "controlled grind" and more opening flush, midday demand retest, then late breakout through 27300–27340 supply.

LESSONS

When the opening flush holds 27120–27130 and reclaims 27240 before noon, keep the bullish thesis active even if the path stays rotational.

Label this setup as opening_flush_late_bullish_reclaim, not clean stop_hunt_reclaim_then_afternoon_grind, when price retests demand around lunch before launching.

Separate "afternoon grind" from "late breakout": if supply at 27300–27340 is not cleared until after 14:40, tag the drive as late breakout, not controlled continuation.

Keep LOD bands tight around defended demand only when the first flush holds cleanly; today 27120–27160 worked and the exact LOD was 27124.25.

Conditional long bias was correct, but the best GOAT window was not morning; future forecasts should shift GOAT later when lunch demand retest produces the higher-low launch.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 27206.75,
    "close_approx": 27334.75,
    "hod_approx": 27338.25,
    "lod_approx": 27124.25,
    "net_range_pct_open_to_close": 0.4705,
    "intraday_span_pts": 214
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction: up",
        "goat_direction: up",
        "close_near_extreme: yes_closer_to_HOD",
        "defended demand",
        "bullish reclaim"
      ],
      "tags_wrong": [
        "open_type: open_dip_then_reclaim",
        "structure: stop_hunt_reclaim_then_afternoon_grind",
        "lunch_behavior: bullish_reclaim_or_balance_above_27200",
        "afternoon_drive: controlled_upside_grind"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Structure was too smooth: actual path was opening flush, midday selloff into defended demand, then late breakout to HOD."
    }
  },
  "evolution": "Only the pre-session forecast was provided, so no stage-by-stage improvement can be measured. The pre-session forecast caught the real signal first by identifying the 27120-27160 demand hold, 27240 reclaim condition, bullish close, and close-near-HOD outcome.",
  "summary": "The forecast was directionally strong and tactically usable because the demand-hold/reclaim conditions stayed valid. Its main weakness was tag precision: the day was a late bullish reclaim/breakout after lunch weakness, not a clean morning stop-hunt reclaim into controlled afternoon grind.",
  "lessons": [
    "When the opening flush holds 27120-27130 and reclaims 27240 before noon, keep the bullish thesis active even if the path stays rotational.",
    "Use opening_flush_late_bullish_reclaim when price retests demand around lunch before launching, not stop_hunt_reclaim_then_afternoon_grind.",
    "If 27300-27340 supply is not broken until after 14:40, tag the afternoon as late_breakout_to_hod rather than controlled_upside_grind.",
    "Keep the defended-demand LOD band centered on 27120-27160 when the first flush holds cleanly; today exact LOD was 27124.25.",
    "Move GOAT timing later when the decisive higher-low launch forms after lunch rather than during the initial morning reclaim."
  ]
}
