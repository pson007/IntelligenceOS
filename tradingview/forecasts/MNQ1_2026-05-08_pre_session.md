---
symbol: MNQ1
date: 2026-05-08
dow: Fri
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260508_082447.png
based_on_priors: ['2026-05-07', '2026-05-06', '2026-05-05', '2026-05-04', '2026-05-01']
same_dow_refs: ['2026-05-01', '2026-04-24', '2026-04-17']
model: chatgpt_thinking
made_at: 2026-05-08T08:25:28
---
REGIME READ

Current regime is bullish rotational-to-continuation, not clean trend. The last five priors show higher-value migration overall, but with frequent failed highs and midday liquidation risk: 2026-05-06 was a clean early-flush-reclaim trend-up day, 2026-05-05 and 2026-05-01 were bullish opening-drive days with later rotation/pullback, while 2026-05-07 warned that upside drives can fail into midday breakdowns. Today's Globex is firm above prior close and prior open, pressing near prior HOD/supply, so the forecast should lean up, but not assume a clean close-at-HOD without post-15:00 confirmation. 

Pasted text

SAME-DOW REFERENCES

2026-05-01: Bullish Friday gap-up drive that made the best long early, then balanced below supply; suggests opening strength can hold even if late follow-through fades.

2026-04-24: Bullish Friday pullback/reclaim trend-up; suggests a morning dip into demand can become the better long than chasing the first print.

2026-04-17: Bullish Friday gap-go with midday shelf and afternoon shakeout/reclaim; suggests trend can survive one sharp liquidation if VWAP and higher lows recover.

PREDICTIONS

Direction: up, confidence med

Open type: gap_up_pullback_reclaim

Structure: gap_up_pullback_reclaim_then_high_balance

Expected move size: medium

Net pct range: +0.25% to +0.80%

Intraday span range: 260–390 pts

TIME WINDOW EXPECTATIONS

10:00: Opening test likely checks whether 28840–28860 holds; reclaim above 28890 keeps bullish control.

12:00: If above VWAP, expect higher-value balance under/around 28950 rather than full reversal.

14:00: Watch for compression near HOD; acceptance above 28950 can open continuation, while rejection risks rotation.

16:00: Favor upper-half close, but not necessarily HOD close; late fade risk remains if 28950–28980 rejects.

PROBABLE GOAT

Direction: long

Time window: opening/morning

Rationale: Strong overnight posture above prior value favors buying the first defended RTH pullback rather than chasing an extended gap into supply.

TACTICAL BIAS

Primary bias: buy_pullback_reclaim_above_prior_high_zone

Invalidation conditions: 09:30–10:00 drive fails below 28820; price accepts below VWAP after first reclaim; 28790 breaks and cannot reclaim by 10:30.

PREDICTION TAGS

direction: up

structure: gap_up_pullback_reclaim_then_high_balance

open_type: gap_up_pullback_reclaim

lunch_behavior: high_balance_with_vwap_hold

afternoon_drive: attempted_continuation_then_late_pullback_risk

goat_direction: up

close_near_extreme: no_mid_upper_range

CONFIDENCE NOTES

The main risk is that price is opening into prior failed-high supply rather than from clean demand. The least certain piece is whether 28950 breaks or caps the day. The most likely invalidation trigger is an early push above 28920–28950 that fails back below VWAP, repeating 2026-05-07's failed-drive behavior.

CANARY THESIS

The bullish bias remains actionable only if the gap holds above prior upper value and RTH pullbacks reclaim quickly instead of accepting below 28790–28820.

