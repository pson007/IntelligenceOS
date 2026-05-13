---
symbol: MNQ1
date: 2026-05-07
dow: Thu
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260507_080032.png
based_on_priors: ['2026-05-06', '2026-05-05', '2026-05-04', '2026-05-01', '2026-04-30']
same_dow_refs: ['2026-04-30', '2026-04-23', '2026-04-16']
model: chatgpt_thinking
made_at: 2026-05-07T08:01:15
---
REGIME READ

Current regime is bullish continuation with upper-range overnight balance, not clean fresh trend initiation. Recent priors favor upside: 2026-05-06 was an early-flush reclaim trend-up close, 2026-05-05 was a gap-up drive with afternoon continuation, and 2026-05-01 was opening-drive then high-balance rotation. Today should lean with the pattern, but not chase blindly: MNQ is opening near/above prior-day high after an overnight high around 28815 and current trade near 28722, so the better read is buyable dip/reclaim unless 28660–28635 accepts lower. 

Pasted text

SAME-DOW REFERENCES

2026-04-30: suggests Thursday can flush hard first, then reclaim and trend higher if early demand holds.

2026-04-23: warns that a morning rally can fail into a lunch liquidation if support breaks.

2026-04-16: supports a bullish morning trend that later transitions into balance instead of a full reversal.

PREDICTIONS

Direction: up, confidence med

Open type: open_dip_then_reclaim

Structure: dip_reclaim_morning_push_lunch_balance_afternoon_probe

Expected move size: med

Net pct range: +0.15% to +0.70%

Intraday span range: 260–430 pts

TIME WINDOW EXPECTATIONS

10:00: Expect either a shallow opening dip holding 28660–28680 or a reclaim back above 28725.

12:00: If above VWAP, expect higher-low consolidation under 28800–28840.

14:00: Bias remains constructive if lunch lows hold above VWAP; watch for compression near HOD.

16:00: Base case is green close in the upper half, but not necessarily near HOD without post-15:00 confirmation.

PROBABLE GOAT

Direction: long

Time window: opening/morning

Rationale: Best risk is likely an early sweep into 28660–28700 that reclaims prior HOD/close rather than chasing near overnight high.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions: sustained 1-min closes below 28635; failure to reclaim 28725 by 10:00; session VWAP lost and rejected from below before 11:00.

PREDICTION TAGS

direction: up

structure: dip_reclaim_morning_push_lunch_balance_afternoon_probe

open_type: open_dip_then_reclaim

lunch_behavior: sideways_higher_low_build

afternoon_drive: controlled_upside_probe_or_balance

goat_direction: up

close_near_extreme: no_mid_upper_range

CONFIDENCE NOTES

The risk is that the overnight high was exhaustion after yesterday's trend day, producing a failed-breakout Thursday like 2026-04-23. Least certain is whether the open drives immediately or sweeps first. The most likely invalidation trigger is failure to reclaim 28725 by 10:00.

CANARY THESIS

Bullish continuation remains actionable only if RTH rejects the overnight pullback zone and reclaims/holds prior-day high area by mid-morning.

JSON
{
  "regime_read": "Bullish continuation with upper-range overnight balance. Recent priors favor upside continuation, especially 2026-05-06 early_flush_reclaim_trend_up_close, 2026-05-05 gap_up_drive, and 2026-05-01 opening_drive_then_high_balance_rotation. Today should lean with that pattern, but because price is already near prior-day high and below the overnight high, the cleaner bias is buy_dips_on_reclaim rather than chase strength.",
  "same_dow_references": [
    "2026-04-30: Thursday can flush hard first, then reclaim and trend higher if early demand holds.",
    "2026-04-23: Morning rally risk can fail into lunch liquidation if support breaks.",
    "2026-04-16: Bullish morning trend may transition into balance rather than full reversal."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "open_dip_then_reclaim",
    "structure": "dip_reclaim_morning_push_lunch_balance_afternoon_probe",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.15,
    "predicted_net_pct_hi": 0.7,
    "predicted_intraday_span_lo_pts": 260,
    "predicted_intraday_span_hi_pts": 430
  },
  "time_window_expectations": {
    "10am": "Opening dip should either hold 28660-28680 or reclaim back above 28725.",
    "12pm": "If above VWAP, expect higher-low consolidation under 28800-28840.",
    "2pm": "Constructive bias remains if lunch lows hold above VWAP; watch for HOD compression.",
    "4pm": "Base case is a green upper-half close, not automatically a near-HOD close without post-15:00 confirmation."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "opening_morning",
    "rationale": "The best asymmetric setup is likely an early sweep into 28660-28700 followed by reclaim of prior high/close."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if price accepts below 28635, fails to reclaim 28725 by 10:00, or loses session VWAP and rejects from below before 11:00."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "dip_reclaim_morning_push_lunch_balance_afternoon_probe",
    "open_type": "open_dip_then_reclaim",
    "lunch_behavior": "sideways_higher_low_build",
    "afternoon_drive": "controlled_upside_probe_or_balance",
    "goat_direction": "up",
    "close_near_extreme": "no_mid_upper_range"
  },
  "confidence_notes": "What could go wrong: overnight strength may be exhaustion after yesterday's trend day, creating a failed breakout and lunch liquidation. Least certain: whether the open dips first or immediately drives. Most likely invalidation: failure to reclaim 28725 by 10:00.",
  "canary": {
    "thesis_summary": "Bullish continuation is valid only if RTH holds the overnight pullback zone and reclaims prior-day high area early.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "overnight_posture",
        "label": "Hold above overnight demand",
        "rationale": "Acceptance below the overnight lower band would turn the gap posture into failed strength.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_above": 28635
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Opening print avoids clean downside break",
        "rationale": "The bullish case can tolerate a dip, but not a decisive trend_break_down.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "dip_then_reclaim",
          "tolerated": [
            "dip_then_reclaim",
            "rotational_open",
            "gap_and_go",
            "inside_bar_open"
          ]
        },
        "weight": 2
      },
      {
        "id": "prior_high_reclaim",
        "label": "Reclaim prior-day high zone",
        "rationale": "Holding above 28725 converts the prior high from resistance into support.",
        "check_type": "price_level",
        "evaluate_at": "10:00",
        "params": {
          "price_above": 28725
        },
        "weight": 2
      },
      {
        "id": "first_30_low",
        "label": "First 30 minutes protects pullback low",
        "rationale": "A low below 28635 during the first 30 minutes would signal acceptance back inside lower overnight range.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 28635
        },
        "weight": 2
      },
      {
        "id": "vwap_confirmation",
        "label": "Mid-morning above VWAP",
        "rationale": "Bullish continuation requires buyers to control VWAP after the opening rotation.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 1
      }
    ]
  }
}
