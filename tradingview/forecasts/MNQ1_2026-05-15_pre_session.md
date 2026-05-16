---
symbol: MNQ1
date: 2026-05-15
dow: Fri
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260515_070143.png
based_on_priors: ['2026-05-14', '2026-05-13', '2026-05-12', '2026-05-11', '2026-05-08']
same_dow_refs: ['2026-05-08', '2026-05-01', '2026-04-24']
model: chatgpt_thinking
made_at: 2026-05-15T07:02:21
---
REGIME READ

Current regime is bullish recent trend transitioning into gap-down rotational risk. The last five priors are all green, but 2026-05-14 was not clean continuation: early strength failed into a hard flush, demand near 29600 held, and the close was choppy/midrange. Today's premarket is trading far below that defended 29600–29650 zone and below prior-day value, so the first forecast should lean against automatic bullish continuation and expect sellers to test whether the overnight gap down can hold.

SAME-DOW REFERENCES

2026-05-08: Strong Friday gap-up drive/trend day, but today diverges because the open is set far below prior value, not above it.

2026-05-01: Friday opening drive then high-balance rotation suggests the best move may come early, then compress.

2026-04-24: Friday failed breakdown into midday reclaim is relevant only if RTH quickly reclaims 29454–29476 and holds above VWAP.

PREDICTIONS

Direction: down, confidence med

Open type: gap_down_probe_then_rotation

Structure: gap_down_acceptance_morning_probe_midday_balance

Expected move size: med

Net pct range: -0.85% to -0.20%

Intraday span range: 190–330 pts

TIME WINDOW EXPECTATIONS

10:00: Opening probe tests whether 29330–29360 can hold; failure below 29245 opens downside continuation.

12:00: If sellers keep price below 29454–29476, expect lower/mid balance rather than full reclaim.

14:00: Afternoon likely resolves from balance; rejection below 29520 favors renewed short.

16:00: Close expected below prior-day close, likely mid-lower range unless 29476 is reclaimed and defended.

PROBABLE GOAT

Direction: short

Time window: opening/morning

Rationale: Large gap down below prior defended demand gives sellers the first clean initiative setup if RTH cannot reclaim 29454–29476.

TACTICAL BIAS

Primary bias: sell_reclaims_below_prior_value

Invalidation conditions:

RTH reclaims and holds above 29476 by 10:00.

First 30-minute low holds above 29330 while price remains above VWAP.

Break and acceptance above 29520 before noon.

PREDICTION TAGS

direction: down

structure: gap_down_acceptance_morning_probe_midday_balance

open_type: gap_down_probe_then_rotation

lunch_behavior: lower_balance_below_prior_value

afternoon_drive: failed_reclaim_then_rotation_lower

goat_direction: down

close_near_extreme: no_mid_lower_range

CONFIDENCE NOTES

The main risk is another Friday-style reclaim day where the gap down becomes a failed liquidation, especially if 29454–29476 is reclaimed early. Least certain: whether the downside continues after the open or simply balances under prior value. The most likely invalidation trigger is an early reclaim above 29476, because recent priors repeatedly showed failed weakness turning into bullish recovery.

CANARY THESIS

Bias remains short only if the gap down is accepted below prior value and early reclaim attempts fail under 29476.

