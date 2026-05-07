---
symbol: MNQ1
date: 2026-04-27
dow: Mon
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-27.png
forecasts_graded: ['pre_session', '1000', '1200']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-27.json
made_at: 2026-05-06T19:44:34
---
ACTUAL OUTCOME

Open ~27,410 / Close 27,444.75 / HOD 27,452.25 / LOD 27,298. Shape: early liquidation into late-morning LOD, then controlled afternoon reversal-trend into a near-HOD close.

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✗ — miss ~20.1 pts below implied +0.20% lower bound

HOD captured: ✗ — projected upside too high, miss ~67.8 pts below 27,520

LOD captured: ✗ — actual flushed ~82 pts below 27,380

Tags correct: direction up, goat_direction up, close_near_extreme, afternoon upside grind/reclaim theme

Tags wrong: open_dip_then_reclaim, LOD demand zone too shallow, magnitude too large, structure too clean

Bias profitable if traded: ✓ — buying failed flush/reclaim worked if entry waited for reclaim, not knife-catching

Invalidation check: Mostly correct. The early flush broke the named demand zone, but the "10:00 holds below 27,380 with no fast reclaim" condition did not cleanly persist; price reclaimed enough to keep the bullish thesis alive.

Overall score: 4/7

F1

Direction: ✓

Close range hit: ✗ — miss 45.25 pts below 27,490

HOD captured: ✗ — miss 72.75 pts below 27,525

LOD captured: ✓

Tags correct: stop_hunt_reclaim_trend_up, goat_direction long, close_near_extreme, afternoon continuation

Tags wrong: lunch compression above 27,400 was premature, upside magnitude exaggerated

Bias profitable if traded: ✗ — preferred long zone likely got stressed/stopped by the 11:25 lower-low sweep before the real reversal

Invalidation check: Partly correct. The warning level near 27,320 did fail again, so the active long bias should have been invalidated before the later reclaim.

Overall score: 4/7

F2

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✗ — miss 2 pts below 27,300

Tags correct: failed_breakdown_midday_reclaim, sideways-to-up compression, moderate upside grind, bullish late-morning sweep, direction up

Tags wrong: close_near_extreme understated; actual close was near HOD, not just upper-third

Bias profitable if traded: ✓

Invalidation check: Correct. Post-12:00 sustained trade below 27,315 did not occur.

Overall score: 6/7

FORECAST EVOLUTION

Forecasts improved materially by F2. Pre-session caught the bullish reclaim theme but missed the depth of the liquidation and overstated upside. F1 identified the stop-hunt structure but chased too much upside and failed to respect the possibility of a second lower-low sweep. F2 caught the real signal first: late-morning failed breakdown into afternoon reclaim, with close/HOD bands close to actual.

LESSONS

After the first reclaim fails and price makes a second lower-low into 11:00–11:30, do not grade the day as a clean stop-hunt trend-up; re-label it as morning_flush_afternoon_reversal_trend.

At 10:00, keep the LOD band wide enough for a second sweep below the first flush low; today the real LOD came later at 11:25.

Once the 12:00 reclaim holds and 27,350–27,380 becomes support, move the close band toward upper-range/near-HOD immediately.

Do not project HOD 70–120 pts above the close band without confirmed afternoon expansion; today the HOD was only ~7.5 pts above close.

Distinguish "correct long thesis" from "tradable long setup"; F1's direction was right, but its entry/stop logic likely failed before the reversal.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 27410.0,
    "close_approx": 27444.75,
    "hod_approx": 27452.25,
    "lod_approx": 27298.0,
    "net_range_pct_open_to_close": 0.1268,
    "intraday_span_pts": 154
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 20.1,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 82.0,
      "tags_correct": [
        "direction up",
        "goat_direction up",
        "close_near_extreme",
        "afternoon upside grind/reclaim theme"
      ],
      "tags_wrong": [
        "open_dip_then_reclaim",
        "LOD demand zone too shallow",
        "upside magnitude too large",
        "structure too clean"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "The bullish thesis was right, but the forecast badly underestimated the morning flush depth and overestimated upside magnitude."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 45.25,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "stop_hunt_reclaim_trend_up",
        "goat_direction long",
        "close_near_extreme",
        "afternoon continuation"
      ],
      "tags_wrong": [
        "lunch compression above 27400",
        "upside magnitude exaggerated"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "F1 saw the reclaim setup but projected too much upside and likely got long before the second sweep to the real LOD."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 2.0,
      "tags_correct": [
        "failed_breakdown_midday_reclaim",
        "sideways-to-up compression",
        "moderate upside grind",
        "bullish late-morning sweep",
        "direction up"
      ],
      "tags_wrong": [
        "close_near_extreme understated"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "F2 still slightly undercalled the near-HOD close behavior, but otherwise captured the actual afternoon reversal trend."
    }
  },
  "evolution": "The forecasts improved from broad bullish-reclaim framing to accurate midday reversal recognition. Pre-session had the correct directional lean but missed both downside depth and upside magnitude. F1 correctly identified stop-hunt behavior but was too aggressive on entry and upside targets. F2 was the first stage to catch the real signal: failed breakdown into late-morning demand hold, then afternoon reclaim-grind into a near-HOD close.",
  "summary": "The day rewarded the bullish reversal thesis, but only after a deeper second liquidation sweep than early forecasts allowed. F2 was the best forecast because it adjusted magnitude lower, respected the late-morning sweep, and placed the close/HOD bands around the actual finish.",
  "lessons": [
    "After the first reclaim fails and price makes a second lower-low into 11:00–11:30, re-label the structure as morning_flush_afternoon_reversal_trend instead of clean stop_hunt_reclaim_trend_up.",
    "At 10:00, keep the LOD band wide enough for a second sweep below the first flush low; today the final LOD came at 11:25.",
    "Once the 12:00 reclaim holds above the late-morning demand shelf, move the close target toward upper-range/near-HOD immediately.",
    "Do not project HOD 70–120 pts above the close band without confirmed afternoon volume expansion; today HOD exceeded close by only about 7.5 pts.",
    "Separate correct direction from tradable execution; F1's long thesis was directionally right, but its entry/stop logic likely failed before the real reversal."
  ]
}
