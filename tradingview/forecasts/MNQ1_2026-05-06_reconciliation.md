---
symbol: MNQ1
date: 2026-05-06
dow: Wed
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-06.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-06.json
made_at: 2026-05-14T19:13:38
---
ACTUAL OUTCOME

MNQ opened near 28,389, flushed early to 28,336.5, reclaimed sharply, based through midday, then stair-stepped higher into a near-HOD close at 28,710.5, with HOD 28,725.75. Shape: early flush → reclaim → trend-up close.

STAGE GRADES
PRE-SESSION

Direction: ✓

Close range hit: ✗ — missed high by ~165 pts

HOD captured: ✗

LOD captured: ✓

Tags correct: direction up, early dip/reclaim, higher-low lunch base, afternoon grind, GOAT long, close near HOD

Tags wrong: move size too small, net pct too low, "gap-up rotational" understated the trend strength

Bias profitable if traded: ✓

Invalidation check: Correct. The bullish thesis required reclaim above 28,300/VWAP and no acceptance below 28,220. Price flushed, reclaimed, and never accepted below the invalidation shelf.

Overall score: 5/7

F1 — 10:00 ET

Direction: ✓

Close range hit: ✗ — missed high by ~155.5 pts

HOD captured: ✗

LOD captured: ✓

Tags correct: failed liquidation, reclaim balance, long GOAT, sideways-to-higher consolidation, upper-half close

Tags wrong: afternoon drive too modest, close/HOD targets too compressed

Bias profitable if traded: ✓

Invalidation check: Correct. Acceptance below 28,430 did not develop; the later 10:05 higher-low/reclaim preserved the long bias.

Overall score: 5/7

F2 — 12:00 ET

Direction: ✓

Close range hit: ✗ — missed high by ~120.5 pts

HOD captured: ✗

LOD captured: ✗

Tags correct: bullish, rotational morning to afternoon breakout, higher balance, controlled upside drive, GOAT long, close near extreme

Tags wrong: projected LOD too low, afternoon extension still under-called

Bias profitable if traded: ✓

Invalidation check: Correct. Sustained trade below 28,389 never occurred after the reclaim structure matured.

Overall score: 4/7

F3 — 14:00 ET

Direction: ✓

Close range hit: ✗ — missed high by ~70.5 pts

HOD captured: ✗ — missed high by ~55.75 pts

LOD captured: ✗ — pullback band was too low relative to the post-14:00 shelf

Tags correct: trend continuation, lunch held value, afternoon upside continuation, GOAT long, close near extreme

Tags wrong: upside target too conservative, late-day demand shelf too low

Bias profitable if traded: ✓

Invalidation check: Correct. Acceptance below 28,555 never fired; long bias stayed valid.

Overall score: 4/7

FORECAST EVOLUTION

Forecasts correctly leaned bullish from the start and improved structurally through F2/F3. The real signal was caught first by the pre-session forecast, which anticipated the early dip/reclaim long framework. F1 confirmed the failed-liquidation setup, while F2 best identified the afternoon-breakout regime. The consistent weakness across all stages was underestimating upside extension, especially close and HOD.

LESSONS

When early flush reclaims above the pre-session reclaim level and VWAP, raise the close band immediately; do not keep the forecast capped near first supply.

After a 10:15 GOAT-up reclaim, treat morning supply breaks as trend-day evidence, not just "upper balance."

At noon, if price holds a higher-low base above reclaimed value, move LOD expectations up to the new shelf instead of anchoring to the morning demand zone.

At 14:00, when continuation triggers above midday range, project HOD/close from trend extension, not from prior supply bands.

Reinforce prior lesson: after confirmed upside breakout, anchor pullback targets to the new demand shelf, not old pre-breakout balance lows.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 28389.25,
    "close_approx": 28710.5,
    "hod_approx": 28725.75,
    "lod_approx": 28336.5,
    "net_range_pct_open_to_close": 1.1316,
    "intraday_span_pts": 389.25
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 165.1,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction up",
        "early dip/reclaim",
        "higher-low lunch base",
        "afternoon grind",
        "GOAT long",
        "close near HOD"
      ],
      "tags_wrong": [
        "move size too small",
        "net pct too low",
        "gap-up rotational understated trend strength"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Close and HOD targets were far too low after the reclaim became a full trend day."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 155.5,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "failed liquidation",
        "reclaim balance",
        "long GOAT",
        "sideways-to-higher consolidation",
        "upper-half close"
      ],
      "tags_wrong": [
        "afternoon drive too modest",
        "close target too compressed",
        "HOD target too compressed"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "The forecast saw the reclaim but failed to expand the upside target enough."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 120.5,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 100,
      "tags_correct": [
        "bullish",
        "rotational morning to afternoon breakout",
        "higher balance",
        "controlled upside drive",
        "GOAT long",
        "close near extreme"
      ],
      "tags_wrong": [
        "projected LOD too low",
        "afternoon extension under-called"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "The structure read was good, but both downside and upside bands remained anchored too low."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 70.5,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 25,
      "tags_correct": [
        "trend continuation",
        "lunch held value",
        "afternoon upside continuation",
        "GOAT long",
        "close near extreme"
      ],
      "tags_wrong": [
        "upside target too conservative",
        "late-day demand shelf too low"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 4,
      "overall_max": 7,
      "biggest_miss": "F3 correctly stayed long but still capped the final trend extension too early."
    }
  },
  "evolution": "Forecasts were directionally correct throughout. Pre-session caught the real signal first by framing the day as buy-the-reclaim after early weakness. F1 validated the failed-liquidation reclaim, F2 best recognized the afternoon-breakout path, and F3 correctly stayed with continuation. The main degradation was not direction but target calibration: every stage underestimated close and HOD.",
  "summary": "The forecast set was structurally strong and tactically profitable, with bullish bias maintained correctly from pre-session through 14:00. The core miss was systematic upside underestimation after the early reclaim converted into a full trend day.",
  "lessons": [
    "When early flush reclaims above the pre-session reclaim level and VWAP, raise the close band immediately; do not keep the forecast capped near first supply.",
    "After a 10:15 GOAT-up reclaim, treat morning supply breaks as trend-day evidence, not just upper balance.",
    "At noon, if price holds a higher-low base above reclaimed value, move LOD expectations up to the new shelf instead of anchoring to the morning demand zone.",
    "At 14:00, when continuation triggers above midday range, project HOD/close from trend extension, not from prior supply bands.",
    "After confirmed upside breakout, anchor pullback targets to the new demand shelf, not old pre-breakout balance lows."
  ]
}
