---
symbol: MNQ1
date: 2026-04-23
dow: Thu
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-23.png
forecasts_graded: ['pre_session', '1000', '1200', '1400', 'invalidation_1332', 'invalidation_1525']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-23.json
made_at: 2026-05-14T19:08:50
---
ACTUAL OUTCOME

MNQ opened near 27015, rallied to a late-morning HOD near 27156, flushed hard to a 26680 LOD around 13:45, then partially reclaimed into the afternoon but closed weak at 26926.25. Shape: morning rally → midday/early-PM liquidation → afternoon partial repair that failed below the open.

STAGE GRADES
PRE-SESSION

Direction: ✗

Close range hit: ✗ — missed by 129.3 pts below projected positive close band

HOD captured: ✗ — no useful HOD band; span forecast was too small

LOD captured: ✗ — actual LOD broke the key 26881 downside line by ~201 pts

Tags correct: early dip/reclaim risk partially recognized

Tags wrong: direction up, stop-hunt-reclaim grind, higher-low lunch base, afternoon breakout, GOAT up, close near HOD

Bias profitable if traded: ✗

Invalidation check: partly. The 26881 break eventually confirmed bearish failure, but the forecast framed invalidation too much around early 10:00 behavior and missed the delayed lunch breakdown.

Overall score: 1/7

F1 — 10:00 ET

Direction: ✗

Close range hit: ✗ — missed by 158.8 pts below

HOD captured: ✓ — projected 27120–27185, actual HOD 27156

LOD captured: ✗ — missed by 310 pts below

Tags correct: early stop-hunt/reclaim, morning upside probe

Tags wrong: trend-up continuation, higher-low lunch, afternoon squeeze, GOAT up, near-high close

Bias profitable if traded: ✗ — a long continuation bias would likely stop out on the midday flush

Invalidation check: ✓ — sustained failure below 26990 correctly invalidated the long thesis once the liquidation started

Overall score: 2/7

F2 — 12:00 ET

Direction: ✗

Close range hit: ✗ — missed by 153.8 pts below

HOD captured: ✓ — projected 27150–27260, actual HOD 27156

LOD captured: ✗ — missed by 200 pts below

Tags correct: morning trend-up into spike high

Tags wrong: trend continuation, higher-low lunch, upside expansion, GOAT up, near-high close

Bias profitable if traded: ✗ — the 26930–26980 long zone failed and 26880 invalidation broke

Invalidation check: ✓ — 26880 loss correctly marked higher-low failure, though the forecast did not anticipate the speed or depth

Overall score: 2/7

F3 — 14:00 ET

Direction: ✗

Close range hit: ✗ — missed by 113.8 pts below

HOD captured: ✗ — missed by 11 pts above the forecast HOD band

LOD captured: ✗ — missed by 250 pts below

Tags correct: none material

Tags wrong: stop-hunt-reclaim, higher-low compression, late squeeze, GOAT up, near-high close

Bias profitable if traded: ✗

Invalidation check: ✗ — the stated invalidation below 26930 was effectively already true or had just been proven by the flush; the forecast failed to reset regime after the downside GOAT

Overall score: 0/7

PIVOT — 13:32 ET

Classification: ✓ — REVERSAL was correct

Level quality: ✓ — short failure below 26964/26960 worked; 26881 target hit before 27015 stop

Reclaim check: N/A

Flat discipline: N/A

Revised-invalidation check: ✓ — price did not quickly reclaim 26964 and hold above 27015 before target

Bias profitable if traded: ✓

Overall score: 7/7

PIVOT — 15:25 ET

Classification: partial — REVERSAL was directionally aligned with failed reclaim, but late-session action was more controlled stall/lower-high than fresh downside expansion

Level quality: partial — stop above 27015 was safe, but 26881 target was likely too ambitious after the 13:45 capitulation and 14:30 repair

Reclaim check: N/A

Flat discipline: N/A

Revised-invalidation check: ✓ — no hold above 27015 occurred

Bias profitable if traded: partial — selling failed reclaims could work, but pressing for new downside late had poor follow-through

Overall score: 4/7

FORECAST EVOLUTION

The forecasts did not improve from pre-session through F3; they became more anchored to the morning reclaim narrative even as the session transitioned into a bearish reversal. F1 and F2 captured the morning HOD zone but failed to anticipate the lunch breakdown. The first forecast to catch the real signal was the 13:32 pivot, which correctly identified acceptance below broken support and shifted from long-reclaim logic to sell-failure reversal.

LESSONS

When a morning reclaim produces HOD by late morning but then forms a 12:35 lower high, stop treating lunch as benign compression; downgrade continuation odds immediately.

After support near 26960–27000 breaks with fast follow-through, classify it as acceptance lower unless price reclaims the broken shelf quickly. Do not wait for close confirmation.

At 14:00, do not reuse a bullish reclaim template if price has already printed a downside GOAT and a deep LOD; reset the regime around the new low, not the morning structure.

