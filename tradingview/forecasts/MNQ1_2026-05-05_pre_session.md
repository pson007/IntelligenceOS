---
symbol: MNQ1
date: 2026-05-05
dow: Tue
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260505_213734.png
based_on_priors: ['2026-04-24', '2026-04-23', '2026-04-22', '2026-04-21', '2026-04-20']
same_dow_refs: ['2026-04-21', '2026-04-14', '2026-04-07']
model: chatgpt_thinking
made_at: 2026-05-05T21:38:14
---
REGIME READ

MNQ is in a strong upward trending regime, not balance. The screenshot shows price extended near fresh highs around 28,282 after a steep late-April/early-May advance, so the forecast should lean with momentum but expect an opening digestion/pullback rather than a clean blind chase. Recent priors favor reclaim-trend behavior when demand is defended: 2026-04-24 and 2026-04-22 both closed near HOD after early weakness was reclaimed, while 2026-04-21 is the main warning case for a Tuesday failed-opening-push trend-down. 

Pasted text

SAME-DOW REFERENCES

2026-04-21: Warns that Tuesday strength can fail fast if the opening push stalls under supply, leading to sell-the-bounce trend-down.

2026-04-14: Supports a bullish gap-and-go/staircase template when early imbalance holds and pullbacks stay shallow.

2026-04-07: Supports a flush-then-reclaim template where the best long comes after morning weakness stabilizes, not necessarily at the open.

PREDICTIONS

Direction: up, confidence med

Open type: gap_up_pullback_reclaim

Structure: opening_dip_then_afternoon_trend_up

Expected move size: med

Net pct range: +0.25% to +0.85%

Intraday span range: 260–430 pts

TIME WINDOW EXPECTATIONS

10:00: Initial pullback or chop should hold above 28,050–28,100 for the long thesis to remain clean.

12:00: Reclaim/hold above 28,240–28,280 keeps the day pointed toward near-HOD close.

14:00: If price is above VWAP and holding 28,300+, expect continuation rather than reversal.

16:00: Bias is close upper range / near HOD unless the morning low breaks and VWAP remains lost.

PROBABLE GOAT

Direction: long

Time window: morning

Rationale: Best risk/reward is likely after an opening dip proves buyers still defend the breakout zone.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions: 09:30–10:00 fails to reclaim 28,240; first-hour low breaks below 28,000 and cannot recover; price remains below VWAP after 10:30.

PREDICTION TAGS

direction: up

structure: opening_dip_then_afternoon_trend_up

open_type: gap_up_pullback_reclaim

lunch_behavior: bullish_hold_above_breakout_base

afternoon_drive: steady_upside_continuation

goat_direction: up

close_near_extreme: yes_closer_to_HOD

CONFIDENCE NOTES

The main risk is exhaustion: the daily chart is already extended, so a failed opening push could copy 2026-04-21. The least certain piece is whether the open drives immediately or first sweeps demand. The most likely invalidation trigger is a failure to reclaim/hold 28,240–28,280 by late morning.

CANARY THESIS

The long thesis remains actionable only if the opening pullback holds above the breakout/demand zone and price reclaims VWAP/28,240 by mid-morning.

JSON
{
  "regime_read": "MNQ is in a strong upward trending regime, not balance. The screenshot shows price extended near fresh highs around 28282 after a steep late-April/early-May advance, so the forecast should lean with momentum but expect an opening digestion/pullback rather than a clean blind chase. Recent priors favor reclaim-trend behavior when demand is defended: 2026-04-24 and 2026-04-22 both closed near HOD after early weakness was reclaimed, while 2026-04-21 is the main warning case for a Tuesday failed-opening-push trend-down.",
  "same_dow_references": [
    "2026-04-21: Warning case for a Tuesday failed-opening-push trend-down if early strength stalls under supply.",
    "2026-04-14: Bullish gap-and-go/staircase template if early imbalance holds and dips stay shallow.",
    "2026-04-07: Flush-then-reclaim template where morning weakness sets up the better long for afternoon squeeze."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "gap_up_pullback_reclaim",
    "structure": "opening_dip_then_afternoon_trend_up",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.25,
    "predicted_net_pct_hi": 0.85,
    "predicted_intraday_span_lo_pts": 260,
    "predicted_intraday_span_hi_pts": 430
  },
  "time_window_expectations": {
    "10am": "Initial pullback or chop should hold above 28050-28100 for the long thesis to remain clean.",
    "12pm": "Reclaim/hold above 28240-28280 keeps the day pointed toward near-HOD close.",
    "2pm": "If price is above VWAP and holding 28300+, expect continuation rather than reversal.",
    "4pm": "Bias is close upper range / near HOD unless the morning low breaks and VWAP remains lost."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "morning",
    "rationale": "Best risk/reward is likely after an opening dip proves buyers still defend the breakout zone."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if 09:30-10:00 fails to reclaim 28240, first-hour low breaks below 28000 and cannot recover, or price remains below VWAP after 10:30."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "opening_dip_then_afternoon_trend_up",
    "open_type": "gap_up_pullback_reclaim",
    "lunch_behavior": "bullish_hold_above_breakout_base",
    "afternoon_drive": "steady_upside_continuation",
    "goat_direction": "up",
    "close_near_extreme": "yes_closer_to_HOD"
  },
  "confidence_notes": "The main risk is exhaustion: the daily chart is already extended, so a failed opening push could copy 2026-04-21. The least certain piece is whether the open drives immediately or first sweeps demand. The most likely invalidation trigger is a failure to reclaim/hold 28240-28280 by late morning.",
  "canary": {
    "thesis_summary": "Long bias remains valid only if the opening pullback holds above breakout demand and price reclaims VWAP/28240 by mid-morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "preopen_breakout_posture",
        "label": "Price holds above breakout demand",
        "rationale": "A clean bullish day should not lose the upper breakout shelf before cash open.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_above": 28120
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Opening dip is reclaimed",
        "rationale": "The preferred setup is not blind continuation; it is a dip that buyers absorb quickly.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "dip_then_reclaim",
          "tolerated": [
            "dip_then_reclaim",
            "gap_and_go",
            "rotational_open"
          ]
        },
        "weight": 1
      },
      {
        "id": "first_30_low",
        "label": "First 30 minutes avoids demand failure",
        "rationale": "Breaking below 28000 would turn the setup from controlled pullback into failed breakout.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 28000
        },
        "weight": 2
      },
      {
        "id": "midmorning_reclaim",
        "label": "Reclaim above 28240 by mid-morning",
        "rationale": "A reclaim above 28240 confirms buyers are rebuilding control above the breakout base.",
        "check_type": "price_level",
        "evaluate_at": "10:30",
        "params": {
          "price_above": 28240
        },
        "weight": 2
      },
      {
        "id": "vwap_control",
        "label": "Price above session VWAP",
        "rationale": "Afternoon continuation is unlikely if price remains below VWAP after the opening auction.",
        "check_type": "vwap_relationship",
        "evaluate_at": "11:00",
        "params": {
          "side": "above"
        },
        "weight": 2
      }
    ]
  }
}