JSON
{
  "regime_read": "Current regime is bullish rotational-to-continuation, not clean trend. The last five priors show higher-value migration overall, but with frequent failed highs and midday liquidation risk: 2026-05-06 was a clean early-flush-reclaim trend-up day, 2026-05-05 and 2026-05-01 were bullish opening-drive days with later rotation/pullback, while 2026-05-07 warned that upside drives can fail into midday breakdowns. Today's Globex is firm above prior close and prior open, pressing near prior HOD/supply, so the forecast should lean up, but not assume a clean close-at-HOD without post-15:00 confirmation.",
  "same_dow_references": [
    "2026-05-01: Bullish Friday gap-up drive that made the best long early, then balanced below supply; suggests opening strength can hold even if late follow-through fades.",
    "2026-04-24: Bullish Friday pullback/reclaim trend-up; suggests a morning dip into demand can become the better long than chasing the first print.",
    "2026-04-17: Bullish Friday gap-go with midday shelf and afternoon shakeout/reclaim; suggests trend can survive one sharp liquidation if VWAP and higher lows recover."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "gap_up_pullback_reclaim",
    "structure": "gap_up_pullback_reclaim_then_high_balance",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.25,
    "predicted_net_pct_hi": 0.8,
    "predicted_intraday_span_lo_pts": 260,
    "predicted_intraday_span_hi_pts": 390
  },
  "time_window_expectations": {
    "10am": "Opening test likely checks whether 28840-28860 holds; reclaim above 28890 keeps bullish control.",
    "12pm": "If above VWAP, expect higher-value balance under/around 28950 rather than full reversal.",
    "2pm": "Watch for compression near HOD; acceptance above 28950 can open continuation, while rejection risks rotation.",
    "4pm": "Favor upper-half close, but not necessarily HOD close; late fade risk remains if 28950-28980 rejects."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "opening/morning",
    "rationale": "Strong overnight posture above prior value favors buying the first defended RTH pullback rather than chasing an extended gap into supply."
  },
  "tactical_bias": {
    "bias": "buy_pullback_reclaim_above_prior_high_zone",
    "invalidation": "Invalid if 09:30-10:00 drive fails below 28820, price accepts below VWAP after first reclaim, or 28790 breaks and cannot reclaim by 10:30."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "gap_up_pullback_reclaim_then_high_balance",
    "open_type": "gap_up_pullback_reclaim",
    "lunch_behavior": "high_balance_with_vwap_hold",
    "afternoon_drive": "attempted_continuation_then_late_pullback_risk",
    "goat_direction": "up",
    "close_near_extreme": "no_mid_upper_range"
  },
  "confidence_notes": "The main risk is that price is opening into prior failed-high supply rather than from clean demand. The least certain piece is whether 28950 breaks or caps the day. The most likely invalidation trigger is an early push above 28920-28950 that fails back below VWAP, repeating 2026-05-07's failed-drive behavior.",
  "canary": {
    "thesis_summary": "Bullish bias requires the gap to hold above prior upper value and for any opening dip to reclaim quickly rather than accept below 28790-28820.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "overnight_posture",
        "label": "RTH opens above prior high-zone support",
        "rationale": "The long thesis depends on Globex strength not being fully rejected at the RTH open.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_above": 28820
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Opening print avoids hard gap failure",
        "rationale": "A tolerated dip-then-reclaim or gap-and-go keeps the bullish Friday analogs valid; trend_break_down would align more with 2026-05-07 failure.",
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
        "weight": 2
      },
      {
        "id": "first_30_low",
        "label": "First 30 minutes defend 28790",
        "rationale": "28790 is the nearby pre-session demand/TP1 zone; breaking it early would imply the gap is being sold rather than accepted.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 28790
        },
        "weight": 2
      },
      {
        "id": "vwap_control",
        "label": "Price holds above session VWAP by mid-morning",
        "rationale": "The bullish structure needs higher-value acceptance after the open, not only a pre-market gap.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 1
      },
      {
        "id": "morning_reclaim",
        "label": "Mid-morning reclaim above 28890",
        "rationale": "A close above 28890 by 11:00 confirms buyers are still controlling the upper half of the Globex range.",
        "check_type": "price_level",
        "evaluate_at": "11:00",
        "params": {
          "price_above": 28890
        },
        "weight": 1
      }
    ]
  }
}
