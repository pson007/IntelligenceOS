---
symbol: MNQ1
date: 2026-05-12
stage: reconciliation
screenshot: /Users/pson/Desktop/TradingView/MNQ1_forecast_1600_close_20260512_184226.png
forecasts_graded: ['F1', 'F2']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-12.json
made_at: 2026-05-12T18:42:59
---
ACTUAL OUTCOME

Open ~29,170 / Close ~29,174 / HOD ~29,290 / LOD ~28,745 / Shape: opening spike rejection into heavy selloff, then 13:00 capitulation low produced a full afternoon V-reversal back near the open.

F1 GRADE (made at 10:00)

Direction: ✗

Close range hit: ✓ (actual 29,174 vs predicted 29,055–29,175, miss 0 pts)

HOD captured: ✗ (actual 29,290 vs predicted 29,185–29,245, miss 45 pts)

LOD captured: ✗ (actual 28,745 vs predicted 29,000–29,080, miss 255 pts)

Tags correct: failed opening drive, supply rejection, downside liquidation risk, possible failed-breakdown reclaim

Tags wrong: direction down, lower-value balance, near lower-third close, sell-side continuation

Bias profitable if traded: ✓

Overall score: 2.5/6

Biggest miss: It correctly identified the failed open and short setup, but badly under-forecast the selloff depth and missed the full afternoon V-reversal.

F2 GRADE (made at 12:00)

Direction: ✗

Close range hit: ✗ (actual 29,174 vs predicted 28,650–28,820, miss 354 pts above range)

HOD captured: ✗ (actual rest-of-day high ~29,180 vs predicted 28,920–29,020, miss ~160 pts)

LOD captured: ✗ (actual 28,745 vs predicted 28,520–28,700, miss 45 pts above lower edge / below upper edge not captured)

Tags correct: trend-down lower highs into lunch, potential lunch-capitulation trap, 13:00 demand-hold reversal branch mentioned

Tags wrong: direction down, sell continuation, weak/minor bounce, near-low close, bearish GOAT direction

Bias profitable if traded: ✓

Overall score: 2/6

Biggest miss: It named the capitulation-trap risk but failed to upgrade it once sellers could not extend after 13:00.

F3 GRADE (made at 14:00)

Direction: N/A

Close range hit: N/A

HOD captured: N/A

LOD captured: N/A

Tags correct: N/A

Tags wrong: N/A

Bias profitable if traded: N/A

Overall score: N/A/6

Biggest miss: No F3 forecast was provided, so it cannot be graded.

FORECAST EVOLUTION

F1 was directionally wrong for the full day but tactically useful: it caught the failed opening squeeze and short opportunity, yet underestimated both the downside flush and the later recovery.

F2 got worse as a full-day forecast. It overfit the noon trend-down state and treated the 13:00 reversal branch as secondary. The key missed signal was failure to extend below the lunch selloff after 13:00, followed by reclaim of lower supply near 29,000.

No F3 was supplied, so improvement after 14:00 cannot be judged.

LESSONS

After a strong morning liquidation, require a formal 13:00 demand-hold reversal branch with higher probability if price stops extending lower.

Do not keep bearish close forecasts after sellers fail to break fresh lows post-lunch.

Separate profitable morning short from accurate full-day bearish forecast.

Increase range width on failed-opening-pop days; this session's 545-point span exceeded both forecasts.

Once 28,925–29,025 reclaimed after 13:00, F2 should have flipped from sell-continuation to capitulation-to-V-reversal.

Add a late-day target branch: reclaim 29,000 → grind to open/VWAP → possible close near upper session.
