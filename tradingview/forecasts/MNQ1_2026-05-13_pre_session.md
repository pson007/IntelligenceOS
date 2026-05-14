---
symbol: MNQ1
date: 2026-05-13
dow: Wed
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260513_080356.png
based_on_priors: ['2026-05-12', '2026-05-11', '2026-05-08', '2026-05-07', '2026-05-06']
same_dow_refs: ['2026-05-06', '2026-04-29', '2026-04-22']
model: chatgpt_thinking
made_at: 2026-05-13T08:04:38
---
REGIME READ

Current regime is bullish but stretched rotational/trend-continuation. The last five completed sessions lean upward, but not cleanly: 05-08 was a true bullish open-drive trend day, 05-11 held an early flush and reclaimed, and 05-12 produced a deep liquidation followed by a full afternoon V-reversal. Today is opening well above 05-12 value and above prior RTH high, so the forecast should lean with upside continuation only if early acceptance holds above the overnight demand shelf; otherwise this becomes a gap-up failure/reversal candidate.

SAME-DOW REFERENCES

2026-05-06: Suggests early dip/reclaim can become a sustained upside session if the first pullback holds and lunch forms a higher-low base.

2026-04-29: Supports a bullish recovery template where early weakness is absorbed and the stronger move comes later.

2026-04-22: Reinforces the Wednesday pattern of stop-hunt/reclaim, then afternoon grind higher.

PREDICTIONS

Direction: up, confidence medium

Open type: open_dip_then_reclaim

Structure: early_pullback_reclaim_to_upper_balance

Expected move size: medium

Net pct range: +0.20% to +0.75%

Intraday span range: 240–430 pts

TIME WINDOW EXPECTATIONS

10:00: Expect an opening test of 29355–29375; bullish only if reclaimed quickly.

12:00: If above VWAP and 29420, expect upper balance or slow grind.

14:00: Watch for continuation attempt through morning high; failed breakout risks range compression.

16:00: Base case is close in upper half, not necessarily clean HOD close.

PROBABLE GOAT

Direction: long

Time window: morning

Rationale: Best long likely comes from a defended gap-up pullback into overnight demand, not blind chase above 29400.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions:

09:30–10:00 low breaks and accepts below 29340

Price fails back below 29375 after an opening spike above 29420

10:30 close remains below session VWAP

PREDICTION TAGS

direction: up

structure: early_pullback_reclaim_to_upper_balance

open_type: open_dip_then_reclaim

lunch_behavior: upper_balance_if_vwap_holds

afternoon_drive: controlled_continuation_or_failed_breakout_balance

goat_direction: up

close_near_extreme: no_mid_upper_range

CONFIDENCE NOTES

The main risk is a gap-up spike over 29400 that fails quickly, matching the accumulated lesson to label that as gap_up_drive_then_reversal rather than bullish rotation. The least certain piece is whether buyers can accept above 29420 after already marking up overnight. The most likely invalidation trigger is a failed early push above 29420 followed by loss of 29375.

CANARY THESIS

Bias remains actionable only if the gap-up posture holds above overnight demand, the open does not become a fast 29400 rejection, and price stays above VWAP into late morning.

JSON
{
  "regime_read": "Current regime is bullish but stretched rotational/trend-continuation. The last five completed sessions lean upward, led by 2026-05-08 bullish_open_drive_trend_day, 2026-05-11 early_flush_to_midday_trend_then_upper_balance, and 2026-05-12 failed_opening_pop_afternoon_v_reversal. Today is trading above prior-day value and above the 2026-05-12 RTH high, so the forecast leans with upside continuation only if early acceptance holds above the overnight demand shelf; otherwise this becomes a gap-up failure/reversal candidate.",
  "same_dow_references": [
    "2026-05-06: Bullish early-flush reclaim template; suggests an early dip can become trend-up if the first pullback holds and lunch forms a higher-low base.",
    "2026-04-29: Bullish recovery day; suggests early weakness can be absorbed before a later upside push.",
    "2026-04-22: Stop-hunt reclaim into afternoon grind; supports buying defended early weakness rather than chasing the first spike."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "open_dip_then_reclaim",
    "structure": "early_pullback_reclaim_to_upper_balance",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.2,
    "predicted_net_pct_hi": 0.75,
    "predicted_intraday_span_lo_pts": 240,
    "predicted_intraday_span_hi_pts": 430
  },
  "time_window_expectations": {
    "10am": "Expect an opening test of 29355-29375; bullish only if reclaimed quickly.",
    "12pm": "If price is above VWAP and 29420, expect upper balance or slow grind higher.",
    "2pm": "Watch for continuation through the morning high; failed breakout risks range compression.",
    "4pm": "Base case is an upper-half close, not necessarily a clean HOD close."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "morning",
    "rationale": "Best long likely comes from a defended gap-up pullback into overnight demand, not blind chase above 29400."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if price accepts below 29340 during the first hour, spikes above 29420 then loses 29375, or remains below session VWAP into 10:30 ET."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "early_pullback_reclaim_to_upper_balance",
    "open_type": "open_dip_then_reclaim",
    "lunch_behavior": "upper_balance_if_vwap_holds",
    "afternoon_drive": "controlled_continuation_or_failed_breakout_balance",
    "goat_direction": "up",
    "close_near_extreme": "no_mid_upper_range"
  },
  "confidence_notes": "The main risk is a gap-up spike over 29400 that fails quickly, which should be reclassified as gap_up_drive_then_reversal. The least certain point is whether buyers can accept above 29420 after the overnight markup. The most likely invalidation trigger is a failed early push above 29420 followed by loss of 29375.",
  "canary": {
    "thesis_summary": "Bullish continuation is valid only if the gap-up pullback holds overnight demand and price accepts above VWAP rather than rejecting the 29400-29420 area.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "overnight_posture",
        "label": "Pre-open gap posture holds above demand",
        "rationale": "The bullish case depends on price staying above the overnight demand shelf instead of returning into prior-day value.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_above": 29355
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open avoids immediate gap-up rejection",
        "rationale": "A fast spike above 29400 that fails would flip the session from bullish continuation to gap-up rejection.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "dip_then_reclaim",
          "tolerated": [
            "dip_then_reclaim",
            "rotational_open",
            "gap_and_go"
          ]
        },
        "weight": 2
      },
      {
        "id": "first_30_low",
        "label": "First 30-minute low defends gap support",
        "rationale": "Breaking below this level would show the gap is being sold instead of absorbed.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 29340
        },
        "weight": 2
      },
      {
        "id": "vwap_control",
        "label": "Late morning holds above VWAP",
        "rationale": "VWAP control is needed to convert early rotation into trend continuation.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 2
      },
      {
        "id": "upper_acceptance",
        "label": "Midday accepts above overnight high zone",
        "rationale": "Acceptance above 29420 confirms buyers absorbed the obvious supply and can widen the upside target.",
        "check_type": "price_level",
        "evaluate_at": "12:00",
        "params": {
          "price_above": 29420
        },
        "weight": 1
      }
    ]
  }
}
