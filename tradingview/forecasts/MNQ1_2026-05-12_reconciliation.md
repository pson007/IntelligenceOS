---
symbol: MNQ1
date: 2026-05-12
stage: reconciliation
screenshot: /Users/pson/Desktop/TradingView/MNQ1_forecast_1600_close_20260513_214640.png
forecasts_graded: ['F1', 'F2', 'F3']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-12.json
made_at: 2026-05-13T21:47:17
---
ACTUAL OUTCOME

Open 29,170 / Close 29,174 / HOD 29,290 / LOD 28,745 / Shape: opening spike failed into a deep selloff, then a 13:00 LOD launched a full afternoon V-reversal back near the open and upper session.

F1 GRADE (made at 10:00)

Direction: ✓

Close range hit: ✗ (29,174 vs 29,250–29,330, miss 76 pts below)

HOD captured: ✗ (29,290 vs 29,300–29,370, miss 10 pts below)

LOD captured: ✗ (28,745 vs 29,165–29,205, miss 420 pts below)

Tags correct: direction: up, partial goat_direction: long, partial close_near_extreme: moderately_near_high

Tags wrong: rotational_morning_to_afternoon_breakout, higher_balance_or_shallow_pullback, upside_extension_if_above_value

Bias profitable if traded: ✗

Overall score: 2/6

Biggest miss: F1 saw bullish continuation but completely missed the morning high failure and 545-point intraday liquidation.

F2 GRADE (made at 12:00)

Direction: ✗

Close range hit: ✗ (29,174 vs 28,700–28,820, miss 354 pts above)

HOD captured: ✗ (29,290 full-day HOD; post-noon high also exceeded 28,900–28,960 by roughly 214+ pts)

LOD captured: ✗ (28,745 vs 28,620–28,740, miss 5 pts above)

Tags correct: morning_high_failure_midday_flush, partial weak balance / shallow bounce, partial goat_direction: down only for the morning selloff

Tags wrong: direction: down, bearish continuation, near low

Bias profitable if traded: ✗

Overall score: 2/6

Biggest miss: F2 correctly identified the morning breakdown, but failed to anticipate the 13:00 demand hold and full V-reversal.

F3 GRADE (made at 14:00)

Direction: ✗

Close range hit: ✗ (29,174 vs 28,780–28,880, miss 294 pts above)

HOD captured: ✗ (29,290 full-day HOD; post-14:00 high also exceeded 28,930–28,975 by roughly 200+ pts)

LOD captured: ✓ (28,745 vs 28,700–28,760)

Tags correct: midday_low_then_corrective_bounce, partial afternoon_repair

Tags wrong: direction: down, afternoon_repair_then_rejection, controlled_selloff_or_range_lower, goat_direction: down, moderate downside close

Bias profitable if traded: ✗

Overall score: 1.5/6

Biggest miss: F3 treated the 13:00 reversal as corrective repair into resistance instead of a valid demand-pivot breakout.

FORECAST EVOLUTION

The forecasts did not improve cleanly.

F1 had the correct final direction but the wrong path. It expected shallow bullish continuation, not a failed opening spike into a deep liquidation leg.

F2 adapted well to the morning selloff and caught the correct downside structure up to noon, but overstayed the bearish read. The key miss was not upgrading once price held demand near 13:00.

F3 had the most information but performed worst tactically. By 14:00, the LOD was likely already in and price was repairing with strength. The forecast kept a short bias instead of recognizing V-reversal risk.

LESSONS

After a deep morning flush, treat a clean 13:00 demand hold as a major regime-change candidate, not merely a bounce.

If price reclaims lower supply and holds above the reversal ribbon/value, downgrade shorts quickly.

Separate "morning structure" from "afternoon control." A correct bearish morning read can become invalid after a strong LOD pivot.

At 14:00, require confirmation before projecting renewed downside: failed reclaim, lower high, or loss of reversal base.

Add a V-reversal branch whenever:

HOD forms early,

liquidation exceeds 300–400 pts,

LOD forms near 13:00,

reclaim accelerates through prior lower-high zones.

Do not score bearish continuation as base case once afternoon price accepts above reclaimed supply.
