---
symbol: MNQ1
date: 2026-04-22
dow: Wed
stage: reconciliation
screenshot: /Users/pson/Desktop/TradingView/MNQ1_profile_frame0_20260422_185526.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-22.json
made_at: 2026-04-22T19:01:18
---
ACTUAL OUTCOME

MNQ1 opened near 26990, flushed to 26944.5 at 09:42, then reclaimed and ground higher all afternoon to close near the high at 27086, with HOD 27105.8; the day was a bullish stop-hunt reclaim then afternoon grind. 

Pasted text

STAGE GRADES

Pre-session

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✓

Tags correct: direction up, lunch held bullishly, afternoon renewed upside grind, GOAT long/up

Tags wrong: open_type exact label, structure exact label, close_near_extreme

Bias profitable if traded: ✓

Invalidation check: Accurate. None of the stated bearish invalidations persisted; the opening low broke briefly but was reclaimed quickly, so the bullish bias stayed valid.

Overall score: 6/7

F1

Direction: ✓

Close range hit: ✗ (106 pts above band)

HOD captured: ✗ (25.8 pts above band)

LOD captured: ✗ (114.5 pts above band)

Tags correct: direction up, afternoon continuation, GOAT long/up, close near high

Tags wrong: structure too clean/too early, lunch tagged as consolidation instead of bullish hold, LOD regime far too low

Bias profitable if traded: ✓

Invalidation check: Accurate. The stated break below 26780 never happened.

Overall score: 4/7

F2

Direction: ✓

Close range hit: ✗ (66 pts above band)

HOD captured: ✓

LOD captured: ✗ (124.5 pts above band)

Tags correct: direction up, structure grind trend, lunch sideways-to-up, afternoon continuation up, GOAT long/up, close near high

Tags wrong: LOD expectation still far too low, structure missed the specific stop-hunt-reclaim character

Bias profitable if traded: ✓

Invalidation check: Accurate. The 26780 break never fired, so long bias remained valid.

Overall score: 5/7

F3

Direction: ✓

Close range hit: ✗ (106 pts above band)

HOD captured: ✗ (55.8 pts above band)

LOD captured: ✗ (94.5 pts above band)

Tags correct: direction up, lunch/grind up, afternoon continuation, GOAT up, close near high

Tags wrong: close/HOD magnitude still too conservative, LOD band still anchored too low, structure still too generic

Bias profitable if traded: ✓

Invalidation check: Accurate. No sustained loss below 26820 occurred.

Overall score: 4/7

FORECAST EVOLUTION

The forecasts improved in structural confidence as the day progressed, but not in magnitude calibration. The pre-session call actually caught the real session best in shape: early dip, reclaim, midday pause/hold, then renewed upside grind. F2 was the best intraday update because it kept the bullish continuation thesis and finally captured the HOD zone, but it still undercalled the close and never lifted the downside band enough after the stop-hunt had already printed. The real signal was identified first in the pre-session forecast, then confirmed most cleanly by F2.

LESSONS

After an early stop-hunt low is reclaimed by 10:00, immediately retire deep downside bands. Today's 09:42 LOD at 26944.5 was the day's low; keeping 26780–26820 as the projected LOD in F1/F2/F3 was stale and distorted the rest-of-day map.

When lunch is holding a round number and higher low prints into 13:30, raise the close band aggressively. Today lunch held near 27000 and the 13:24 higher low held 26988; from there, close bands still capped around 26980–27020 were too conservative.

Use close_near_extreme more aggressively on reclaim-trend days with no late reversal attempt. Once the 14:00 upside trigger fired and the profile showed defended demand plus a rising afternoon grind, the correct close assumption was "near HOD," not merely "upper half."

Separate direction accuracy from magnitude accuracy, but then force a magnitude update when the afternoon trigger confirms. All four forecasts were directionally bullish; the miss was failing to convert that correct read into a higher close/HOD band after 14:00.

Name the structure precisely when the opening pattern is a flush-and-reclaim, not generic trend-up. "Trend up" was directionally fine, but "stop-hunt reclaim then afternoon grind" would have improved both tactical entries and LOD placement.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 26990.0,
    "close_approx": 27086.0,
    "hod_approx": 27105.8,
    "lod_approx": 26944.5,
    "net_range_pct_open_to_close": 0.36,
    "intraday_span_pts": 161
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction",
        "lunch_behavior",
        "afternoon_drive",
        "goat_direction"
      ],
      "tags_wrong": [
        "open_type",
        "structure",
        "close_near_extreme"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Correct path, but it undercalled how close to the high the session would actually finish."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 106,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 114.5,
      "tags_correct": [
        "direction",
        "afternoon_drive",
        "goat_direction",
        "close_near_extreme"
      ],
      "tags_wrong": [
        "structure",
        "lunch_behavior",
        "lod_expectation"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "Price bands were anchored far too low; it stayed bullish but underpriced the reclaim trend day."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 66,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 124.5,
      "tags_correct": [
        "direction",
        "structure",
        "lunch_behavior",
        "afternoon_drive",
        "goat_direction",
        "close_near_extreme"
      ],
      "tags_wrong": [
        "lod_expectation",
        "exact_structure_label"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Best intraday update, but it still failed to lift the close band enough after the reclaim was already proven."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 106,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 94.5,
      "tags_correct": [
        "direction",
        "lunch_behavior",
        "afternoon_drive",
        "goat_direction",
        "close_near_extreme"
      ],
      "tags_wrong": [
        "close_magnitude",
        "hod_magnitude",
        "lod_expectation",
        "exact_structure_label"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "Even by 14:00, the forecast still capped the session too low despite a confirmed afternoon drive trigger."
    }
  },
  "evolution": "The forecasts got better at recognizing the bullish reclaim structure as the day developed, but they did not improve enough on price magnitude. The pre-session forecast best described the actual path first; F2 was the strongest intraday refinement, yet even it remained too conservative on the closing extension and too bearish on the residual LOD band.",
  "summary": "All stages got the main directional thesis right: this was an up day and the long bias was tradable. The reconciliation problem was not regime read but magnitude calibration—especially failing to raise close/HOD expectations after the stop-hunt reclaim and lunch hold confirmed a near-high finish.",
  "lessons": [
    "After an early stop-hunt low is reclaimed by 10:00, remove deep downside LOD projections and re-anchor the day around the actual cash-session flush.",
    "When lunch holds a major round number and a higher low prints into 13:00-13:30, widen the upside close band immediately rather than leaving it near midday prices.",
    "Use close_near_extreme aggressively on reclaim-trend days with no late reversal attempt; near-HOD should become the default once 14:00 continuation triggers.",
    "Separate direction accuracy from magnitude accuracy, then force a magnitude update when afternoon continuation is confirmed.",
    "Label the structure as stop-hunt-reclaim when that is the actual opening mechanism; generic trend-up framing hides the real tactical edge."
  ]
}
