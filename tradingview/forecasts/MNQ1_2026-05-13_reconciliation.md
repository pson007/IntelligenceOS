---
symbol: MNQ1
date: 2026-05-13
dow: Wed
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-13.png
forecasts_graded: ['pre_session', '1000']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-13.json
made_at: 2026-05-13T18:31:40
---
ACTUAL OUTCOME

MNQ opened around 29,317.25, closed 29,475.50, made HOD 29,565.25 and LOD 29,281.50. Shape: bullish reclaim/trend day with early chop/dip, noon reclaim, decisive 14:00 breakout, then late pullback into a still-bullish close.

STAGE GRADES
PRE-SESSION

Direction: ✓

Close range hit: ✓

HOD captured: ✗

LOD captured: ✗ — LOD undercut the key 29,340 invalidation zone by 58.50 pts

Tags correct: direction up, goat_direction up, buy_dips_on_reclaim, upper-half close, afternoon continuation watch

Tags wrong: open_dip_then_reclaim, early_pullback_reclaim_to_upper_balance, close_near_extreme no_mid_upper_range, controlled_continuation_or_failed_breakout_balance

Bias profitable if traded: ✓, but only if the trader did not overreact to the 29,340 break

Invalidation check: ✗. The stated first-hour acceptance below 29,340 / VWAP weakness risked invalidating a thesis that later worked. The hard invalidation was too tight for the actual morning dip.

Overall score: 4/7

F1 — 10:00 ET

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✓

Tags correct: bullish direction, high-level consolidation / buyable dip, afternoon continuation higher, upper-third close

Tags wrong: open_drive_trend_to_upper_balance, opening LONG as GOAT timing

Bias profitable if traded: ✓

Invalidation check: ✓. Sustained loss of 29,240–29,250 did not occur; LOD held well above it.

Overall score: 6/7

FORECAST EVOLUTION

Forecast quality improved sharply from pre-session to F1. The pre-session forecast had the correct bullish direction and dip-buy idea, but its invalidation level was too tight and its structure undercalled the afternoon breakout. F1 caught the real signal first: the broader LOD band, higher close band, HOD band, and 29,240–29,250 invalidation all matched the completed session much better.

LESSONS

Do not invalidate a bullish MNQ thesis on a shallow first-hour break of a nearby level unless price sustains below it; today broke below 29,340 but never lost the broader 29,240–29,250 demand zone.

When the open is rotational but lows hold above the true demand shelf, classify as rotational_morning_to_afternoon_breakout, not open-drive or simple upper balance.

At 10:00, widen HOD and close bands when price holds near early highs without losing the open; F1 correctly allowed 29,500–29,610.

Separate "GOAT direction" from "GOAT timing." Long was correct, but the real completion came around 14:15, not the opening window.

If noon reclaim holds and price forms higher balance, upgrade the afternoon branch from controlled continuation to breakout-drive potential.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 29317.25,
    "close_approx": 29475.5,
    "hod_approx": 29565.25,
    "lod_approx": 29281.5,
    "net_range_pct_open_to_close": 0.5398,
    "intraday_span_pts": 283.75
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 58.5,
      "tags_correct": [
        "direction up",
        "goat_direction up",
        "buy_dips_on_reclaim",
        "upper-half close",
        "afternoon continuation watch"
      ],
      "tags_wrong": [
        "open_dip_then_reclaim",
        "early_pullback_reclaim_to_upper_balance",
        "close_near_extreme no_mid_upper_range",
        "controlled_continuation_or_failed_breakout_balance"
      ],
      "bias_profitable": true,
      "invalidation_correct": false,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "Invalidation around 29340 was too tight; actual LOD undercut it before the bullish afternoon breakout."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "bullish direction",
        "high-level consolidation / buyable dip",
        "afternoon continuation higher",
        "upper-third close"
      ],
      "tags_wrong": [
        "open_drive_trend_to_upper_balance",
        "opening LONG as GOAT timing"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "It overcalled the open as an open-drive trend instead of a rotational morning that later became an afternoon breakout."
    }
  },
  "evolution": "Forecast quality improved from pre-session to F1. The pre-session call had the correct bullish direction and dip-buy concept, but its structure and invalidation were too tight. F1 correctly widened the downside tolerance, captured the close/HOD/LOD bands, and identified the continuation setup before the 14:00 breakout.",
  "summary": "Both forecasts leaned bullish, which matched the completed session. F1 was materially better because it respected the wider demand shelf and projected the afternoon continuation range accurately.",
  "lessons": [
    "Do not invalidate a bullish MNQ thesis on a shallow first-hour break of a nearby level unless price sustains below the broader demand shelf.",
    "When the open is rotational but lows hold above true demand, classify the day as rotational_morning_to_afternoon_breakout rather than open-drive.",
    "At 10:00, widen HOD and close bands when price holds near early highs without losing the open.",
    "Separate GOAT direction from GOAT timing; long was right, but the real completion came around 14:15.",
    "If noon reclaim holds and forms higher balance, upgrade the afternoon branch from controlled continuation to breakout-drive potential."
  ]
}
