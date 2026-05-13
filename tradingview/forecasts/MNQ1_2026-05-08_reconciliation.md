---
symbol: MNQ1
date: 2026-05-08
dow: Fri
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-08.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-08.json
made_at: 2026-05-12T07:13:45
---
ACTUAL OUTCOME

MNQ opened near 28878, made its LOD almost immediately near 28863.5, then ran a clean bullish open-drive trend day to a 29340.75 HOD and 29339.5 close, finishing at the high after midday stair-step continuation and late-session push.

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✗ — predicted roughly +0.25% to +0.80%, actual was +1.60%; close missed high side by about 230 pts

HOD captured: ✗ — forecast capped too low near 28950–28980 / medium span; actual HOD was 29340.75

LOD captured: ✓ — expected the open to defend roughly 28840–28860 / above 28790; actual LOD was 28863.5

Tags correct: direction up, goat_direction up, morning long, demand defended, VWAP control, higher-value continuation

Tags wrong: gap_up_pullback_reclaim, high_balance, attempted_continuation_then_late_pullback_risk, no_mid_upper_range, medium move

Bias profitable if traded: ✓

Invalidation check: ✓ — bearish invalidations did not fire; no acceptance below VWAP after reclaim, no 28790 break, no failed drive below 28820

Overall score: 4/7

FORECAST EVOLUTION

Only the pre-session forecast was provided. It caught the correct directional regime and the actionable long bias immediately, but it underfit the strength: the day was not a pullback-reclaim into high balance, but a full bullish open-drive trend day with persistent higher lows and a close at the high. The real signal was already present at the open/09:30 launch, and the forecast identified the right side but not the magnitude or structure.

LESSONS

When a gap-up open immediately defends the first 5-minute low and reclaims above the open, upgrade from gap_up_pullback_reclaim to bullish_open_drive_trend_day instead of waiting for a deeper pullback.

Do not cap upside at nearby supply after price accepts above it in the first hour. Once 28950–28980 was absorbed, the forecast needed a widened HOD/close band.

A clean VWAP hold plus higher lows into lunch should convert "high balance" into "trend continuation." Lunch did not rotate; it stair-stepped.

On strong overnight posture plus early RTH reclaim, allow a larger span than the default 260–390 pts. Actual span was 477.25 pts, consistent with prior lesson on expanding move-size bands.

Remove late-fade risk from the active bias when afternoon price holds high-level consolidation and makes no failed reclaim. The close-near-HOD condition was visible before the final push.

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
        "goat_direction up",
        "morning long",
        "demand defended",
        "VWAP control",
        "higher-value continuation"
      ],
      "tags_wrong": [
        "gap_up_pullback_reclaim",
        "gap_up_pullback_reclaim_then_high_balance",
        "high_balance_with_vwap_hold",
        "attempted_continuation_then_late_pullback_risk",
        "no_mid_upper_range",
        "medium move"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "Forecast correctly leaned long but badly undercalled trend-day strength, HOD extension, and close-near-high behavior."
    }
  },
  "evolution": "Only the pre-session forecast was provided. It caught the correct side and the best tactical bias, but it treated the setup as a pullback-reclaim/high-balance day instead of a full bullish open-drive trend day. The real signal appeared immediately at the 09:30 launch and was confirmed by the 10:00 continuation above the forecast's upside cap.",
  "summary": "The pre-session forecast was directionally useful and tradable, but too conservative on structure and magnitude. Its main error was respecting nearby supply too much after price had already accepted above it.",
  "lessons": [
    "When a gap-up open immediately defends the first 5-minute low and reclaims above the open, upgrade from gap_up_pullback_reclaim to bullish_open_drive_trend_day instead of waiting for a deeper pullback.",
    "Do not cap upside at nearby supply after price accepts above it in the first hour; once 28950-28980 was absorbed, widen the HOD and close bands.",
    "A clean VWAP hold plus higher lows into lunch should convert high_balance into trend_continuation.",
    "On strong overnight posture plus early RTH reclaim, allow a larger span than the default 260-390 pt medium-move band; actual span was 477.25 pts.",
    "Remove late-fade risk from the active bias when afternoon price holds high-level consolidation and makes no failed reclaim."
  ]
}
