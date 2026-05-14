---
symbol: MNQ1
date: 2026-05-12
dow: Tue
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-12.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-12.json
made_at: 2026-05-14T19:21:05
---
ACTUAL OUTCOME

MNQ opened near 29,213, closed near 29,174, made HOD near 29,296 and LOD near 28,741. Shape: opening pop failed into a deep morning liquidation, then a 13:00 demand hold produced a persistent afternoon V-reversal back near the open / upper session.

STAGE GRADES
PRE-SESSION

Direction: ✗

Close range hit: ✗ — miss by ~5 pts above the bearish close band using exact OHLC

HOD captured: ✓ — early spike into 29,240–29,310 reclaim/supply risk zone was identified

LOD captured: ✗ — actual LOD was far below the expected downside extension / span

Tags correct: lower-value acceptance, morning seller control, opening/morning short opportunity, late rebound risk

Tags wrong: final direction down, gap_down_drive open type, partial rebound instead of full V-reversal, goat_direction down

Bias profitable if traded: ✓ — sell-reclaims / morning short bias worked before 13:00

Invalidation check: mostly correct. The 29,240–29,310 reclaim did not hold early, and VWAP did not flip to support before lunch, so bearish morning thesis remained valid. It failed later because no pivot rule handled the 13:00 demand reversal.

Overall score: 4/7

F1 — 10:00

Direction: ✓

Close range hit: ✗ — close missed below 29,250–29,330 by ~76 pts

HOD captured: ✗ — actual HOD missed below 29,300–29,370 by ~4 pts, but the forecast expected more upside after 10:00 that never developed

LOD captured: ✗ — actual LOD was ~424 pts below the 29,165–29,205 band

Tags correct: early upside pressure into supply, supply-test risk

Tags wrong: rotational_morning_to_afternoon_breakout, shallow pullback, upside extension, goat_direction long, moderately near high

Bias profitable if traded: ✗ — preferred long zone would have broken 29,185 invalidation and stopped before the selloff

Invalidation check: correct. Sustained break below 29,185–29,190 fired and invalidated the long thesis.

Overall score: 2/7

F2 — 12:00

Direction: ✗

Close range hit: ✗ — close missed above 28,700–28,820 by ~354 pts

HOD captured: ✗ — afternoon recovery exceeded the 28,900–28,960 HOD band by over 200 pts

LOD captured: ✗ — exact LOD 28,741.25 missed just above the 28,620–28,740 band by ~1 pt

Tags correct: morning_high_failure_midday_flush, weak bounce into noon, downside pressure into 13:00, goat_direction down before the actual pivot

Tags wrong: bearish continuation, near-low close, trend-day extension

Bias profitable if traded: ✓ — shorting 28,890–28,930 could reach the 28,760 target before the later reclaim

Invalidation check: correct. Reclaim above 28,960 fired during the afternoon and invalidated the bearish continuation thesis.

Overall score: 3/7

F3 — 14:00

Direction: ✗

Close range hit: ✗ — close missed above 28,780–28,880 by ~294 pts

HOD captured: ✗ — post-14:00 recovery exceeded the 28,930–28,975 upside cap decisively

LOD captured: ✗ — no retest of 28,700–28,760; price held much higher

Tags correct: morning-high failure, midday low then corrective bounce

Tags wrong: afternoon_repair_then_rejection, controlled_selloff_or_range_lower, goat_direction down, moderate downside close

Bias profitable if traded: ✗ — short bias failed once price accepted above 28,975

Invalidation check: correct. Acceptance above 28,975 fired and should have forced standing down / reversal consideration.

Overall score: 2/7

FORECAST EVOLUTION

Forecasts did not improve cleanly. Pre-session caught the morning short opportunity best, but missed the 13:00 V-reversal. F1 flipped bullish too early and underestimated downside risk. F2 correctly read the morning liquidation and gave a profitable short setup, but failed to upgrade the 13:00 low into a reversal risk. F3 was the weakest late-stage read because it treated the 13:00 reclaim as corrective resistance repair instead of the start of the real afternoon signal. The real signal was first visible after the 13:00 LOD hold and higher-low reclaim into 14:00, but no forecast fully caught it.

LESSONS

