---
symbol: MNQ1
date: 2026-04-28
dow: Tue
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260428_100941.png
based_on_priors: ['2026-04-24', '2026-04-23', '2026-04-22', '2026-04-21', '2026-04-20']
same_dow_refs: ['2026-04-21', '2026-04-14', '2026-04-07']
model: chatgpt_thinking
made_at: 2026-04-28T10:10:29
---
REGIME READ

Current regime is rotational-to-bullish reclaim, not clean continuation. Overnight/early Globex sold off from the prior high area, then based and reclaimed back toward the 27,200 open/gap-rotation zone, while price is still below the 04-24 RTH close/HOD band near 27,440–27,457. Recent priors favor defended-demand reclaim days over straight breakdowns: 04-24 was a failed-breakdown midday reclaim trend-up, and 04-22 was a stop-hunt reclaim into afternoon grind; the bearish caution is 04-21 Tuesday, where an opening push failed into trend-down. Lean modestly long, but only if 27,130–27,150 holds and 27,210–27,240 is reclaimed early. 

Pasted text

SAME-DOW REFERENCES

2026-04-21: Warns that Tuesday strength can fail quickly; if the open cannot hold above 27,210 and rejects under 27,240, use the failed-opening-push template.

2026-04-14: Supports a bullish staircase only if the open accepts above the gap/open zone and pullbacks remain shallow.

2026-04-07: Supports a flush-then-reclaim template if morning weakness sweeps demand but reclaims by late morning.

PREDICTIONS

Direction: up, confidence med-low

Open type: open_dip_then_reclaim

Structure: stop_hunt_reclaim_then_afternoon_grind

Expected move size: medium

Net pct range: +0.20% to +0.75%

Intraday span range: 220–360 pts

TIME WINDOW EXPECTATIONS

10:00: Early shakeout likely; bias survives only if price is back above 27,180–27,210.

12:00: Base/reclaim zone should form above 27,130 if long thesis is valid.

14:00: If above 27,240, expect continuation toward 27,320–27,410.

16:00: Close should finish upper range, closer to HOD, unless 27,130 breaks and holds.

PROBABLE GOAT

Direction: long

Time window: morning

Rationale: Best R/R is a defended sweep of 27,130–27,150 followed by reclaim of the 27,210 open/gap-rotation level.

TACTICAL BIAS

Primary bias: buy_dips_on_27130_hold_reclaim_27210

Invalidation conditions: 09:45 close below 27,130; failed reclaim of 27,210 by 10:00; session VWAP rejection with lower high under 27,180.

PREDICTION TAGS

direction: up

structure: stop_hunt_reclaim_then_afternoon_grind

open_type: open_dip_then_reclaim

lunch_behavior: bullish_hold_above_demand

afternoon_drive: controlled_upside_continuation

goat_direction: up

close_near_extreme: yes_closer_to_HOD

CONFIDENCE NOTES

Main risk is that the overnight rebound is only a bear-flag under prior-day value, producing a 04-21-style failed opening push. Least certain variable is whether 27,210 becomes support or resistance after the open. The most likely invalidation trigger is a failed 27,210 reclaim by 10:00.

CANARY THESIS

The long thesis requires an early demand hold above 27,130 and reclaim/acceptance above 27,210 before late morning; without that, the day likely shifts to failed_opening_push_trend_down.

JSON
{
  "regime_read": "Current regime is rotational-to-bullish reclaim, not clean continuation. Overnight/early Globex sold off from the prior high area, then based and reclaimed back toward the 27200 open/gap-rotation zone, while price is still below the 04-24 RTH close/HOD band near 27440-27457. Recent priors favor defended-demand reclaim days over straight breakdowns: 04-24 was a failed-breakdown midday reclaim trend-up, and 04-22 was a stop-hunt reclaim into afternoon grind; the bearish caution is 04-21 Tuesday, where an opening push failed into trend-down. Lean modestly long, but only if 27130-27150 holds and 27210-27240 is reclaimed early.",
  "same_dow_references": [
    "2026-04-21: Warns that Tuesday strength can fail quickly; if the open cannot hold above 27210 and rejects under 27240, use the failed-opening-push template.",
    "2026-04-14: Supports a bullish staircase only if the open accepts above the gap/open zone and pullbacks remain shallow.",
    "2026-04-07: Supports a flush-then-reclaim template if morning weakness sweeps demand but reclaims by late morning."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "open_dip_then_reclaim",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.2,
    "predicted_net_pct_hi": 0.75,
    "predicted_intraday_span_lo_pts": 220,
    "predicted_intraday_span_hi_pts": 360
  },
  "time_window_expectations": {
    "10am": "Early shakeout likely; bias survives only if price is back above 27180-27210.",
    "12pm": "Base/reclaim zone should form above 27130 if long thesis is valid.",
    "2pm": "If above 27240, expect continuation toward 27320-27410.",
    "4pm": "Close should finish upper range, closer to HOD, unless 27130 breaks and holds."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "morning",
    "rationale": "Best R/R is a defended sweep of 27130-27150 followed by reclaim of the 27210 open/gap-rotation level."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_27130_hold_reclaim_27210",
    "invalidation": "Invalid if there is a 09:45 close below 27130, failed reclaim of 27210 by 10:00, or session VWAP rejection with a lower high under 27180."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "open_type": "open_dip_then_reclaim",
    "lunch_behavior": "bullish_hold_above_demand",
    "afternoon_drive": "controlled_upside_continuation",
    "goat_direction": "up",
    "close_near_extreme": "yes_closer_to_HOD"
  },
  "confidence_notes": "Main risk is that the overnight rebound is only a bear-flag under prior-day value, producing a 04-21-style failed opening push. Least certain variable is whether 27210 becomes support or resistance after the open. The most likely invalidation trigger is a failed 27210 reclaim by 10:00.",
  "canary": {
    "thesis_summary": "Long bias remains actionable only if the open defends 27130-27150 and reclaims 27210 before late morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "opening_demand_hold",
        "label": "Opening demand holds above 27130",
        "rationale": "A break below 27130 would invalidate the defended-demand reclaim setup and shift toward trend-down risk.",
        "check_type": "price_level_window",
        "evaluate_at": "09:45",
        "params": {
          "window": "09:30-09:45",
          "low_of_window_above": 27130
        },
        "weight": 2
      },
      {
        "id": "open_pattern",
        "label": "Open forms dip-then-reclaim or rotation",
        "rationale": "The forecast depends on absorption after an opening shakeout, not immediate downside continuation.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "dip_then_reclaim",
          "tolerated": [
            "dip_then_reclaim",
            "rotational_open",
            "inside_bar_open"
          ]
        },
        "weight": 1
      },
      {
        "id": "reclaim_open_zone",
        "label": "Price reclaims 27210 by 10:00",
        "rationale": "27210 is the open/gap-rotation reference; failure to reclaim keeps sellers in control.",
        "check_type": "price_level",
        "evaluate_at": "10:00",
        "params": {
          "price_above": 27210
        },
        "weight": 2
      },
      {
        "id": "vwap_acceptance",
        "label": "Price holds above VWAP by late morning",
        "rationale": "Above-VWAP acceptance confirms the reclaim is actionable instead of only a short-covering bounce.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 1
      },
      {
        "id": "midday_floor",
        "label": "Late-morning pullbacks hold above 27180",
        "rationale": "A higher low above 27180 is needed for afternoon continuation toward 27320-27410.",
        "check_type": "price_level_window",
        "evaluate_at": "12:00",
        "params": {
          "window": "10:30-12:00",
          "low_of_window_above": 27180
        },
        "weight": 1
      }
    ]
  }
}
