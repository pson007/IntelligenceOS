---
symbol: MNQ1
date: 2026-04-29
dow: Wed
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260429_093751.png
based_on_priors: ['2026-04-24', '2026-04-23', '2026-04-22', '2026-04-21', '2026-04-20']
same_dow_refs: ['2026-04-22', '2026-04-15', '2026-04-08']
model: chatgpt_thinking
made_at: 2026-04-29T09:38:37
---
REGIME READ

Current regime is rotational-to-reclaim, not clean trend continuation. Recent priors alternate bearish liquidation days with bullish reclaim days, but the strongest usable pattern is defended demand followed by afternoon continuation: 2026-04-24 failed breakdown into trend-up and 2026-04-22 stop-hunt reclaim both closed near HOD. Today should lean cautiously with the reclaim pattern only if 27130–27160 holds and 27240–27280 is reclaimed; otherwise the overnight lower-high structure argues for a failed-open fade. 

Pasted text

SAME-DOW REFERENCES

2026-04-22: Supports an early stop-hunt under the open, fast reclaim, then afternoon grind higher if demand holds.

2026-04-15: Supports open dip-then-reclaim with midday shakeout but strong close if buyers keep absorbing supply.

2026-04-08: Bear case reference: if the open fails near supply, expect opening flush, reflex bounce, then lower-high chop/fade.

PREDICTIONS

Direction: up, confidence low-to-med

Open type: open_dip_then_reclaim

Structure: stop_hunt_reclaim_then_afternoon_grind

Expected move size: med

Net pct range: +0.20% to +0.65%

Intraday span range: 210–340 pts

TIME WINDOW EXPECTATIONS

10:00: Early flush or chop should hold above 27120–27130 and attempt reclaim back over 27200.

12:00: If 27240–27280 is reclaimed, long thesis becomes active; failure there keeps the day rotational.

14:00: Higher low above 27200 should set up afternoon continuation.

16:00: Close likely upper range, closer to HOD if no late rejection under 27240.

PROBABLE GOAT

Direction: long

Time window: morning

Rationale: Best edge is buying a failed opening flush that holds the 27120–27160 demand shelf and reclaims VWAP/27240.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions: sustained 1-min closes below 27120 after 09:45; failed reclaim of 27240 by 12:00; lower high under VWAP followed by break of opening low.

PREDICTION TAGS

direction: up

structure: stop_hunt_reclaim_then_afternoon_grind

open_type: open_dip_then_reclaim

lunch_behavior: bullish_reclaim_or_balance_above_27200

afternoon_drive: controlled_upside_grind

goat_direction: up

close_near_extreme: yes_closer_to_HOD

CONFIDENCE NOTES

The weak point is the pre-open rejection under 27260–27280; if that remains supply, the day can become lower-high chop instead of reclaim. The most likely invalidation trigger is failure to reclaim 27240 by noon. Direction is less certain than structure: the cleaner setup is conditional long only after the opening flush fails.

CANARY THESIS

The long bias remains actionable only if the open flush holds 27120–27160, price reclaims VWAP/27240 by late morning, and no lower-high breakdown forms under supply.

JSON
{
  "regime_read": "Current regime is rotational-to-reclaim, not clean trend continuation. Recent priors alternate bearish liquidation days with bullish reclaim days, but the strongest usable pattern is defended demand followed by afternoon continuation: 2026-04-24 failed breakdown into trend-up and 2026-04-22 stop-hunt reclaim both closed near HOD. Today should lean cautiously with the reclaim pattern only if 27130-27160 holds and 27240-27280 is reclaimed; otherwise the overnight lower-high structure argues for a failed-open fade.",
  "same_dow_references": [
    "2026-04-22: Supports an early stop-hunt under the open, fast reclaim, then afternoon grind higher if demand holds.",
    "2026-04-15: Supports open dip-then-reclaim with midday shakeout but strong close if buyers keep absorbing supply.",
    "2026-04-08: Bear case reference: if the open fails near supply, expect opening flush, reflex bounce, then lower-high chop/fade."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "low",
    "open_type": "open_dip_then_reclaim",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.2,
    "predicted_net_pct_hi": 0.65,
    "predicted_intraday_span_lo_pts": 210,
    "predicted_intraday_span_hi_pts": 340
  },
  "time_window_expectations": {
    "10am": "Early flush or chop should hold above 27120-27130 and attempt reclaim back over 27200.",
    "12pm": "If 27240-27280 is reclaimed, long thesis becomes active; failure there keeps the day rotational.",
    "2pm": "Higher low above 27200 should set up afternoon continuation.",
    "4pm": "Close likely upper range, closer to HOD if no late rejection under 27240."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "morning",
    "rationale": "Best edge is buying a failed opening flush that holds the 27120-27160 demand shelf and reclaims VWAP/27240."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if price sustains 1-min closes below 27120 after 09:45, fails to reclaim 27240 by 12:00, or forms a lower high under VWAP followed by a break of the opening low."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "open_type": "open_dip_then_reclaim",
    "lunch_behavior": "bullish_reclaim_or_balance_above_27200",
    "afternoon_drive": "controlled_upside_grind",
    "goat_direction": "up",
    "close_near_extreme": "yes_closer_to_HOD"
  },
  "confidence_notes": "The weak point is the pre-open rejection under 27260-27280; if that remains supply, the day can become lower-high chop instead of reclaim. The most likely invalidation trigger is failure to reclaim 27240 by noon. Direction is less certain than structure: the cleaner setup is conditional long only after the opening flush fails.",
  "canary": {
    "thesis_summary": "The long bias remains actionable only if the open flush holds 27120-27160, price reclaims VWAP/27240 by late morning, and no lower-high breakdown forms under supply.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "opening_demand_hold",
        "label": "Opening flush respects demand",
        "rationale": "The long thesis depends on the open being a stop-hunt, not true liquidation.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 27120
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open prints dip then reclaim",
        "rationale": "A reclaim pattern confirms that sellers failed to extend below overnight demand.",
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
        "id": "vwap_reclaim",
        "label": "Price back above session VWAP",
        "rationale": "Without VWAP reclaim, the open remains a failed bounce under supply.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 2
      },
      {
        "id": "midmorning_27240_reclaim",
        "label": "Reclaim above 27240",
        "rationale": "27240 is the practical pivot between lower-high rotation and upside continuation.",
        "check_type": "price_level",
        "evaluate_at": "11:30",
        "params": {
          "price_above": 27240
        },
        "weight": 2
      },
      {
        "id": "no_supply_rejection",
        "label": "No hard rejection under 27280",
        "rationale": "A capped bounce under 27280 would match the bearish lower-high reference instead of the reclaim priors.",
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
