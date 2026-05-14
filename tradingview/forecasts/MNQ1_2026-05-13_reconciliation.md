---
symbol: MNQ1
date: 2026-05-13
dow: Wed
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-13.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-13.json
made_at: 2026-05-14T16:10:59
---
ACTUAL OUTCOME

MNQ opened near 29317.25, dipped to 29281.50, reclaimed after late morning/noon, broke out hard around 14:00, made HOD near 29565.25, and closed bullish at 29475.50. Shape: bullish reclaim/trend day — rotational morning, noon reclaim, 14:00 breakout drive, late pullback held demand.

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✓

HOD captured: ✗

LOD captured: ✗

Tags correct: direction up, buy dips on reclaim, noon reclaim, upper-half close, goat direction up

Tags wrong: open_dip_then_reclaim level too high, morning GOAT, controlled continuation understated the 14:00 breakout

Bias profitable if traded: ✓

Invalidation check: Mostly correct. The bearish invalidation did not cleanly fire because the early break below support did not accept lower; it reclaimed. But the stated 29340/29355 support ladder was too high versus the actual low near 29281.50.

Overall score: 5/7

F1

Direction: ✗

Close range hit: ✗ — missed by 305.50 pts above forecast band

HOD captured: ✗

LOD captured: ✗

Tags correct: early demand-test risk

Tags wrong: direction down, morning_high_failure_midday_flush, weak balance, downside continuation, short GOAT, lower-third close

Bias profitable if traded: ✗

Invalidation check: ✓. The forecast said sustained reclaim above 29245, stronger above 29290–29330, would invalidate the short; price reclaimed through those levels and continued higher.

Overall score: 1/7

F2

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✗ — forecast LOD band was too low by about 61.50 pts

Tags correct: direction up, rotational morning to afternoon breakout, higher balance, breakout drive potential, long GOAT, close near extreme

Tags wrong: LOD/demand retest too bearish

Bias profitable if traded: ✓

Invalidation check: ✓. The invalidation below 29170–29190 never fired; long bias stayed valid.

Overall score: 6/7

F3

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✗ — late downside expectation was too low; post-breakout demand held higher

Tags correct: direction up, higher-low grind, noon higher balance, long GOAT, near upper-quartile close, squeeze risk

Tags wrong: controlled continuation understated the strength of the 14:00 breakout

Bias profitable if traded: ✓

Invalidation check: ✓. Price did not sustain below 29405; bullish bias remained active.

Overall score: 6/7

FORECAST EVOLUTION

Forecast quality worsened sharply at F1 because it misread early weakness as a bearish continuation setup. F2 caught the real signal first: failed morning liquidation, reclaim, higher balance, and afternoon breakout potential. F3 refined the read well, correctly staying long into the 14:00 breakout, though it still underestimated how well late demand would hold.

LESSONS

When early weakness breaks forecast support but immediately reclaims, classify it as failed liquidation / reclaim, not automatic bearish acceptance.

At 10:00, do not press short bias after a demand test unless price remains below reclaim pivots; today's reclaim through 29245–29330 invalidated F1 quickly.

After a noon reclaim with higher lows, raise the LOD expectation; do not keep looking for deep demand retests unless the reclaim shelf breaks.

Treat 14:00 strength through supply as a potential GOAT launch, not merely "controlled continuation," when supply breaks with volume and price holds above the breakout base.

For late-day forecasts after a confirmed upside breakout, anchor pullback targets to the new demand shelf, not the old pre-breakout balance low.

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
      "lod_miss_pts": 73.5,
      "tags_correct": [
        "direction up",
        "buy_dips_on_reclaim",
        "noon reclaim",
        "upper-half close",
        "goat_direction up"
      ],
      "tags_wrong": [
        "open_dip_then_reclaim level too high",
        "morning GOAT",
        "controlled continuation understated 14:00 breakout"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Correct bullish thesis, but support/invalidation levels were too high and the forecast missed the true 14:00 breakout as the main signal."
    },
    "F1": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 305.5,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 196.5,
      "tags_correct": [
        "early demand-test risk"
      ],
      "tags_wrong": [
        "direction down",
        "morning_high_failure_midday_flush",
        "weak balance",
        "downside continuation",
        "short GOAT",
        "lower-third close"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 1,
      "overall_max": 7,
      "biggest_miss": "It treated early weakness as bearish continuation instead of recognizing that reclaim above 29245-29330 would flip control back to buyers."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 61.5,
      "tags_correct": [
        "direction up",
        "rotational_morning_to_afternoon_breakout",
        "higher_balance",
        "breakout_drive_potential",
        "long GOAT",
        "close_near_extreme"
      ],
      "tags_wrong": [
        "LOD/demand retest too low"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "The directional and structural call was strong, but it expected a deeper downside retest than the market allowed after reclaim."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 25,
      "tags_correct": [
        "direction up",
        "higher-low grind",
        "held higher balance after noon reclaim",
        "long GOAT",
        "near upper-quartile close",
        "squeeze risk"
      ],
      "tags_wrong": [
        "controlled continuation understated breakout strength"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "It correctly stayed bullish but set late pullback expectations too low relative to the new demand shelf after the breakout."
    }
  },
  "evolution": "The pre-session forecast had the right bullish framework but imperfect levels and timing. F1 was the worst read, flipping bearish just before the reclaim regime became clear. F2 caught the real signal first by identifying rotational morning into afternoon breakout. F3 confirmed the bullish structure and stayed aligned with the 14:00 GOAT drive, though it slightly underestimated late demand.",
  "summary": "The day rewarded forecasts that respected failed early liquidation and noon reclaim. The decisive signal was not the open, but the higher-balance transition into the 14:00 upside breakout.",
  "lessons": [
    "When early weakness breaks forecast support but immediately reclaims, classify it as failed liquidation / reclaim, not automatic bearish acceptance.",
    "At 10:00, do not press short bias after a demand test unless price remains below reclaim pivots; today's reclaim through 29245-29330 invalidated F1 quickly.",
    "After a noon reclaim with higher lows, raise the LOD expectation; do not keep looking for deep demand retests unless the reclaim shelf breaks.",
    "Treat 14:00 strength through supply as a potential GOAT launch, not merely controlled continuation, when supply breaks with volume and price holds above the breakout base.",
    "For late-day forecasts after a confirmed upside breakout, anchor pullback targets to the new demand shelf, not the old pre-breakout balance low."
  ]
}
