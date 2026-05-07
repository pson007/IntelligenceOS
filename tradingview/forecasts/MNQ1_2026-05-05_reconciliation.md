---
symbol: MNQ1
date: 2026-05-05
dow: Tue
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-05.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-05.json
made_at: 2026-05-06T19:50:12
---
ACTUAL OUTCOME

Open 27,988 / Close 28,135 / HOD 28,189 / LOD 27,970.5. Shape: bullish opening drive, midday consolidation and flush/reclaim, afternoon continuation to new high, then late pullback into a higher close.

STAGE GRADES

Pre-session

Direction: ✓

Close range hit: ✓

HOD captured: ✗

LOD captured: ✗

Tags correct: direction up, afternoon continuation, GOAT up

Tags wrong: gap_up_pullback_reclaim, opening_dip_then_afternoon_trend_up, bullish_hold_above_breakout_base, close_near_extreme

Bias profitable if traded: ✓, but only if treating the actual open as drive-first and buying pullbacks

Invalidation check: ✗ — 28,240 reclaim condition was too high and would have invalidated a correct long thesis

Overall score: 4/7

F1 — 10:00 ET

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✓

Tags correct: opening drive trend-up, breakout-and-hold, afternoon continuation, GOAT up

Tags wrong: close_near_extreme / near-HOD close

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained trade below 28,000 did not occur after cursor

Overall score: 6/7

F2 — 12:00 ET

Direction: ✓

Close range hit: ✗ — missed by 20 pts below 28,155

HOD captured: ✓

LOD captured: ✓

Tags correct: direction up, failed breakdown/reclaim trend-up, afternoon grind higher, GOAT up

Tags wrong: high-base consolidation, close_near_extreme

Bias profitable if traded: ✓

Invalidation check: ✓ — sustained break below 28,075 did not occur

Overall score: 6/7

F3 — 14:00 ET

Direction: ✓

Close range hit: ✗ — missed by 30 pts below 28,165

HOD captured: ✓

LOD captured: ✓

Tags correct: direction up, upward continuation, bullish GOAT, late HOD attempt

Tags wrong: close_near_extreme, no meaningful reversal

Bias profitable if traded: ✓, if avoiding chase above 28,185 as stated

Invalidation check: ✓ — sustained break below 28,095 did not occur

Overall score: 6/7

FORECAST EVOLUTION

Forecasts improved immediately at F1. Pre-session caught the broad up direction but used the wrong open template and unusable 28,240+ reclaim levels. F1 caught the real signal first: opening-drive trend-up with pullbacks holding and continuation favored. F2 and F3 refined the continuation path well, but both overestimated the close by missing the late supply rejection.

LESSONS

When the first 15–30 minutes is an immediate upside drive, change gap_up_pullback_reclaim to gap_up_drive; do not wait for a reclaim that never needs to happen.

Do not use a reclaim level above the actual session's reachable range as a validity gate. Today, 28,240 invalidated a correct long thesis even though HOD was only 28,189.

After noon, separate "high-base" from "range-then-flush-and-reclaim." Today's 12:28 flush to ~28,095 mattered and should be tagged explicitly.

Near-HOD close needs confirmation after 15:00. If price rejects late supply and closes 54 pts below HOD, mark late_pullback, not close_near_extreme.

For post-10:00 forecasts, grade LOD against post-cursor tradeable lows; F1 correctly raised LOD toward the defended 10:18 pullback zone.

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
      "lod_miss_pts": 79.5,
      "tags_correct": ["direction_up", "afternoon_continuation", "goat_direction_up"],
      "tags_wrong": ["gap_up_pullback_reclaim", "opening_dip_then_afternoon_trend_up", "bullish_hold_above_breakout_base", "close_near_extreme"],
      "bias_profitable": true,
      "invalidation_correct": false,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "The 28240 reclaim gate was too high and would have mechanically invalidated a correct bullish day."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": ["opening_drive_trend_up", "breakout_and_hold", "afternoon_continuation", "goat_direction_up"],
      "tags_wrong": ["close_near_extreme"],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "It expected an upper-quadrant or near-HOD close, but late supply pulled price back to 28135."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 20,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": ["direction_up", "failed_breakdown_midday_reclaim_trend_up", "afternoon_grind_higher", "goat_direction_up"],
      "tags_wrong": ["high_base_consolidation", "close_near_extreme"],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Close band was too high because it underweighted the late pullback risk."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 30,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": ["direction_up", "upward_continuation", "bullish_goat", "late_hod_attempt"],
      "tags_wrong": ["close_near_extreme", "no_meaningful_reversal"],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "It saw the afternoon continuation but missed the late rejection from supply."
    }
  },
  "evolution": "The forecasts improved sharply from pre-session to F1. Pre-session had the right directional lean but wrong open template and bad reclaim levels. F1 caught the real signal first by identifying opening-drive trend-up; F2 and F3 kept the bullish continuation call but both overestimated the close because they did not price in the late pullback.",
  "summary": "The day was a clean bullish trend session with the best long opportunity in the opening drive and later continuation after lunch reclaim. The main forecasting error was not direction, but structure precision: the models repeatedly overstated near-HOD close odds and under-tagged the late supply rejection.",
  "lessons": [
    "When the first 15–30 minutes is an immediate upside drive, switch the open tag to gap_up_drive instead of waiting for gap_up_pullback_reclaim.",
    "Reject reclaim thresholds above the live session's plausible range; 28240 was unusable when actual HOD was 28189.",
    "Tag lunch as range_then_flush_and_reclaim when a midday dip tests the lower intraday range and recovers, instead of generic high-base consolidation.",
    "Require post-15:00 confirmation before forecasting close_near_extreme; a 54-point rejection from HOD is late_pullback behavior.",
    "For intraday forecasts, grade LOD against post-cursor actionable lows and raise the LOD band to the first defended RTH pullback zone."
  ]
}
