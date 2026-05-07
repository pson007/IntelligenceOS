---
symbol: MNQ1
date: 2026-04-28
dow: Tue
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-28.png
forecasts_graded: ['pre_session', '1000', 'invalidation_1039']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-28.json
made_at: 2026-05-06T19:45:25
---
ACTUAL OUTCOME

Open 27,161.25 / Close 27,169.50 / HOD 27,250.75 / LOD 27,006.25. Shape: early failed high, morning liquidation into late-morning lows, then steady afternoon reclaim that closed slightly green but not near HOD. 

Pasted text (3)

STAGE GRADES
pre_session_forecast

Direction: ✓

Close range hit: ✗ — missed by ~39.8 pts below implied +0.20% lower band

HOD captured: ✗

LOD captured: ✗ — missed by ~123.8 pts below 27,130 demand thesis

Tags correct: direction up, rotational-to-bullish reclaim, defended demand theme, afternoon recovery

Tags wrong: open_dip_then_reclaim, stop_hunt_reclaim_then_afternoon_grind, bullish_hold_above_demand, goat_direction up, close_near_extreme yes

Bias profitable if traded: ✗

Invalidation check: ✓ — failed 27,210 reclaim / VWAP rejection correctly invalidated the original long plan

Overall score: 3/7

F1

Direction: ✓

Close range hit: ✗ — missed by ~190.5 pts below 27,360 lower band

HOD captured: ✗ — missed by ~149.3 pts below 27,400 lower band

LOD captured: ✗ — missed by ~28.8 pts below 27,035 lower band

Tags correct: direction up, failed_breakdown/value_reclaim risk, supply rejection risk

Tags wrong: stop-hunt-reclaim trend-up, lunch hold above reclaim base, upside continuation, close near upper third/HOD

Bias profitable if traded: ✗

Invalidation check: ✗ — stop/invalid zone was too tight; price undercut 27,035 before the real reversal

Overall score: 3/7

invalidation_1039

Classification: ✓ — REVERSAL short was correct after the failed reclaim/VWAP rejection

Level quality: ✓ — 27,069–27,090 failed-retest short, stop 27,130, target 27,020 was workable

Target before stop: ✓ — 27,020/27,000 area traded before the afternoon reclaim

Revised-invalidation check: ✓ — reclaim above 27,090/27,130 came later, after target opportunity

Bias profitable if traded: ✓

Overall score: 5/5

FORECAST EVOLUTION

Pre-session got the final green direction but underestimated the morning liquidation and overcalled close strength. F1 saw the failed-breakdown template but still forced an upside trend-day projection, badly overshooting close/HOD and placing the LOD band too high. The 10:39 pivot caught the first truly tradable signal: failed reclaim → VWAP rejection → short continuation into the eventual LOD.

LESSONS

When 27,210 fails before 10:00 and VWAP rejects, downgrade any "close near HOD" forecast immediately; this day closed green but ~81 pts below HOD.

At 10:00, do not anchor LOD to the first flush low. Keep room for a second sweep; actual LOD was 27,006.25, ~29 pts below F1's lower LOD band.

Separate final direction from executable bias. The day closed up, but early long plans were stopped before the valid afternoon recovery.

After a morning high fails near supply, cap HOD expectations unless price reclaims and holds above that high with expanding volume.

Label this as early_failed_high_late_reclaim, not clean stop-hunt-reclaim trend-up; the key feature was failed morning supply followed by late recovery.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 27161.25,
    "close_approx": 27169.5,
    "hod_approx": 27250.75,
    "lod_approx": 27006.25,
    "net_range_pct_open_to_close": 0.0304,
    "intraday_span_pts": 244.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 39.8,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 123.75,
      "tags_correct": [
        "direction up",
        "rotational-to-bullish reclaim",
        "defended demand theme",
        "afternoon recovery"
      ],
      "tags_wrong": [
        "open_dip_then_reclaim",
        "stop_hunt_reclaim_then_afternoon_grind",
        "bullish_hold_above_demand",
        "goat_direction up",
        "close_near_extreme yes"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "Correct final direction but invalidated early; underestimated liquidation below 27130 and overestimated close strength."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 190.5,
      "hod_in_band": false,
      "hod_miss_pts": 149.25,
      "lod_in_band": false,
      "lod_miss_pts": 28.75,
      "tags_correct": [
        "direction up",
        "failed_breakdown/value_reclaim risk",
        "supply rejection risk"
      ],
      "tags_wrong": [
        "stop-hunt-reclaim trend-up",
        "lunch hold above reclaim base",
        "upside continuation",
        "close near upper third/HOD"
      ],
      "bias_profitable": false,
      "invalidation_correct": false,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "Overprojected trend-day upside and kept the LOD band too high despite failed supply and weak reclaim."
    },
    "invalidation_1039": {
      "classification_correct": true,
      "level_quality": true,
      "target_before_stop": true,
      "reclaim_check": null,
      "flat_discipline": null,
      "revised_invalidation_correct": true,
      "bias_profitable": true,
      "overall_score": 5,
      "overall_max": 5,
      "biggest_miss": "No major miss; the short was tactical, not a full-day bearish call."
    }
  },
  "evolution": "Forecasts improved tactically only after the 10:39 invalidation. Pre-session and F1 were directionally right on the final close but wrong on path, close strength, HOD, and tradable long execution. The pivot caught the real actionable signal first: failed reclaim, VWAP rejection, and downside continuation into the late-morning LOD.",
  "summary": "The day reconciles as a green close after a bearish morning failure, not as a clean bullish trend day. The best forecast was the 10:39 pivot because it respected the broken reclaim and produced a workable short before the afternoon recovery.",
  "lessons": [
    "When 27210 fails before 10:00 and VWAP rejects, downgrade any close-near-HOD forecast immediately.",
    "At 10:00, keep the LOD band wide enough for a second sweep below the first flush low.",
    "Separate final direction from executable bias; a green close can still stop out early long plans.",
    "After a morning high fails near supply, cap HOD expectations unless price reclaims that high with expanding volume.",
    "Use early_failed_high_late_reclaim for this structure, not clean stop_hunt_reclaim trend-up."
  ]
}
