---
symbol: MNQ1
date: 2026-05-11
dow: Mon
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260510_204953.png
based_on_priors: ['2026-05-07', '2026-05-06', '2026-05-05', '2026-05-04', '2026-05-01']
same_dow_refs: ['2026-05-04', '2026-04-27', '2026-04-20']
model: chatgpt_thinking
made_at: 2026-05-10T20:50:26
---
REGIME READ

Current regime is bullish continuation / upside auction, not balance: recent completed days show higher highs from 05-01 through 05-07, with 05-06 confirming early-flush-reclaim trend behavior and 05-05/05-01 showing gap-up drive tendencies. The 05-07 reversal warns against blindly carrying morning strength through lunch, but today's overnight posture is materially stronger: MNQ is trading far above the prior RTH close/value area, implying gap-up conditions and possible short-cover continuation unless the open accepts back below premarket demand.

SAME-DOW REFERENCES

2026-05-04: Monday failed a morning high and flushed midday; today should respect that risk if the gap-up push stalls before 11:00.

2026-04-27: Monday flushed first, then reclaimed and trended up into the close; supports buying a failed downside open if price reclaims VWAP.

2026-04-20: Monday broke down late morning, then V-reversed; warns that Monday weakness may not trend cleanly unless lower prices accept.

PREDICTIONS

Direction: up, confidence med

Open type: gap_up_rotational_reclaim

Structure: gap_up_pullback_reclaim_high_balance

Expected move size: large

Net pct range: +0.35% to +1.05%

Intraday span range: 260–460 pts

TIME WINDOW EXPECTATIONS

10:00: Opening dip or rotation tests 29300–29260; bullish if reclaimed quickly.

12:00: Price should be above VWAP or forming a higher-low base; failure here downgrades to balance/fade.

14:00: If lunch holds higher lows, expect compression near HOD and possible upside extension.

16:00: Bias is for a green close, likely mid-upper range unless afternoon loses VWAP.

PROBABLE GOAT

Direction: long

Time window: opening/morning

Rationale: Best risk/reward is likely a gap-up pullback that holds premarket demand and reclaims VWAP/OR high before noon.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions: sustained 1-min acceptance below 29240; failed VWAP reclaim after 10:30; break and hold below 29120 opening/premarket demand.

PREDICTION TAGS

direction: up

structure: gap_up_pullback_reclaim_high_balance

open_type: gap_up_rotational_reclaim

lunch_behavior: higher_low_base_required

afternoon_drive: conditional_upside_extension

goat_direction: up

close_near_extreme: no_mid_upper_range

CONFIDENCE NOTES

Main risk is a gap-up exhaustion open: price is already extended far above recent RTH value, so a failed push above 29400 could trigger liquidation. Least certain is whether the session trends after lunch or balances below HOD. The most likely invalidation trigger is VWAP loss after an initially valid 10:00 reclaim.

CANARY THESIS

Bullish gap continuation remains actionable only if the open holds above premarket demand, reclaims early rotation, and stays above VWAP into late morning.

JSON
{
  "regime_read": "Current regime is bullish continuation / upside auction, not balance: recent completed days show higher highs from 05-01 through 05-07, with 05-06 confirming early-flush-reclaim trend behavior and 05-05/05-01 showing gap-up drive tendencies. The 05-07 reversal warns against blindly carrying morning strength through lunch, but today's overnight posture is materially stronger: MNQ is trading far above the prior RTH close/value area, implying gap-up conditions and possible short-cover continuation unless the open accepts back below premarket demand.",
  "same_dow_references": [
    "2026-05-04: Monday failed a morning high and flushed midday; today should respect that risk if the gap-up push stalls before 11:00.",
    "2026-04-27: Monday flushed first, then reclaimed and trended up into the close; supports buying a failed downside open if price reclaims VWAP.",
    "2026-04-20: Monday broke down late morning, then V-reversed; warns that Monday weakness may not trend cleanly unless lower prices accept."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "gap_up_rotational_reclaim",
    "structure": "gap_up_pullback_reclaim_high_balance",
    "expected_move_size": "large",
    "predicted_net_pct_lo": 0.35,
    "predicted_net_pct_hi": 1.05,
    "predicted_intraday_span_lo_pts": 260,
    "predicted_intraday_span_hi_pts": 460
  },
  "time_window_expectations": {
    "10am": "Opening dip or rotation tests 29300-29260; bullish if reclaimed quickly.",
    "12pm": "Price should be above VWAP or forming a higher-low base; failure here downgrades to balance/fade.",
    "2pm": "If lunch holds higher lows, expect compression near HOD and possible upside extension.",
    "4pm": "Bias is for a green close, likely mid-upper range unless afternoon loses VWAP."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "opening/morning",
    "rationale": "Best risk/reward is likely a gap-up pullback that holds premarket demand and reclaims VWAP/OR high before noon."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if price accepts below 29240, fails to reclaim VWAP after 10:30, or breaks and holds below 29120 opening/premarket demand."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "gap_up_pullback_reclaim_high_balance",
    "open_type": "gap_up_rotational_reclaim",
    "lunch_behavior": "higher_low_base_required",
    "afternoon_drive": "conditional_upside_extension",
    "goat_direction": "up",
    "close_near_extreme": "no_mid_upper_range"
  },
  "confidence_notes": "Main risk is a gap-up exhaustion open: price is already extended far above recent RTH value, so a failed push above 29400 could trigger liquidation. Least certain is whether the session trends after lunch or balances below HOD. The most likely invalidation trigger is VWAP loss after an initially valid 10:00 reclaim.",
  "canary": {
    "thesis_summary": "Bullish gap continuation remains actionable only if the open holds above premarket demand, reclaims early rotation, and stays above VWAP into late morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "premarket_demand_hold",
        "label": "Open holds above upper premarket demand",
        "rationale": "A bullish gap should not accept back below the first defended demand shelf.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 29240
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open is rotational or dip-then-reclaim, not liquidation",
        "rationale": "The long thesis needs early selling to be absorbed rather than accepted.",
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
        "weight": 1
      },
      {
        "id": "vwap_reclaim",
        "label": "Price above VWAP by late morning",
        "rationale": "A valid gap continuation should regain or hold VWAP before lunch.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 2
      },
      {
        "id": "lower_demand_not_broken",
        "label": "No acceptance below lower premarket demand",
        "rationale": "Breaking 29120 would turn the setup from bullish pullback into gap-fade risk.",
        "check_type": "price_level",
        "evaluate_at": "11:00",
        "params": {
          "price_above": 29120
        },
        "weight": 2
      },
      {
        "id": "noon_continuation_check",
        "label": "Noon holds above 29300",
        "rationale": "Prior lessons require a continuation check before carrying long bias through lunch.",
        "check_type": "price_level",
        "evaluate_at": "12:00",
        "params": {
          "price_above": 29300
        },
        "weight": 2
      }
    ]
  }
}
