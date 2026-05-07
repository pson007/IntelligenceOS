---
symbol: MNQ1
date: 2026-05-01
dow: Fri
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-01.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-01.json
made_at: 2026-05-06T19:47:22
---
ACTUAL OUTCOME

Opened ~27,632.50, closed 27,836.75, HOD 27,917.50, LOD 27,615.00: strong gap-up/opening-drive session into late-morning highs, then broad high-balance rotation and a late fade that still preserved a bullish close.

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✗ — actual close missed high end by ~10.85 pts

HOD captured: ✓

LOD captured: ✗ — forecast expected a dip toward 27,540–27,560; actual LOD held much higher at 27,615

Tags correct: direction up, goat_direction up, close_near_extreme yes_closer_to_HOD

Tags wrong: open_dip_then_reclaim, stop_hunt_reclaim_then_afternoon_grind, bullish_hold_above_reclaim_zone, controlled_upside_grind

Bias profitable if traded: ✓

Invalidation check: Correct. The named invalidations did not fire: price did not accept below 27,560, was not below VWAP after 10:15, and did not fail 27,625 back below 27,590.

Overall score: 5/7

FORECAST EVOLUTION

Only the pre-session forecast was provided. It caught the key directional signal and the early GOAT long correctly, but misread the path: this was not a stop-hunt/dip-reclaim day. It was a gap-up drive that already had buyers in control from the open, followed by balance below late-morning supply.

LESSONS

When MNQ gaps above the reclaim shelf and immediately accepts higher, switch the open tag from open_dip_then_reclaim to gap_up_drive; do not wait for a dip that never comes.

If the first 15 minutes expands more than 150 pts upward without losing VWAP, prioritize opening-drive continuation over "buy dips on reclaim."

For strong opening drives, separate morning opportunity from afternoon structure: after HOD forms before noon, tag the rest as high_balance_rotation unless price keeps making clean impulse highs.

Do not project LOD back into overnight demand when RTH opens above it and never tests it; raise the LOD band to the first defended RTH pullback zone.

Keep controlled_upside_grind only when afternoon price steadily expands; if price rotates below supply and fades late, use failed_late_push_then_fade.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 27632.5,
    "close_approx": 27836.75,
    "hod_approx": 27917.5,
    "lod_approx": 27615.0,
    "net_range_pct_open_to_close": 0.7392,
    "intraday_span_pts": 302.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 10.85,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 55.0,
      "tags_correct": [
        "direction: up",
        "goat_direction: up",
        "close_near_extreme: yes_closer_to_HOD"
      ],
      "tags_wrong": [
        "structure: stop_hunt_reclaim_then_afternoon_grind",
        "open_type: open_dip_then_reclaim",
        "lunch_behavior: bullish_hold_above_reclaim_zone",
        "afternoon_drive: controlled_upside_grind"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "The forecast expected a dip/reclaim and afternoon grind, but the actual session was an immediate gap-up opening drive followed by high-balance rotation and a late fade."
    }
  },
  "evolution": "Only the pre-session forecast was available. It caught the bullish direction and opening long opportunity, but did not identify the true session structure: immediate gap-up drive into late-morning HOD, then rotational balance below supply.",
  "summary": "The forecast was directionally useful and tactically profitable, with invalidation logic behaving correctly. Its main error was path classification: it looked for stop-hunt/reclaim mechanics instead of recognizing clean opening-drive acceptance.",
  "lessons": [
    "When MNQ gaps above the reclaim shelf and immediately accepts higher, switch the open tag from open_dip_then_reclaim to gap_up_drive.",
    "If the first 15 minutes expands more than 150 pts upward without losing VWAP, prioritize opening-drive continuation over buy-dips-on-reclaim.",
    "After a strong morning HOD forms before noon, classify the afternoon as high-balance rotation unless price keeps making clean impulse highs.",
    "Do not anchor LOD to overnight demand if RTH opens above it and never tests it; raise the LOD band to the first defended RTH pullback zone.",
    "Use failed_late_push_then_fade when afternoon price rotates below supply and fades into close instead of expanding steadily."
  ]
}
