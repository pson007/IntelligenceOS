---
symbol: MNQ1
date: 2026-05-11
stage: reconciliation
screenshot: /Users/pson/Desktop/TradingView/MNQ1_forecast_1600_close_20260513_214252.png
forecasts_graded: ['F1', 'F2', 'F3']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-11.json
made_at: 2026-05-13T21:43:32
---
ACTUAL OUTCOME

Open 29,373 / Close 29,429 / HOD 29,478 / LOD 29,310 / Shape: Wide two-way green session: gap-up spike failed, early flush held demand, late-morning trend reached upper balance, then 15:00 selloff recovered into the close.

F1 GRADE (made at 10:00)

Direction: ✓

Close range hit: ✗ (actual 29,429 vs predicted 29,340–29,410, miss +19 pts)

HOD captured: ✗ (actual 29,478 vs predicted 29,415–29,455, miss +23 pts)

LOD captured: ✓ (actual 29,310 vs predicted 29,260–29,315)

Tags correct: direction slightly_bullish, gap_up_drive_then_reversal, goat_direction up, close_near_extreme no, late_reclaim_attempt

Tags wrong: lunch_behavior range_compression; structure understated the later trend/upper balance

Bias profitable if traded: ✓

Overall score: 4/6

Biggest miss: It correctly kept the dip-buy thesis alive but capped upside too low after the early flush held demand.

F2 GRADE (made at 12:00)

Direction: ✓

Close range hit: ✗ (actual 29,429 vs predicted 29,510–29,570, miss -81 pts)

HOD captured: ✗ (actual 29,478 vs predicted 29,540–29,610, miss -62 pts)

LOD captured: ✓/partial (post-12:00 low was near the lower edge of 29,370–29,420; full-day LOD was already in)

Tags correct: direction up, structure early_flush_to_midday_trend_then_upper_balance, lunch higher/sideways balance, goat_direction long

Tags wrong: afternoon_drive bullish breakout attempt; close_near_extreme yes

Bias profitable if traded: ✓/partial

Overall score: 4/6

Biggest miss: It over-upgraded noon strength into a breakout-drive call when supply at 29,460–29,478 capped the session.

F3 GRADE (made at 14:00)

Direction: ✓

Close range hit: ✗ (actual 29,429 vs predicted 29,455–29,505, miss -26 pts)

HOD captured: ✗ (actual 29,478 vs predicted 29,485–29,535, miss -7 pts)

LOD captured: ✗ (post-14:00 low near 29,365–29,370 vs predicted 29,385–29,420, miss ~15–20 pts)

Tags correct: goat_direction long, lunch_behavior held_higher_balance, upper_balance context

Tags wrong: controlled_upside_continuation, close_near_extreme moderately likely, breakout_attempt too optimistic

Bias profitable if traded: ✗

Overall score: 2/6

Biggest miss: It failed to allow for a late failed-breakdown flush before reclaim.

FORECAST EVOLUTION

The forecasts improved from F1 to F2 on structure recognition, then degraded tactically in F3.

F1 caught the key idea: early failed gap-up did not invalidate bullish dip-buying. Its miss was too-tight upside bands.

F2 best identified the actual day structure: early flush → trend → upper balance. Its miss was assuming the 29,478 supply break would extend instead of cap.

F3 correctly saw upper balance but overfit bullish continuation. It missed the 15:00 selloff and failed_breakdown_late_reclaim shape.

LESSONS

Keep the bullish thesis when early demand holds, but do not automatically project a breakout through first major supply.

After HOD forms near noon and price stalls under supply, add a capped upper-balance branch.

At 14:00, include a late-day liquidation/reclaim path if price has spent hours failing above supply.

Separate "long direction correct" from "long trade location safe." F3 long bias was directionally acceptable but tactically vulnerable.

For MNQ upper-balance days, widen LOD bands after 14:00; late flushes often pierce obvious value-band demand before reclaiming.