A post-capitulation bounce to 26980 that fails below the open is repair, not trend reversal. Late-day close targets should stay below the open unless 27015 is reclaimed and held.

For late pivots after the main liquidation already hit target, reduce downside targets. Sell-failure can remain valid, but expect stall/lower-high behavior rather than a clean second breakdown.

JSON
{
  "actual_summary": {
    "direction": "down",
    "open_approx": 27015.0,
    "close_approx": 26926.25,
    "hod_approx": 27156.0,
    "lod_approx": 26680.0,
    "net_range_pct_open_to_close": -0.3285,
    "intraday_span_pts": 476
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 129.3,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 201.0,
      "tags_correct": [
        "early dip/reclaim risk partially recognized"
      ],
      "tags_wrong": [
        "direction up",
        "stop_hunt_reclaim_then_afternoon_grind",
        "sideways_base_with_higher_lows",
        "breakout_trend_into_close",
        "goat_direction up",
        "close_near_HOD"
      ],
      "bias_profitable": false,
      "invalidation_correct": false,
      "overall_score": 1,
      "overall_max": 7,
      "biggest_miss": "Bullish reclaim thesis missed the decisive lunch breakdown and close below the open."
    },
    "F1": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 158.75,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 310.0,
      "tags_correct": [
        "early stop-hunt reclaim",
        "morning upside probe"
      ],
      "tags_wrong": [
        "trend-up continuation",
        "higher-low lunch",
        "afternoon squeeze higher",
        "goat_direction up",
        "near_high close"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "Correctly saw the morning reclaim but extrapolated it into a full-day long trend."
    },
    "F2": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 153.75,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 200.0,
      "tags_correct": [
        "morning trend up into spike high"
      ],
      "tags_wrong": [
        "trend-continuation",
        "sideways-to-higher-low lunch",
        "upside expansion",
        "goat_direction up",
        "near_high close"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "Mistook the post-HOD pullback for continuation structure instead of a lower-high breakdown setup."
    },
    "F3": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 113.75,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 250.0,
      "tags_correct": [],
      "tags_wrong": [
        "stop-hunt-reclaim",
        "higher-low compression",
        "late squeeze higher",
        "goat_direction up",
        "near_high close"
      ],
      "bias_profitable": false,
      "invalidation_correct": false,
      "overall_score": 0,
      "overall_max": 7,
      "biggest_miss": "Failed to reset after the downside GOAT and treated a bearish reversal day as bullish compression."
    },
    "invalidation_1332": {
      "direction_hit": true,
      "close_in_band": null,
      "close_miss_pts": null,
      "hod_in_band": null,
      "lod_in_band": null,
      "lod_miss_pts": null,
      "tags_correct": [
        "REVERSAL",
        "sell_failure",
        "broken support became supply",
        "target before stop"
      ],
      "tags_wrong": [],
      "bias_profitable": true,
      "invalidation_correct": true,
      "classification_correct": true,
      "level_quality": "good",
      "target_hit_before_stop": true,
      "overall_score": 7,
      "overall_max": 7,
      "biggest_miss": "None material; this was the cleanest read."
    },
    "invalidation_1525": {
      "direction_hit": true,
      "close_in_band": null,
      "close_miss_pts": null,
      "hod_in_band": null,
      "lod_in_band": null,
      "lod_miss_pts": null,
      "tags_correct": [
        "failed reclaim",
        "sell_failure",
        "no 27015 reclaim"
      ],
      "tags_wrong": [
        "fresh reversal extension",
        "26881 target expectation"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "classification_correct": "partial",
      "level_quality": "mixed",
      "target_hit_before_stop": false,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "The late short read was directionally safe but pressed for too much downside after the main capitulation had already occurred."
    }
  },
  "evolution": "The directional forecasts did not improve as the day progressed; they remained anchored to the morning reclaim and repeatedly projected higher-low continuation. F1 and F2 captured the HOD area, but both failed badly on LOD and close. F3 was the weakest because it should have reset after the downside break but instead preserved the bullish template. The 13:32 pivot was the first stage to catch the true signal: broken support, downside acceptance, and a valid short target.",
  "summary": "This was a bearish reversal day: morning strength resolved into a decisive lunch/early-PM liquidation, followed by a partial afternoon repair that failed below the open. The original long framework was invalidated by the 13:32 breakdown, and only the pivot forecast correctly adapted to the actual regime.",
  "lessons": [
    "When a morning reclaim produces HOD by late morning but then forms a 12:35 lower high, downgrade continuation odds immediately instead of assuming lunch compression.",
    "After 26960-27000 support breaks with fast follow-through, classify the move as acceptance lower unless the broken shelf is reclaimed quickly.",
    "At 14:00, reset the regime around the actual downside GOAT and LOD; do not keep using the morning reclaim template.",
    "Treat a bounce to 26980 that fails below the 27015 open as repair, not reversal; keep close targets below the open unless 27015 is reclaimed and held.",
    "For late pivots after a large liquidation has already hit target, reduce downside expectations; sell-failure may work, but new extension targets need stronger confirmation."
  ]
}
