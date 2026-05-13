---
symbol: MNQ1
date: 2026-05-11
dow: Mon
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-11.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-11.json
made_at: 2026-05-12T07:16:06
---
ACTUAL OUTCOME

Opened near 29305, closed 29429, HOD 29480.5, LOD 29247. Shape: early flush, late-morning upside reversal/trend, upper balance, 15:00 breakdown attempt, then late reclaim into a green close.

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✗ (missed by 13 pts below 29260 expected pullback floor; exact LOD 29247)

Tags correct: direction up, goat_direction up, close_near_extreme no, buy_dips_on_reclaim, gap-up pullback/reclaim, upper balance risk

Tags wrong: structure too generic, open_type missed gap-up drive then reversal, lunch_behavior not just higher-low base, afternoon_drive missed failed breakdown late reclaim

Bias profitable if traded: ✓

Invalidation check: Correct. Price did not accept below 29240, did not break 29120, and the post-10:30 reclaim thesis remained valid after the 10:34 reversal.

Overall score: 5/7

FORECAST EVOLUTION

Only the pre-session forecast was provided. It caught the core signal early: bullish day, dip-buy setup, morning reclaim, non-extreme green close. Its main miss was scale/shape: it expected a larger 260–460 pt span and framed the day as gap-up pullback high balance, while the exact session was a smaller 233.5 pt span with a deeper early flush, stronger late-morning trend leg, and failed 15:00 breakdown/reclaim.

LESSONS

When MNQ gaps up and immediately spikes above 29400 but fails within minutes, label the open as gap_up_drive_then_reversal, not merely rotational reclaim.

Keep the bullish dip-buy plan active if the flush holds just above the hard invalidation level; today's 29247 LOD held above 29240, then reversed cleanly.

Use exact invalidation separately from expected pullback bands: the forecast's tactical invalidation was good, but the LOD band was too shallow by 13 pts.

After a 10:34 secondary flush base and 11:33 reclaim, upgrade structure from high_balance to early_flush_to_midday_trend_then_upper_balance.

Add a late-day branch for failed breakdown late reclaim when price balances near highs but cannot cleanly break supply.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 29305.0,
    "close_approx": 29429.0,
    "hod_approx": 29480.5,
    "lod_approx": 29247.0,
    "net_range_pct_open_to_close": 0.4231,
    "intraday_span_pts": 233.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 13,
      "tags_correct": [
        "direction up",
        "goat_direction up",
        "close_near_extreme no",
        "buy_dips_on_reclaim",
        "gap-up pullback/reclaim",
        "upper balance risk"
      ],
      "tags_wrong": [
        "structure too generic",
        "open_type missed gap_up_drive_then_reversal",
        "lunch_behavior not just higher_low_base_required",
        "afternoon_drive missed failed_breakdown_late_reclaim",
        "expected_move_size large overstated span"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "The forecast got bullish direction and dip-buy invalidation right, but understated the early flush depth and missed the exact session shape: early flush to midday trend, upper balance, then failed late breakdown/reclaim."
    }
  },
  "evolution": "Only the pre-session forecast was provided, so there is no stage-to-stage improvement to evaluate. The pre-session call caught the real signal first: bullish dip-buy continuation after a defended flush, but it did not refine the intraday structure into the actual early-flush-to-midday-trend and late failed-breakdown pattern.",
  "summary": "The pre-session forecast was directionally correct and tactically usable: buying the defended flush/reclaim would likely have worked. Its weaknesses were structural precision and range calibration, especially the too-shallow LOD expectation and oversized span forecast.",
  "lessons": [
    "When MNQ gaps up and immediately spikes above 29400 but fails within minutes, label the open as gap_up_drive_then_reversal, not merely rotational reclaim.",
    "Keep the bullish dip-buy plan active if the flush holds just above the hard invalidation level; today's 29247 LOD held above 29240, then reversed cleanly.",
    "Use exact invalidation separately from expected pullback bands: the forecast's tactical invalidation was good, but the LOD band was too shallow by 13 pts.",
    "After a 10:34 secondary flush base and 11:33 reclaim, upgrade structure from high_balance to early_flush_to_midday_trend_then_upper_balance.",
    "Add a late-day branch for failed_breakdown_late_reclaim when price balances near highs but cannot cleanly break supply."
  ]
}