JSON
{
  "regime_read": "Current regime is bullish recent trend transitioning into gap-down rotational risk. The last five priors are all green, but 2026-05-14 was not clean continuation: early strength failed into a hard flush, demand near 29600 held, and the close was choppy/midrange. Today's premarket is trading far below that defended 29600–29650 zone and below prior-day value, so the first forecast should lean against automatic bullish continuation and expect sellers to test whether the overnight gap down can hold.",
  "same_dow_references": [
    "2026-05-08: Strong Friday gap-up drive/trend day, but today diverges because the open is set far below prior value, not above it.",
    "2026-05-01: Friday opening drive then high-balance rotation suggests the best move may come early, then compress.",
    "2026-04-24: Friday failed breakdown into midday reclaim is relevant only if RTH quickly reclaims 29454–29476 and holds above VWAP."
  ],
  "predictions": {
    "direction": "down",
    "direction_confidence": "med",
    "open_type": "gap_down_probe_then_rotation",
    "structure": "gap_down_acceptance_morning_probe_midday_balance",
    "expected_move_size": "med",
    "predicted_net_pct_lo": -0.85,
    "predicted_net_pct_hi": -0.2,
    "predicted_intraday_span_lo_pts": 190,
    "predicted_intraday_span_hi_pts": 330
  },
  "time_window_expectations": {
    "10am": "Opening probe tests whether 29330–29360 can hold; failure below 29245 opens downside continuation.",
    "12pm": "If sellers keep price below 29454–29476, expect lower/mid balance rather than full reclaim.",
    "2pm": "Afternoon likely resolves from balance; rejection below 29520 favors renewed short.",
    "4pm": "Close expected below prior-day close, likely mid-lower range unless 29476 is reclaimed and defended."
  },
  "probable_goat": {
    "direction": "short",
    "time_window": "opening/morning",
    "rationale": "Large gap down below prior defended demand gives sellers the first clean initiative setup if RTH cannot reclaim 29454–29476."
  },
  "tactical_bias": {
    "bias": "sell_reclaims_below_prior_value",
    "invalidation": "Invalid if RTH reclaims and holds above 29476 by 10:00, first 30-minute low holds above 29330 while price remains above VWAP, or price breaks and accepts above 29520 before noon."
  },
  "prediction_tags": {
    "direction": "down",
    "structure": "gap_down_acceptance_morning_probe_midday_balance",
    "open_type": "gap_down_probe_then_rotation",
    "lunch_behavior": "lower_balance_below_prior_value",
    "afternoon_drive": "failed_reclaim_then_rotation_lower",
    "goat_direction": "down",
    "close_near_extreme": "no_mid_lower_range"
  },
  "confidence_notes": "The main risk is another Friday-style reclaim day where the gap down becomes a failed liquidation, especially if 29454–29476 is reclaimed early. Least certain: whether the downside continues after the open or simply balances under prior value. The most likely invalidation trigger is an early reclaim above 29476, because recent priors repeatedly showed failed weakness turning into bullish recovery.",
  "canary": {
    "thesis_summary": "Bias remains short only if the gap down is accepted below prior value and early reclaim attempts fail under 29476.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "prior_value_rejection",
        "label": "Price remains below prior-value reclaim zone",
        "rationale": "Short bias depends on sellers defending the gap-down posture below the prior-day open/value area.",
        "check_type": "price_level",
        "evaluate_at": "10:00",
        "params": {
          "price_below": 29476
        },
        "weight": 2
      },
      {
        "id": "opening_acceptance",
        "label": "Opening print does not reclaim into bullish drive",
        "rationale": "A fast reclaim would convert the setup from gap-down acceptance into failed liquidation.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "trend_break_down",
          "tolerated": [
            "trend_break_down",
            "rotational_open",
            "inside_bar_open"
          ]
        },
        "weight": 2
      },
      {
        "id": "first_30_resistance",
        "label": "First 30 minutes fail below 29520",
        "rationale": "A push through 29520 would imply buyers are absorbing the gap and targeting prior supply.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "high_of_window_below": 29520
        },
        "weight": 2
      },
      {
        "id": "vwap_control",
        "label": "Price remains below session VWAP",
        "rationale": "Short continuation needs VWAP to act as resistance, not support.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "below"
        },
        "weight": 1
      },
      {
        "id": "overnight_low_pressure",
        "label": "Morning can pressure the overnight lower shelf",
        "rationale": "Without pressure toward 29245, the setup is more likely balance than directional downside.",
        "check_type": "price_level",
        "evaluate_at": "12:00",
        "params": {
          "price_below": 29330
        },
        "weight": 1
      }
    ]
  }
}
