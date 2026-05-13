---
symbol: MNQ1
date: 2026-05-13
dow: Wed
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260513_080007.png
based_on_priors: ['2026-05-12', '2026-05-11', '2026-05-08', '2026-05-07', '2026-05-06']
same_dow_refs: ['2026-05-06', '2026-04-29', '2026-04-22']
model: chatgpt_thinking
made_at: 2026-05-13T08:00:47
---
REGIME READ

Current regime is bullish but rotational at upper value: recent completed days favor dip-reclaim behavior over clean continuation, with 2026-05-12 showing a failed opening pop followed by full afternoon V-reversal, 2026-05-11 showing early flush into late-morning trend, and 2026-05-08 showing true open-drive strength. Today opens well above prior-day close/value, but directly into the 29,390–29,420 overnight/supply shelf, so the forecast should lean bullish only after reclaim/acceptance, not naive gap-up chase.

SAME-DOW REFERENCES

2026-05-06: Suggests early flush/reclaim can become a trend-up day if the morning reclaim holds and lunch forms a higher-low base.

2026-04-29: Suggests Wednesday can absorb an opening flush and still close near HOD after a late bullish reclaim.

2026-04-22: Suggests early stop-hunt risk, then upside grind if demand is defended before noon.

PREDICTIONS

Direction: up, confidence med

Open type: gap_up_pullback_reclaim

Structure: early_pullback_reclaim_then_upper_balance_breakout_attempt

Expected move size: med

Net pct range: +0.25% to +0.85%

Intraday span range: 260–470 pts

TIME WINDOW EXPECTATIONS

10:00: Initial gap-up test likely pulls back or chops under 29,400 before deciding.

12:00: Bull case needs price back above VWAP and holding 29,350–29,375 as support.

14:00: Expect upper balance; breakout attempt if 29,420 has been absorbed.

16:00: Close likely mid-upper range or near HOD if afternoon holds above 29,400.

PROBABLE GOAT

Direction: long

Time window: morning

Rationale: Best asymmetric setup is likely a post-open dip into defended 29,335–29,350 support followed by reclaim through VWAP/29,375.

TACTICAL BIAS

Primary bias: buy_dips_after_reclaim

Invalidation conditions:

09:30–10:00 fails to hold above 29,335 after the first pullback.

Price accepts below VWAP and below 29,310 by 10:30.

Any flush through 29,290 without immediate reclaim shifts the day toward gap_failure/downside rotation.

PREDICTION TAGS

direction: up

structure: early_pullback_reclaim_then_upper_balance_breakout_attempt

open_type: gap_up_pullback_reclaim

lunch_behavior: high_base_or_vwap_reclaim_hold

afternoon_drive: upper_balance_breakout_attempt

goat_direction: up

close_near_extreme: no_mid_upper_range

CONFIDENCE NOTES

Main risk is the accumulated lesson around gap-up spike above 29,400 failing quickly; if that happens, this becomes a gap_up_drive_then_reversal, not a bullish reclaim. I am least sure whether 29,400–29,420 is absorbed early or acts as firm supply into a deeper morning rotation. The most likely invalidation trigger is failure to hold above 29,335 after the first pullback.

CANARY THESIS

Bullish bias remains actionable only if the gap-up does not become immediate 29,400 rejection and price defends the 29,335–29,350 reclaim zone by late morning.

JSON
{
  "regime_read": "Current regime is bullish but rotational at upper value: recent completed days favor dip-reclaim behavior over clean continuation, with 2026-05-12 showing a failed opening pop followed by full afternoon V-reversal, 2026-05-11 showing early flush into late-morning trend, and 2026-05-08 showing true open-drive strength. Today opens well above prior-day close/value, but directly into the 29390-29420 overnight/supply shelf, so the forecast should lean bullish only after reclaim/acceptance, not naive gap-up chase.",
  "same_dow_references": [
    "2026-05-06: Early flush/reclaim became a trend-up day after the morning reclaim held and lunch formed a higher-low base.",
    "2026-04-29: Opening flush was absorbed and converted into a late bullish reclaim near HOD.",
    "2026-04-22: Early stop-hunt risk resolved into upside grind after demand was defended before noon."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "gap_up_pullback_reclaim",
    "structure": "early_pullback_reclaim_then_upper_balance_breakout_attempt",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.25,
    "predicted_net_pct_hi": 0.85,
    "predicted_intraday_span_lo_pts": 260,
    "predicted_intraday_span_hi_pts": 470
  },
  "time_window_expectations": {
    "10am": "Initial gap-up test likely pulls back or chops under 29400 before deciding.",
    "12pm": "Bull case needs price back above VWAP and holding 29350-29375 as support.",
    "2pm": "Expect upper balance; breakout attempt if 29420 has been absorbed.",
    "4pm": "Close likely mid-upper range or near HOD if afternoon holds above 29400."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "morning",
    "rationale": "Best asymmetric setup is likely a post-open dip into defended 29335-29350 support followed by reclaim through VWAP/29375."
  },
  "tactical_bias": {
    "bias": "buy_dips_after_reclaim",
    "invalidation": "Invalid if 09:30-10:00 fails to hold above 29335 after the first pullback, price accepts below VWAP and below 29310 by 10:30, or any flush through 29290 fails to immediately reclaim."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "early_pullback_reclaim_then_upper_balance_breakout_attempt",
    "open_type": "gap_up_pullback_reclaim",
    "lunch_behavior": "high_base_or_vwap_reclaim_hold",
    "afternoon_drive": "upper_balance_breakout_attempt",
    "goat_direction": "up",
    "close_near_extreme": "no_mid_upper_range"
  },
  "confidence_notes": "Main risk is the accumulated lesson around gap-up spike above 29400 failing quickly; if that happens, this becomes a gap_up_drive_then_reversal, not a bullish reclaim. I am least sure whether 29400-29420 is absorbed early or acts as firm supply into a deeper morning rotation. The most likely invalidation trigger is failure to hold above 29335 after the first pullback.",
  "canary": {
    "thesis_summary": "Bullish bias remains actionable only if the gap-up does not become immediate 29400 rejection and price defends the 29335-29350 reclaim zone by late morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "preopen_posture",
        "label": "Pre-open holds above upper reclaim zone",
        "rationale": "A bullish RTH thesis needs the overnight premium to remain accepted instead of reverting back into prior-day value before the bell.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_above": 29335
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open avoids immediate gap failure",
        "rationale": "A hard rejection above 29400 in the first five minutes would match the known gap-up failure lesson and invalidate chase bias.",
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
        "label": "First 30 minutes defend hard support",
        "rationale": "The dip-buy plan is only valid if the first liquidation holds above the hard failure zone.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 29290
        },
        "weight": 2
      },
      {
        "id": "vwap_reclaim",
        "label": "Late morning holds above VWAP",
        "rationale": "A clean VWAP hold plus higher lows into lunch is the trigger to upgrade from high balance into trend continuation.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:45",
        "params": {
          "side": "above"
        },
        "weight": 1
      },
      {
        "id": "supply_absorption",
        "label": "Morning accepts above 29400",
        "rationale": "Upside targets widen only if the 29400-29420 supply shelf is absorbed rather than rejected.",
        "check_type": "price_level",
        "evaluate_at": "11:30",
        "params": {
          "price_above": 29400
        },
        "weight": 1
      }
    ]
  }
}