After a deep morning liquidation reaches a new LOD near 13:00, require a fresh reversal test before extending bearish trend-day targets; do not carry the noon short thesis unchanged into 14:00.

At 14:00, if price is above the 13:00 low, building higher lows, and reclaiming broken lower supply, classify the setup as possible V-reversal continuation, not default repair-into-resistance.

For noon shorts, take first downside targets into capitulation lows; after target hit, shift from "continuation" to "reclaim watch" if price recovers the failed-bounce shelf.

When F1 longs fail by breaking the invalidation level, do not simply invert to trend-down for the rest of day; watch for a later failed-liquidation reclaim, especially after a 400+ pt flush.

Reuse the prior lesson on failed weakness: early bearish acceptance can be tradable, but once demand holds and supply is reclaimed, old short levels must be retired immediately.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 29212.75,
    "close_approx": 29174.25,
    "hod_approx": 29295.75,
    "lod_approx": 28741.25,
    "net_range_pct_open_to_close": -0.1318,
    "intraday_span_pts": 554.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 5.3,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 379,
      "tags_correct": [
        "lower-value acceptance",
        "morning seller control",
        "opening/morning short opportunity",
        "late rebound risk"
      ],
      "tags_wrong": [
        "direction down",
        "gap_down_drive open type",
        "partial rebound instead of full V-reversal",
        "goat_direction down"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "It correctly captured the morning short but had no effective rule for the 13:00 demand hold turning into a full V-reversal."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 75.75,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 423.75,
      "tags_correct": [
        "early upside pressure into supply",
        "supply-test risk"
      ],
      "tags_wrong": [
        "rotational_morning_to_afternoon_breakout",
        "higher_balance_or_shallow_pullback",
        "upside_extension_if_above_value",
        "goat_direction long",
        "moderately_near_high"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "It treated the opening pop as bullish continuation instead of an opening spike rejection before liquidation."
    },
    "F2": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 354.25,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 1.25,
      "tags_correct": [
        "morning_high_failure_midday_flush",
        "weak bounce into noon",
        "downside pressure into 13:00",
        "goat_direction down before the pivot"
      ],
      "tags_wrong": [
        "bearish continuation",
        "near-low close",
        "late-day trend extension"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "It correctly targeted the capitulation low but failed to flip after the 13:00 LOD hold and reclaim."
    },
    "F3": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 294.25,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 140,
      "tags_correct": [
        "morning-high failure",
        "midday_low_then_corrective_bounce"
      ],
      "tags_wrong": [
        "afternoon_repair_then_rejection",
        "controlled_selloff_or_range_lower",
        "goat_direction down",
        "moderate downside close"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "It misread the 13:00-to-14:00 recovery as resistance repair instead of the start of persistent V-reversal control."
    }
  },
  "evolution": "Pre-session was best for the morning selloff but missed the final recovery. F1 flipped bullish too early and was stopped by the liquidation. F2 recovered the bearish read and offered a workable short into the LOD, but did not recognize the post-13:00 reversal. F3 should have improved most with more information, but instead stayed anchored to the old bearish thesis after the actual reversal had begun.",
  "summary": "The day rewarded early shorts and late longs, but punished any static forecast that stayed bearish after the 13:00 demand hold. The core reconciliation is that the bearish morning structure was real, but it ended cleanly once the LOD held and lower supply was reclaimed.",
  "lessons": [
    "After a deep morning liquidation reaches a new LOD near 13:00, require a fresh reversal test before extending bearish trend-day targets; do not carry the noon short thesis unchanged into 14:00.",
    "At 14:00, if price is above the 13:00 low, building higher lows, and reclaiming broken lower supply, classify the setup as possible V-reversal continuation, not default repair-into-resistance.",
    "For noon shorts, take first downside targets into capitulation lows; after target hit, shift from continuation to reclaim watch if price recovers the failed-bounce shelf.",
    "When F1 longs fail by breaking the invalidation level, do not simply invert to trend-down for the rest of day; watch for a later failed-liquidation reclaim, especially after a 400+ pt flush.",
    "Early bearish acceptance can be tradable, but once demand holds and supply is reclaimed, old short levels must be retired immediately."
  ]
}
