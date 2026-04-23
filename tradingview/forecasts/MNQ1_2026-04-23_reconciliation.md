---
symbol: MNQ1
date: 2026-04-23
stage: reconciliation
screenshot: /Users/pson/Desktop/TradingView/MNQ1_forecast_1600_close_20260423_093245.png
forecasts_graded: ['F1', 'F2', 'F3']
ground_truth_profile: none
made_at: 2026-04-23T09:36:12
---
ACTUAL OUTCOME

Open ~26,930 / Close ~27,110 / HOD ~27,120 / LOD ~26,885 / Shape: early stop-hunt low, full reclaim, steady trend-up, then firm close near the upper end of the RTH range. 

Pasted text

F1 GRADE (made at 10:00)

Direction: ✓

Close range hit: ✓ (~27,110 vs 27,080–27,160, miss in pts: 0)

HOD captured: ✗ (~27,120 vs 27,140–27,220, miss: ~20 pts low)

LOD captured: ✗ (~26,885 vs 26,900–26,950, miss: ~15 pts low)

Tags correct: direction up, reclaim/trend-up read, lunch hold-high, afternoon continuation, close near high

Tags wrong: none major; only the HOD magnitude was too optimistic

Bias profitable if traded: ✓

Overall score: 4/6

Biggest miss: It read the day type correctly but projected both extremes a bit too high.

F2 GRADE (made at 12:00)

Direction: ✓

Close range hit: ✓ (~27,110 vs 27,080–27,180, miss in pts: 0)

HOD captured: ✗ (~27,120 vs 27,150–27,260, miss: ~30 pts low)

LOD captured: ✓ (~26,885 vs 26,880–26,940, miss in pts: 0)

Tags correct: direction up, lunchtime higher-low / stabilization, afternoon upside expansion, near-high close tendency

Tags wrong: structure was too generic; this was more specifically stop-hunt-reclaim than plain trend continuation

Bias profitable if traded: ✓

Overall score: 5/6

Biggest miss: The upside extension band stayed too high even after midday information narrowed the likely range.

F3 GRADE (made at 14:00)

Direction: ✓

Close range hit: ✗ (~27,110 vs 27,040–27,105, miss: ~5 pts high)

HOD captured: ✓ (~27,120 vs 27,085–27,145, miss in pts: 0)

LOD captured: ✗ (~26,885 vs 26,930–26,970, miss: ~45 pts low)

Tags correct: direction up, stop-hunt-reclaim, holds value / higher-low compression, late squeeze higher, near-high close

Tags wrong: downside band was too shallow relative to the actual morning flush already on the chart

Bias profitable if traded: ✓

Overall score: 4/6

Biggest miss: It finally got the structure right, but the close band remained slightly too conservative and the LOD range was anchored too high.

FORECAST EVOLUTION

Yes. The forecasts improved in structure labeling and HOD precision as the day progressed.

F1 caught the main signal early: reclaim after the opening flush and trend-up continuation.

F2 kept the right directional bias and improved the LOD band, but still overstated upside magnitude.

F3 best captured the actual structure and late-session behavior, but it under-updated the close band once continuation was effectively confirmed.

LESSONS

Once the stop-hunt low is reclaimed by 10:00, anchor the day's true LOD there and stop projecting a fresh deep downside test unless structure actually breaks.

After lunch holds the round number and prints higher lows, shift the close band upward faster.

At 14:00, if continuation is active, push the close forecast toward near-HOD by default, not just modestly above midday value.

Separate day type from range size: the direction call was good all day, but the magnitude update lagged.

Use the actual opening mechanism explicitly: stop-hunt-reclaim was the edge, not generic bullishness.

ACCUMULATED LESSONS

After an early stop-hunt low is reclaimed by 10:00, remove deep downside LOD projections and re-anchor the day around the actual cash-session flush.

When lunch holds a major round number and a higher low prints into 13:00-13:30, widen the upside close band immediately rather than leaving it near midday prices.

Use close_near_extreme aggressively on reclaim-trend days with no late reversal attempt; near-HOD should become the default once 14:00 continuation triggers.

Separate direction accuracy from magnitude accuracy, then force a magnitude update when afternoon continuation is confirmed.

Label the structure as stop-hunt-reclaim when that is the actual opening mechanism; generic trend-up framing hides the real tactical edge.

Close extension in trend-down liquidation days routinely breaks below F1's projected close range — extend the lower bound ~1.5x when close_near_extreme=near_low is the primary prediction

When F1 calls 'liquidation extension' as the afternoon drive, bias the LOD band lower than symmetric — late-session flushes 14:30-15:55 overshoot conservative ranges by 80-120 pts on MNQ1!

Pre-session forecasts after a broken green streak should default direction confidence to 'low' rather than 'med' until the first 30min of RTH confirms — the regime-shift read is right, but the continuation-vs-reversal coin flip is still open

Separate trend-regime continuation from exhaustion-after-extension scenarios when prior week is 5+ green days straight

Weight opening-fade risk more heavily after close-near-high streaks - continuation becomes less reliable not more
