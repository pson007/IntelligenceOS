---
symbol: MNQ1
date: 2026-05-04
dow: Mon
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-04.png
forecasts_graded: ['pre_session', '1000', '1200']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-04.json
made_at: 2026-05-14T19:10:13
---
ACTUAL OUTCOME

MNQ opened near 27,854, pushed to a failed morning high near 27,941, flushed to 27,614.25, then repaired into a 27,779.75 close; net direction was down, with a morning-high failure, midday liquidation, and afternoon repair below the morning range.

STAGE GRADES
PRE-SESSION

Direction: ✗

Close range hit: ✗ — predicted roughly 27,896–28,035 using +0.15% to +0.65%; actual 27,779.75, miss 116.1 pts below

HOD captured: ✓ — predicted span 210–360 pts captured actual span 326.75 pts, but directional HOD thesis was wrong

LOD captured: ✗ — expected dip/reclaim above 28,450–28,500, while actual LOD was 27,614.25

Tags correct: rotational/reclaim risk noted, extended-gap exhaustion risk noted

Tags wrong: direction up, stop_hunt_reclaim_high_balance_trend_up, constructive_high_base, controlled_upside_continuation, goat_direction up, close_near_HOD

Bias profitable if traded: ✗

Invalidation check: ✓ — the forecast's own invalidation should have fired immediately because RTH opened far below the forecast ladder and never interacted with the stated 28,500+ thesis levels

Overall score: 2/7

F1 — 10:00 ET

Direction: ✗

Close range hit: ✗ — predicted 27,910–27,955; actual 27,779.75, miss 130.25 pts below

HOD captured: ✓ — predicted 27,940–27,985; actual HOD 27,941, captured

LOD captured: ✗ — predicted 27,845–27,875; actual LOD 27,614.25, miss 230.75 pts below

Tags correct: morning upside trend attempt, supply-test breakout attempt

Tags wrong: direction up, bullish reclaim/trend attempt, sideways-to-higher lunch, upside continuation, goat_direction long, high-close

Bias profitable if traded: ✗

Invalidation check: ✓ — 27,845–27,850 acceptance below rising value correctly invalidated the long bias before the major liquidation expanded

Overall score: 3/7

F2 — 12:00 ET

Direction: ✓

Close range hit: ✗ — predicted 27,590–27,680; actual 27,779.75, miss 99.75 pts above

HOD captured: ✗ — rest-of-day recovery reached about 27,815, above the projected 27,760–27,805 band by about 10 pts

LOD captured: ✗ — predicted 27,520–27,610; actual LOD 27,614.25, miss 4.25 pts above

Tags correct: failed rally → lower-high liquidation, bearish regime break, goat_direction short

Tags wrong: weak lunch consolidation, downside afternoon continuation, close near LOD

Bias profitable if traded: ✓

Invalidation check: ✓ — acceptance above 27,820 did not clearly occur; the bearish trade could target the flush before the afternoon repair

Overall score: 4/7

FORECAST EVOLUTION

Forecasts improved materially after the 11:00 breakdown. Pre-session was unusable because it carried a stale 28,500+ ladder into a session that opened around 27,854. F1 correctly identified the morning high zone but misread it as continuation rather than exhaustion. F2 caught the real signal first: failed morning rally into lower-high liquidation. Its main miss was extrapolating the flush into a weak close instead of respecting the post-liquidation demand repair.

LESSONS

Invalidate stale ladders at the open. When RTH opens hundreds of points away from the pre-session reference zone, do not grade the thesis as "still pending"; mark it broken and rebuild from live RTH structure.

At 10:00, separate HOD capture from bullish continuation. F1 nailed the 27,940 HOD area but treated the test as breakout fuel; require acceptance above supply, not just a probe into it.

After an 11:00 liquidation impulse, expect one more low, but do not automatically forecast a low close. Today flushed from 27,700s to 27,614, then repaired almost 165 pts into the close.

Use demand-hit behavior to adjust close targets. Once 27,645–27,680 demand defended and reclaimed 27,735, the close forecast should shift from near-low continuation to midrange repair.

For noon shorts, define cover targets separately from close targets. F2's short was tradable into the flush, but the close call failed because it assumed the trade target would also become the settlement zone.

JSON
{
  "actual_summary": {
    "direction": "down",
    "open_approx": 27854.0,
    "close_approx": 27779.75,
    "hod_approx": 27941.0,
    "lod_approx": 27614.25,
    "net_range_pct_open_to_close": -0.2666,
    "intraday_span_pts": 326.75
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 116.1,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 835.75,
      "tags_correct": [
        "rotational/reclaim risk noted",
        "extended-gap exhaustion risk noted"
      ],
      "tags_wrong": [
        "direction up",
        "stop_hunt_reclaim_high_balance_trend_up",
        "constructive_high_base",
        "controlled_upside_continuation",
        "goat_direction up",
        "close_near_HOD"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "The forecast carried a 28500+ bullish ladder into a session that opened near 27854, making the entire pre-session structure stale immediately."
    },
    "F1": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 130.25,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 230.75,
      "tags_correct": [
        "morning upside trend attempt",
        "supply-test breakout attempt"
      ],
      "tags_wrong": [
        "direction up",
        "bullish reclaim/trend attempt",
        "sideways-to-higher lunch",
        "upside continuation",
        "goat_direction long",
        "high-close"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "It correctly located the HOD zone near 27940 but interpreted the supply test as continuation instead of morning-high failure."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 99.75,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 4.25,
      "tags_correct": [
        "failed rally -> lower-high liquidation",
        "bearish regime break",
        "goat_direction short"
      ],
      "tags_wrong": [
        "weak lunch consolidation",
        "downside afternoon continuation",
        "close near LOD"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "It caught the bearish liquidation but over-projected downside persistence and missed the afternoon repair back toward 27800."
    }
  },
  "evolution": "The forecast sequence improved after live evidence replaced the stale pre-session ladder. Pre-session was directionally wrong and invalid at the open. F1 found the correct morning supply/HOD zone but drew the wrong continuation conclusion. F2 caught the real signal first by identifying the failed morning rally and lower-high liquidation, though it failed to adjust for demand defense and afternoon repair.",
  "summary": "This was a bearish failed-morning-high day, not a bullish reclaim/high-balance session. The best actionable read was F2's short after the 11:00 regime break, but the correct close framework was midrange repair, not near-low continuation.",
  "lessons": [
    "Invalidate stale ladders at the open when RTH opens hundreds of points away from the forecast reference zone; rebuild from live RTH structure instead of carrying the old thesis.",
    "At 10:00, require acceptance above supply before calling continuation; a probe into the projected HOD zone can be the exhaustion signal.",
    "After an 11:00 liquidation impulse, forecast one more low but do not automatically forecast a low close unless demand fails on the rebound.",
    "When post-flush demand defends and price reclaims the breakdown shelf, move close targets from lower-extreme to midrange repair.",
    "For noon shorts, separate trade targets from settlement targets; a flush target can hit even when the final close repairs sharply."
  ]
}
