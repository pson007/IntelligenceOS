---
symbol: MNQ1
date: 2026-05-12
dow: Tue
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260512_071634.png
based_on_priors: ['2026-05-11', '2026-05-08', '2026-05-07', '2026-05-06', '2026-05-05']
same_dow_refs: ['2026-05-05', '2026-04-28', '2026-04-21']
model: chatgpt_thinking
made_at: 2026-05-12T07:17:21
---
REGIME READ

Recent RTH regime is bullish but extended, with four of the last five completed sessions closing green and two strong trend-up structures on 2026-05-08 and 2026-05-06. Today's Globex action rejects that pattern: MNQ is trading far below 2026-05-11 value and below prior RTH LOD near 29310 after an overnight trend-down sequence. Forecast should lean with the overnight break, against the recent bullish continuation, unless RTH immediately reclaims 29240–29310.

SAME-DOW REFERENCES

2026-05-05: Bullish Tuesday gap-up drive, but today diverges because overnight posture is gap-down below prior value, not upside initiative.

2026-04-28: Useful for an early failed move followed by afternoon reclaim; relevant if sellers fail to extend below 29120–29140.

2026-04-21: Best downside comparable: early strength failed, then session sold rallies beneath supply into a trend-down structure.

PREDICTIONS

Direction: down, confidence med

Open type: gap_down_drive

Structure: gap_down_drive_lower_value_balance_late_partial_rebound

Expected move size: med

Net pct range: -0.65% to -0.15%

Intraday span range: 260–430 pts

TIME WINDOW EXPECTATIONS

10:00: Sellers should press or hold price below the open; reclaim above 29240 would weaken the short thesis.

12:00: Lower-value balance likely forms under prior-day low / broken demand.

14:00: Watch for continuation lower if VWAP rejects; otherwise a controlled short-covering bounce.

16:00: Close expected below the RTH open, likely mid-lower range unless late reclaim clears 29310.

PROBABLE GOAT

Direction: short

Time window: opening/morning

Rationale: Overnight trend has already broken prior-day value, so the cleanest trade is likely the first RTH sell-the-reclaim or opening continuation.

TACTICAL BIAS

Primary bias: sell_reclaims_below_prior_low

Invalidation conditions:

RTH reclaims and holds above 29240 by 10:00.

Price accepts back above prior RTH LOD near 29310 by 10:30.

Session VWAP flips from resistance to support before lunch.

PREDICTION TAGS

direction: down

structure: gap_down_drive_lower_value_balance_late_partial_rebound

open_type: gap_down_drive

lunch_behavior: lower_value_balance_under_broken_prior_low

afternoon_drive: continuation_or_late_partial_rebound

goat_direction: down

close_near_extreme: no_mid_lower_range

CONFIDENCE NOTES

The risk is a liquidation-trap open: Globex is already stretched lower, so a failed breakdown near 29120 could trigger a sharp reclaim. The least certain piece is whether RTH extends immediately or first squeezes toward 29240–29310. The most likely invalidation trigger is an early reclaim above 29240, not necessarily a full reclaim of prior-day value.

CANARY THESIS

Bearish bias remains actionable only if RTH accepts below prior-day low and VWAP acts as resistance rather than support.

