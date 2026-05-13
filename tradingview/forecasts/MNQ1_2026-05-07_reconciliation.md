---
symbol: MNQ1
date: 2026-05-07
dow: Thu
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/.claude/worktrees/beautiful-edison-a2c148/tradingview/profiles/MNQ1_2026-05-07.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-07.json
made_at: 2026-05-08T08:38:19
---
ACTUAL OUTCOME

Open 28,750.25 / Close 28,684.50 / HOD 28,945.00 / LOD 28,553.50. Shape: morning upside drive failed into a noon breakdown, then lower-value afternoon balance with a modest late reclaim that still closed below the open. 

Pasted text

STAGE GRADES
pre_session_forecast

Direction: ✗

Close range hit: ✗ — missed below by 108.9 pts

HOD captured: ✗

LOD captured: ✗ — missed below invalidation floor by 81.5 pts

Tags correct: bullish_reclaim_open partial, morning_push partial, close_near_extreme=no

Tags wrong: direction=up, dip_reclaim_continuation, sideways_higher_low_build, controlled_upside_probe_or_balance, goat_direction=up

Bias profitable if traded: ✗

Invalidation check: Partly correct. The 28,635 downside invalidation eventually fired, but the forecast's primary early read stayed bullish after the 10:00 reclaim and did not identify the noon failed-reclaim/breakdown as the real regime shift.

Overall score: 2/7

FORECAST EVOLUTION

Only the pre-session forecast was provided, so there was no forecast evolution to grade. It caught the early bullish reclaim and morning push, but misclassified that strength as continuation instead of exhaustion. The real signal first appeared around 12:00–12:25, when the morning drive failed, 28,708 broke, and the reclaim attempt near 28,725 turned into a long trap.

LESSONS

When a bullish pre-session thesis gets the morning drive right but price stalls near HOD before noon, require a 12:00 continuation check before carrying the long bias into lunch.

Treat a break of the first defended midday demand zone — here 28,708 — as a regime-change trigger, not merely as a dip to buy.

If the forecast explicitly cites a "morning rally can fail into lunch liquidation" analog, convert that risk into a hard tactical branch with downside targets.

Do not let a valid 10:00 reclaim override later VWAP loss and failed reclaim behavior; the active bias must update after the noon structure changes.

For continuation days, HOD extension is acceptable only if lunch holds higher lows. Here lunch failed, so the forecast should have flipped from "controlled upside probe" to "lower-value balance."

JSON
{
  "actual_summary": {
    "direction": "down",
    "open_approx": 28750.25,
    "close_approx": 28684.5,
    "hod_approx": 28945.0,
    "lod_approx": 28553.5,
    "net_range_pct_open_to_close": -0.2287,
    "intraday_span_pts": 391.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 108.9,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 81.5,
      "tags_correct": [
        "bullish_reclaim_open partial",
        "morning_push partial",
        "close_near_extreme=no"
      ],
      "tags_wrong": [
        "direction=up",
        "dip_reclaim_morning_push_lunch_balance_afternoon_probe",
        "sideways_higher_low_build",
        "controlled_upside_probe_or_balance",
        "goat_direction=up"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "Forecast treated the early reclaim and morning drive as bullish continuation instead of recognizing the noon failed reclaim and breakdown into lower afternoon value."
    }
  },
  "evolution": "Only the pre-session forecast was provided. It partially captured the early bullish open and morning push, but no later stage corrected the bias after the 12:00 rollover and 12:15 breakdown. The real signal first appeared around 12:00-12:25, when the upside drive failed and the 28708-28725 zone became a long trap.",
  "summary": "The forecast got the opening/morning behavior partially right but missed the completed-day direction and the lunch regime shift. Its invalidation framework contained a useful downside floor, but the actionable failure was the midday demand break well before the final LOD.",
  "lessons": [
    "When a bullish pre-session thesis gets the morning drive right but price stalls near HOD before noon, require a 12:00 continuation check before carrying the long bias into lunch.",
    "Treat a break of the first defended midday demand zone — here 28708 — as a regime-change trigger, not merely as a dip to buy.",
    "If the forecast explicitly cites a morning-rally-fails-into-lunch-liquidation analog, convert that risk into a hard tactical branch with downside targets.",
    "Do not let a valid 10:00 reclaim override later VWAP loss and failed reclaim behavior; the active bias must update after the noon structure changes.",
    "For continuation days, HOD extension is acceptable only if lunch holds higher lows. Here lunch failed, so the forecast should have flipped from controlled upside probe to lower-value balance."
  ]
}
