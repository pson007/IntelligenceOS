---
symbol: MNQ1
date: 2026-04-24
dow: Fri
stage: reconciliation
screenshot: /Users/pson/Desktop/TradingView/MNQ1_profile_frame1_20260424_182512.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-24.json
made_at: 2026-04-24T18:32:40
---
ACTUAL OUTCOME

MNQ1! opened near 27,210.25, dipped to 27,130.00, reclaimed through midday, broke out in the afternoon, made HOD 27,457.50, and closed near highs at 27,440.75; structure was a failed-breakdown → midday reclaim → trend-up continuation day. 

Pasted text

STAGE GRADES
PRE-SESSION

Direction: ✓

Close range hit: ✗ — implied close band from +0.20% to +0.75% was ~27,264.67–27,414.33; close missed high by 26.42 pts

HOD captured: ✗ — upside extension exceeded expected span / "mid-upper" framing

LOD captured: ✓ — invalidation below ~27,100 did not fire; actual LOD held 27,130 demand

Tags correct: direction up, buy-dips-after-failed-breakdown, midday shakeout/reclaim, afternoon continuation, GOAT up

Tags wrong: gap_up_rotational, close_near_extreme no_mid_upper_range

Bias profitable if traded: ✓

Invalidation check: Correct. Price did not accept below ~27,100, lunch did not remain below trend support, and the failed-breakdown buy thesis stayed valid.

Overall score: 5/7

F1 — 10:00 ET

Direction: ✓

Close range hit: ✓ — 27,430–27,560 captured 27,440.75

HOD captured: ✗ — projected 27,500–27,620; actual HOD missed low by 42.50 pts

LOD captured: ✗ — projected 27,180–27,250; actual LOD 27,130 missed low by 50 pts

Tags correct: direction up, stop-hunt-reclaim, afternoon continuation grind, GOAT up, near_high close

Tags wrong: shallow lunch dip / LOD band too high

Bias profitable if traded: ✓

Invalidation check: Mostly correct. The sustained-loss trigger below 27,180–27,200 did not persist; however, the actual low undercut the forecast's lower demand band before reclaiming.

Overall score: 5/7

F2 — 12:00 ET

Direction: ✓

Close range hit: ✓ — 27,430–27,520 captured 27,440.75

HOD captured: ✗ — projected 27,470–27,560; actual HOD missed low by 12.50 pts

LOD captured: ✗ — full-day LOD 27,130 was below projected 27,190–27,250; miss 60 pts

Tags correct: direction up, stop-hunt-reclaim, higher-low consolidation, bullish continuation, GOAT up, near_high close

Tags wrong: none material after cursor; only full-day LOD band failed

Bias profitable if traded: ✓

Invalidation check: Correct. Price did not sustain below 27,190–27,210 after the reclaim structure was established.

Overall score: 5/7

F3 — 14:00 ET

Direction: ✓

Close range hit: ✓ — 27,430–27,520 captured 27,440.75

HOD captured: ✗ — projected 27,500–27,580; actual HOD missed low by 42.50 pts

LOD captured: ✓ — rest-of-day LOD stayed above 27,320–27,360 support framing

Tags correct: direction up, trend_up_reclaim, consolidation_hold, continuation_grind, GOAT up, near_high close

Tags wrong: HOD magnitude too high

Bias profitable if traded: ✓

Invalidation check: Correct. No sustained break below ~27,300 occurred; higher-low / VWAP structure held.

Overall score: 6/7

FORECAST EVOLUTION

Forecasts improved as the session progressed. The pre-session forecast had the correct long thesis and failed-breakdown framing but undercalled the close location. F1 caught the real signal first by explicitly naming the stop-hunt-reclaim structure. F2 confirmed the midday higher-low continuation, and F3 best matched the actual trade state, though it still projected too much HOD extension.

LESSONS

When the early flush holds above the named invalidation zone but undercuts the first LOD band, keep the long thesis but widen the LOD band to include the demand sweep.

After a 12:00 reclaim holds above 27,240–27,280, move the close target to near-HOD immediately; do not keep "mid-upper" close language.

For stop-hunt-reclaim trend days, forecast HOD as a modest overshoot above the close band, not a full extra 70–120 pts unless volume expansion confirms.

At 14:00, once price is above breakout base and no reversal attempt exists, prioritize close accuracy over exaggerated upside extension.

Label the structure specifically as failed_breakdown_midday_reclaim_trend_up; generic "trend-up" misses the tactical reason the long worked.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 27210.25,
    "close_approx": 27440.75,
    "hod_approx": 27457.5,
    "lod_approx": 27130.0,
    "net_range_pct_open_to_close": 0.85,
    "intraday_span_pts": 327.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 26.42,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction up",
        "buy_dips_after_failed_breakdown",
        "midday shakeout/reclaim",
        "afternoon continuation",
        "goat_direction up"
      ],
      "tags_wrong": [
        "gap_up_rotational",
        "close_near_extreme no_mid_upper_range"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Underestimated close strength and failed to call a near-HOD close."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 50,
      "tags_correct": [
        "direction up",
        "stop-hunt-reclaim",
        "afternoon continuation grind",
        "goat_direction up",
        "close_near_extreme near_high"
      ],
      "tags_wrong": [
        "rest-of-day LOD too high",
        "HOD target too high"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Correct structure and close, but LOD band failed to allow the final demand sweep to 27130."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 60,
      "tags_correct": [
        "direction up",
        "stop-hunt-reclaim",
        "higher-low consolidation",
        "bullish continuation",
        "goat_direction up",
        "close_near_extreme near_high"
      ],
      "tags_wrong": [
        "full-day LOD band too high"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 5,
      "overall_max": 7,
      "biggest_miss": "Good post-reclaim read, but still missed the actual full-session low."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": false,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "direction up",
        "trend_up_reclaim",
        "consolidation_hold",
        "continuation_grind",
        "goat_direction up",
        "close_near_extreme near_high"
      ],
      "tags_wrong": [
        "HOD target too high"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Overestimated the final upside extension despite correctly calling continuation and near-high close."
    }
  },
  "evolution": "The pre-session forecast had the correct direction and buy-dip framework but was too conservative on close strength. F1 was the first stage to identify the actual stop-hunt-reclaim signal. F2 confirmed the higher-low continuation, while F3 produced the best overall grade by aligning with the afternoon breakout and near-HOD close, though it still overprojected HOD.",
  "summary": "All forecasts correctly favored upside and a profitable long bias. The main miss was not direction but magnitude calibration: early stages undercalled the close strength, while intraday stages overcalled the HOD extension and underestimated the morning demand sweep.",
  "lessons": [
    "When the early flush holds above the named invalidation zone but undercuts the first LOD band, keep the long thesis but widen the LOD band to include the demand sweep.",
    "After a 12:00 reclaim holds above 27240–27280, move the close target to near-HOD immediately; do not keep mid-upper close language.",
    "For stop-hunt-reclaim trend days, forecast HOD as a modest overshoot above the close band, not a full extra 70–120 pts unless volume expansion confirms.",
    "At 14:00, once price is above breakout base and no reversal attempt exists, prioritize close accuracy over exaggerated upside extension.",
    "Label the structure specifically as failed_breakdown_midday_reclaim_trend_up; generic trend-up misses the tactical reason the long worked."
  ]
}