JSON
{
  "regime_read": "Recent RTH regime is bullish but extended, with four of the last five completed sessions closing green and two strong trend-up structures on 2026-05-08 and 2026-05-06. Today's Globex action rejects that pattern: MNQ is trading far below 2026-05-11 value and below prior RTH LOD near 29310 after an overnight trend-down sequence. Forecast should lean with the overnight break, against the recent bullish continuation, unless RTH immediately reclaims 29240–29310.",
  "same_dow_references": [
    "2026-05-05: Bullish Tuesday gap-up drive, but today diverges because overnight posture is gap-down below prior value, not upside initiative.",
    "2026-04-28: Useful for an early failed move followed by afternoon reclaim; relevant if sellers fail to extend below 29120–29140.",
    "2026-04-21: Best downside comparable: early strength failed, then session sold rallies beneath supply into a trend-down structure."
  ],
  "predictions": {
    "direction": "down",
    "direction_confidence": "med",
    "open_type": "gap_down_drive",
    "structure": "gap_down_drive_lower_value_balance_late_partial_rebound",
    "expected_move_size": "med",
    "predicted_net_pct_lo": -0.65,
    "predicted_net_pct_hi": -0.15,
    "predicted_intraday_span_lo_pts": 260,
    "predicted_intraday_span_hi_pts": 430
  },
  "time_window_expectations": {
    "10am": "Sellers should press or hold price below the open; reclaim above 29240 would weaken the short thesis.",
    "12pm": "Lower-value balance likely forms under prior-day low / broken demand.",
    "2pm": "Watch for continuation lower if VWAP rejects; otherwise a controlled short-covering bounce.",
    "4pm": "Close expected below the RTH open, likely mid-lower range unless late reclaim clears 29310."
  },
  "probable_goat": {
    "direction": "short",
    "time_window": "opening/morning",
    "rationale": "Overnight trend has already broken prior-day value, so the cleanest trade is likely the first RTH sell-the-reclaim or opening continuation."
  },
  "tactical_bias": {
    "bias": "sell_reclaims_below_prior_low",
    "invalidation": "Invalidated if RTH reclaims and holds above 29240 by 10:00, accepts back above prior RTH LOD near 29310 by 10:30, or VWAP flips from resistance to support before lunch."
  },
  "prediction_tags": {
    "direction": "down",
    "structure": "gap_down_drive_lower_value_balance_late_partial_rebound",
    "open_type": "gap_down_drive",
    "lunch_behavior": "lower_value_balance_under_broken_prior_low",
    "afternoon_drive": "continuation_or_late_partial_rebound",
    "goat_direction": "down",
    "close_near_extreme": "no_mid_lower_range"
  },
  "confidence_notes": "The risk is a liquidation-trap open: Globex is already stretched lower, so a failed breakdown near 29120 could trigger a sharp reclaim. The least certain piece is whether RTH extends immediately or first squeezes toward 29240–29310. The most likely invalidation trigger is an early reclaim above 29240, not necessarily a full reclaim of prior-day value.",
  "canary": {
    "thesis_summary": "Bearish bias remains actionable only if RTH accepts below prior-day low and VWAP acts as resistance rather than support.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "prior_low_rejection",
        "label": "Price remains below prior RTH low",
        "rationale": "The bearish thesis depends on prior-day demand near 29310 staying broken.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_below": 29310
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open confirms downside acceptance",
        "rationale": "A gap-down open must either drive lower or reject upside quickly; a dip-then-reclaim would warn of liquidation trap.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "trend_break_down",
          "tolerated": [
            "trend_break_down",
            "gap_and_go",
            "rotational_open"
          ]
        },
        "weight": 2
      },
      {
        "id": "first_hour_supply_cap",
        "label": "First-hour high stays below reclaim zone",
        "rationale": "If 29240 is not reclaimed in the first hour, broken overnight support is acting as supply.",
        "check_type": "price_level_window",
        "evaluate_at": "10:30",
        "params": {
          "window": "09:30-10:30",
          "high_of_window_below": 29240
        },
        "weight": 2
      },
      {
        "id": "vwap_resistance",
        "label": "Price remains below session VWAP",
        "rationale": "Below-VWAP acceptance confirms sellers control value rather than just an opening flush.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "below"
        },
        "weight": 1
      },
      {
        "id": "midmorning_no_full_reclaim",
        "label": "No reclaim of prior-day low by late morning",
        "rationale": "A reclaim above 29310 would neutralize the gap-down breakdown and shift the day toward failed breakdown reclaim.",
        "check_type": "price_level",
        "evaluate_at": "12:00",
        "params": {
          "price_below": 29310
        },
        "weight": 2
      }
    ]
  }
}
