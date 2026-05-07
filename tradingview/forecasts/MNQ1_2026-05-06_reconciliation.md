---
symbol: MNQ1
date: 2026-05-06
dow: Wed
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-06.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-06.json
made_at: 2026-05-06T20:16:23
---
ACTUAL OUTCOME

Open 28,389.25 / Close 28,710.50 / HOD 28,725.75 / LOD 28,336.50. Shape: bullish trend day with early flush, fast reclaim, midday higher-low base, and steady afternoon continuation into a near-HOD close.

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✗ — close overshot implied +0.55% upper band by ~165 pts

HOD captured: ✗ — upside extension exceeded expected span

LOD captured: ✓ — early flush/reclaim thesis was directionally right

Tags correct: direction up, dip/reclaim, higher-low lunch, afternoon grind, GOAT up, close near HOD

Tags wrong: gap_up_rotational_reclaim; actual was more rotational_open_then_drive

Bias profitable if traded: ✓

Invalidation check: ✓ — 28,300 reclaimed; no acceptance below 28,220; VWAP control restored

Overall score: 5/7

F1

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✓

Tags correct: stop-hunt reclaim, trend up, higher-low lunch, bullish continuation, GOAT up, close near extreme

Tags wrong: failed_breakdown_midday_reclaim was slightly too dramatic; no real midday breakdown

Bias profitable if traded: ✓

Invalidation check: ✓ — no sustained acceptance below 28,335–28,360

Overall score: 7/7

F2

Direction: ✓

Close range hit: ✗ — missed by ~0.5 pts above 28,710 upper band

HOD captured: ✓

LOD captured: ✗ — rest-of-day LOD band was too low; midday pullback held higher

Tags correct: up, digestion, afternoon continuation, GOAT up, near upper quartile close

Tags wrong: failed_breakdown_midday_reclaim overstated the weakness

Bias profitable if traded: ✓

Invalidation check: ✓ — no sustained acceptance below ~28,390

Overall score: 5/7

F3

Direction: ✓

Close range hit: ✗ — close overshot upper band by ~20.5 pts

HOD captured: ✓ — 28,725.75 was effectively at the top of the 28,665–28,725 band

LOD captured: ✗ — pullback risk was overstated; price held firmer after 14:00

Tags correct: stop-hunt reclaim, lunch higher-low continuation, late near-HOD grind, close near HOD

Tags wrong: none material

Bias profitable if traded: ✓

Invalidation check: ✓ — 28,500 / 28,455 never failed

Overall score: 5/7

FORECAST EVOLUTION

Forecasts improved sharply at F1. The pre-session read caught the core direction and reclaim logic but undersized the day. F1 was the first stage to catch the real signal cleanly: opening flush rejected, demand held, and the day shifted into stop-hunt-reclaim trend-up. F2 and F3 stayed directionally correct but became too conservative on final upside and too pessimistic on pullback depth.

LESSONS

After a 09:30 flush reclaims by 10:00 and holds above the opening sweep, upgrade from "dip/reclaim" to "stop-hunt-reclaim trend day"; do not leave it as generic gap-up rotation.

When early LOD is already set and lunch holds higher lows, raise rest-of-day LOD bands; F2/F3 kept pullback bands too low versus the actual 13:00 higher-low base.

If price holds above VWAP through lunch and compresses near HOD by 14:00, widen close/HOD upside bands instead of capping the day at nearby supply.

Keep "failed_breakdown" tags only for real acceptance below demand; today had an early sweep and reclaim, not a sustained breakdown.

The pre-session model needs larger upside-span allowance on strong overnight posture plus early RTH reclaim; actual span was 389.25 pts versus the 180–320 pt forecast.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 28389.25,
    "close_approx": 28710.5,
    "hod_approx": 28725.75,
    "lod_approx": 28336.5,
    "net_range_pct_open_to_close": 1.1316,
    "intraday_span_pts": 389.25
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 165,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction up",
        "dip_then_reclaim",
        "higher_low_lunch",
        "afternoon_grind",
        "goat_direction_up",
        "close_near_extreme"
      ],
      "tags_wrong": [
        "gap_up_rotational_reclaim"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Upside was materially undersized; close and HOD exceeded the implied range."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "stop_hunt_reclaim",
        "trend_up",
        "higher_low_lunch",
        "bullish_continuation",
        "goat_direction_up",
        "close_near_extreme"
      ],
      "tags_wrong": [
        "failed_breakdown_midday_reclaim_overstated"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 7,
      "overall_max": 7,
      "biggest_miss": "Minor structure wording only; the forecast captured the session well."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 0.5,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 65,
      "tags_correct": [
        "direction up",
        "sideways_to_up_digestion",
        "afternoon_continuation",
        "goat_direction_up",
        "near_upper_quartile_close"
      ],
      "tags_wrong": [
        "failed_breakdown_midday_reclaim_overstated"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Rest-of-day downside band was too low after buyers had already established a higher-low base."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 20.5,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 20,
      "tags_correct": [
        "stop_hunt_reclaim",
        "lunch_higher_low_continuation",
        "late_day_near_HOD_grind",
        "close_near_HOD"
      ],
      "tags_wrong": [],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "The forecast capped the close too low and expected a deeper pullback than occurred."
    }
  },
  "evolution": "The pre-session forecast had the right bullish framework but undersized the move. F1 caught the true signal first by identifying the opening flush as a failed sell attempt and projecting continuation. F2 and F3 preserved the bullish bias but did not fully adapt to the strength of the higher-low structure and late-day stair-step continuation.",
  "summary": "The forecast suite was directionally strong, with F1 the cleanest and most actionable forecast. The main error was not direction but magnitude: later forecasts kept close and pullback bands too conservative for a full bullish trend day.",
  "lessons": [
    "After a 09:30 flush reclaims by 10:00 and holds above the opening sweep, upgrade from dip/reclaim to stop-hunt-reclaim trend day.",
    "When lunch holds higher lows above VWAP, raise rest-of-day LOD bands instead of anchoring to the morning flush.",
    "If price compresses near HOD into 14:00, widen the close/HOD upside band rather than capping at nearby supply.",
    "Use failed_breakdown only when price accepts below demand; today was a sweep and reclaim, not a true breakdown.",
    "On strong overnight posture plus early RTH reclaim, allow larger intraday span than the default 180–320 pt medium-move band."
  ]
}
