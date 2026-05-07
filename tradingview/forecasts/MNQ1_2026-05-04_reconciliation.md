---
symbol: MNQ1
date: 2026-05-04
dow: Mon
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-04.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-04.json
made_at: 2026-05-06T19:47:55
---
ACTUAL OUTCOME

Opened ~27,854, closed 27,779.75, HOD 27,941, LOD 27,614.25. Shape: morning push to highs failed into an 11:00–12:10 liquidation flush, then afternoon repair stalled below the morning breakdown zone.

STAGE GRADES
pre_session_forecast

Direction: ✗

Close range hit: ✗ — forecast implied +0.15% to +0.65%; actual was -0.27%, about 116 pts below the lower close band.

HOD captured: ✓ — expected span 210–360 pts; actual span was 326.75 pts, and the morning upside probe fit the forecast's "extended/rotational" risk.

LOD captured: ✗ — forecast expected dip support/reclaim behavior, not a 27,614 liquidation flush.

Tags correct: rotational risk, morning upside extension risk, medium span

Tags wrong: direction up, stop_hunt_reclaim_high_balance_trend_up, open_dip_then_reclaim, constructive_high_base, controlled_upside_continuation, goat_direction up, close_near_HOD

Bias profitable if traded: ✗

Invalidation check: Mostly correct as a risk framework, but levels were unusable. The long thesis should have degraded by the failed rebound/breakdown, yet the named 28,500/28,450 thresholds were far above actual RTH price and therefore not operational for this session.

Overall score: 2/7

FORECAST EVOLUTION

Only the pre-session forecast was provided, so there was no intraday improvement to evaluate. It identified the main risk conceptually — large overnight advance already spent, open-near-high fade — but still anchored the base case to long reclaim continuation. The real signal was the 10:45 HOD failure followed by the 11:00 breakdown; no provided stage caught it in real time.

LESSONS

When the forecast's price ladder is far from the live RTH open, invalidate the forecast mechanically before grading directional bias; unusable levels should not remain active trade triggers.

If MNQ makes HOD before 11:00 and then breaks the opening support shelf with expanding volume, switch from "dip/reclaim" to morning_high_failure_midday_flush.

Do not label GOAT long when the best move is a post-HOD liquidation leg; today's GOAT was down around 11:00, not morning dip-buy.

After a failed morning high, treat afternoon strength as repair unless price reclaims the morning range; today's 13:25–14:05 push stalled near 27,805–27,815 and never restored bullish control.

Add a "level sanity check" before publishing: all support/resistance and invalidation levels must be within the current session's plausible price area.

JSON
{
  "actual_summary": {
    "direction": "down",
    "open_approx": 27854.0,
    "close_approx": 27779.75,
    "hod_approx": 27941.0,
    "lod_approx": 27614.25,
    "net_range_pct_open_to_close": -0.2666,
    "intraday_span_pts": 326.75
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 116.03,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 0,
      "tags_correct": [
        "rotational risk",
        "morning upside extension risk",
        "medium span"
      ],
      "tags_wrong": [
        "direction up",
        "stop_hunt_reclaim_high_balance_trend_up",
        "open_dip_then_reclaim",
        "constructive_high_base",
        "controlled_upside_continuation",
        "goat_direction up",
        "close_near_extreme yes_closer_to_HOD"
      ],
      "bias_profitable": false,
      "invalidation_correct": false,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "Forecast stayed anchored to long reclaim continuation despite the actual day being a morning-high failure into midday liquidation; stated invalidation levels were also far from the live RTH price area."
    }
  },
  "evolution": "Only the pre-session forecast was provided, so no forecast progression can be scored. The forecast recognized the possible open-near-high fade risk, but its base case remained long continuation and it did not capture the decisive 10:45 HOD failure into the 11:00 breakdown.",
  "summary": "The forecast got the approximate volatility regime right but missed the direction, close, LOD, tactical bias, and core structure. The main failure was treating early weakness as potential dip-buy fuel instead of preparing for failed-morning-high liquidation once the upside extension rejected.",
  "lessons": [
    "When the forecast's price ladder is far from the live RTH open, invalidate the forecast mechanically before grading directional bias; unusable levels should not remain active trade triggers.",
    "If MNQ makes HOD before 11:00 and then breaks the opening support shelf with expanding volume, switch from dip/reclaim to morning_high_failure_midday_flush.",
    "Do not label GOAT long when the best move is a post-HOD liquidation leg; today's GOAT was down around 11:00, not morning dip-buy.",
    "After a failed morning high, treat afternoon strength as repair unless price reclaims the morning range; today's 13:25–14:05 push stalled near 27805–27815 and never restored bullish control.",
    "Add a level sanity check before publishing: all support/resistance and invalidation levels must be within the current session's plausible price area."
  ]
}
