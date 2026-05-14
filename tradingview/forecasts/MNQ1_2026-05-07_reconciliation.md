---
symbol: MNQ1
date: 2026-05-07
dow: Thu
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-07.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-07.json
made_at: 2026-05-14T19:24:47
---
ACTUAL OUTCOME

Opened ~28,750.25, closed ~28,684.50, exact HOD ~28,945, exact LOD ~28,553.50. Shape: morning upside drive failed into a midday breakdown, then afternoon lower-value balance with a modest late reclaim that still closed below the open.

STAGE GRADES
PRE-SESSION

Direction: ✗

Close range hit: ✗ — missed by ~108.9 pts below predicted band

HOD captured: ✗

LOD captured: ✗

Tags correct: close_near_extreme no/mid-upper range, afternoon balance/probe partial

Tags wrong: direction up, dip_reclaim continuation, lunch higher-low build, GOAT up

Bias profitable if traded: ✗

Invalidation check: mostly ✓ — bullish thesis correctly required >28,635 and VWAP control; later acceptance below 28,635 invalidated it, though the early reclaim delayed the failure.

Overall score: 1/7

F1

Direction: ✗

Close range hit: ✗ — missed by ~105.5 pts below predicted band

HOD captured: ✗

LOD captured: ✗ — missed by ~166.5 pts below predicted band

Tags correct: early bullish attempt / rotational risk partial

Tags wrong: direction up, afternoon upside continuation, higher balance, GOAT long, upper-third close

Bias profitable if traded: ✓ — pullback longs near 28,735–28,748 could have paid before the later breakdown.

Invalidation check: ✓ — sustained trade below 28,720 eventually fired and correctly killed the long thesis.

Overall score: 2/7

F2

Direction: ✗

Close range hit: ✗ — missed by ~175.5 pts below predicted band

HOD captured: ✓

LOD captured: ✗ — missed by ~166.5 pts below predicted band

Tags correct: morning squeeze into upper supply, shallow pullback risk partial

Tags wrong: direction up, controlled upside continuation, high-balance lunch, GOAT long, moderate-high close

Bias profitable if traded: ✓ — controlled pullback/reclaim longs could hit 28,925+ before failure, but the forecast missed the reversal.

Invalidation check: ✓ — sustained break below 28,720 did fire and correctly invalidated the upside thesis.

Overall score: 3/7

F3

Direction: ✓

Close range hit: ✗ — missed by ~24.5 pts above predicted band

HOD captured: ✓

LOD captured: ✓

Tags correct: direction down, midday downtrend, lower-high retest, weak bounce under value, GOAT short, not near extreme

Tags wrong: afternoon sell-continuation-to-lower-low attempt

Bias profitable if traded: ✓ — short-fade bias from the lower-high/value-rejection area was workable, though the close target was too low.

Invalidation check: ✓ — no sustained reclaim above 28,775 occurred, so the short thesis was not invalidated.

Overall score: 6/7

FORECAST EVOLUTION

Forecasts improved sharply only at F3. Pre-session, F1, and F2 all over-weighted the bullish reclaim and failed to downgrade after the morning drive became exhaustion risk. F2 captured the HOD band but still treated it as continuation. F3 was the first stage to catch the real signal: morning strength had failed, noon breakdown controlled the session, and afternoon should be read as lower-value balance/fade rather than upside continuation.

LESSONS

After a strong morning drive into 28,900+ supply, require a clean hold above the breakdown shelf before keeping any long bias; failure back through ~28,830–28,800 should flip the read to exhaustion risk.

Do not let a profitable early long setup become a full-day bullish forecast. Mark the long as paid once HOD supply is tested, then reassess VWAP/value acceptance.

At noon, treat loss of ~28,708 midday demand as a regime break, not a normal pullback. That level separated upper balance from bearish reversal.

For 14:00 forecasts after a liquidation low, keep downside close targets closer to lower-value balance unless price makes a fresh lower low. Today's 28,575–28,660 close band was directionally right but too bearish.

Reinforce prior lesson: a GOAT long can exist intraday without producing a high-close trend day. Here the morning long paid, but the true session GOAT became the 12:00 downside rollover.

JSON
{
  "actual_summary": {
    "direction": "down",
    "open_approx": 28750.25,
    "close_approx": 28684.5,
    "hod_approx": 28945.0,
    "lod_approx": 28553.5,
    "net_range_pct_open_to_close": -0.2287,
    "intraday_span_pts": 391.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 108.9,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 81.5,
      "tags_correct": ["close_near_extreme_no", "afternoon_balance_partial"],
      "tags_wrong": ["direction_up", "dip_reclaim_morning_push", "sideways_higher_low_lunch", "goat_up"],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 1,
      "overall_max": 7,
      "biggest_miss": "Bullish continuation thesis missed the noon breakdown and bearish reversal day."
    },
    "F1": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 105.5,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 166.5,
      "tags_correct": ["early_bullish_attempt_partial", "failed_breakout_risk_partial"],
      "tags_wrong": ["direction_up", "higher_balance", "afternoon_upside_continuation", "goat_long", "upper_third_close"],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "Correctly saw early long potential but failed to anticipate the later liquidation below 28720."
    },
    "F2": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 175.5,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 166.5,
      "tags_correct": ["morning_squeeze_into_supply", "hod_zone"],
      "tags_wrong": ["direction_up", "high_balance_lunch", "controlled_upside_continuation", "goat_long", "moderate_high_close"],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "Captured the upside extension zone but misclassified it as continuation instead of exhaustion before the noon breakdown."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 24.5,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": ["direction_down", "midday_downtrend_lower_high_retest", "weak_bounce_under_value", "goat_short", "close_not_near_extreme"],
      "tags_wrong": ["afternoon_sell_continuation_to_lower_low_attempt"],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Downside continuation target was too aggressive after the 13:30 liquidation low had already been defended."
    }
  },
  "evolution": "Forecast quality improved materially at F3. The pre-session, F1, and F2 reads stayed too attached to bullish reclaim/continuation despite mounting exhaustion risk. F2 captured the HOD band but failed to identify it as a likely reversal zone. F3 was the first forecast to align with the actual bearish reversal and lower-value afternoon balance.",
  "summary": "The day was a bearish reversal after a strong morning upside drive: early longs could pay, but the full-session direction was down. The main forecasting error was carrying bullish continuation too long after supply rejection and midday demand failure.",
  "lessons": [
    "After a strong morning drive into 28900+ supply, require a clean hold above the breakdown shelf before keeping any long bias; failure back through roughly 28830-28800 should flip the read to exhaustion risk.",
    "Do not let a profitable early long setup become a full-day bullish forecast; mark the long as paid once HOD supply is tested, then reassess VWAP and value acceptance.",
    "At noon, treat loss of roughly 28708 midday demand as a regime break, not a normal pullback.",
    "For 14:00 forecasts after a liquidation low, keep downside close targets closer to lower-value balance unless price makes a fresh lower low.",
    "Reinforce: a GOAT long can exist intraday without producing a high-close trend day; today the morning long paid, but the true session GOAT became the 12:00 downside rollover."
  ]
}
