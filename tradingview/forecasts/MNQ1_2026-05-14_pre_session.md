---
symbol: MNQ1
date: 2026-05-14
dow: Thu
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260514_090548.png
based_on_priors: ['2026-05-13', '2026-05-12', '2026-05-11', '2026-05-08', '2026-05-07']
same_dow_refs: ['2026-05-07', '2026-04-30', '2026-04-23']
model: chatgpt_thinking
made_at: 2026-05-14T09:06:25
---
REGIME READ

Recent regime is bullish but stretched/rotational: four of the last five completed sessions closed green, with 2026-05-08 as the clean trend-up impulse and 2026-05-13 as a bullish reclaim into afternoon breakout. Today should not naively chase that pattern because pre-open MNQ has rejected the overnight upper band near 29,570–29,590 and is now trading back near prior close/late demand around 29,475–29,500. Lean: mildly down to flat, looking for failed upside continuation rather than another clean trend-up day.

SAME-DOW REFERENCES

2026-05-07: Strong morning upside failed into a noon breakdown; useful warning if today makes an early HOD and loses the open/VWAP.

2026-04-30: Opening flush reversed into afternoon reclaim; useful if early liquidation holds above prior-day demand and reclaims VWAP by lunch.

2026-04-23: Morning rally failed into lunch/early-PM flush; best structural analogue if price cannot reclaim 29,535–29,555 after the open.

PREDICTIONS

Direction: down, confidence medium-low

Open type: rotational_open_then_failed_reclaim

Structure: morning_high_failure_midday_flush_afternoon_partial_repair

Expected move size: medium

Net pct range: -0.55% to -0.10%

Intraday span range: 260–430 pts

TIME WINDOW EXPECTATIONS

10:00: Choppy open, likely testing whether 29,500–29,535 can become resistance instead of support.

12:00: If below VWAP and under 29,500, expect the main short window into a midday flush.

14:00: Lower-value balance or partial repair attempt, but only bullish if back above 29,555.

16:00: Close likely mid-lower range unless afternoon reclaims the morning range.

PROBABLE GOAT

Direction: short

Time window: morning to midday

Rationale: Overnight failed above prior HOD/value extension, and the best asymmetric move is a failed reclaim below 29,535–29,555 into liquidation.

TACTICAL BIAS

Primary bias: sell_failed_reclaims_below_29555

Invalidation conditions:

09:30–09:45 accepts above 29,555 and holds above VWAP.

First pullback after open holds above 29,535 with rising buy volume.

Price breaks 29,590 before 10:30 without immediate rejection.

PREDICTION TAGS

direction: down

structure: morning_high_failure_midday_flush_afternoon_partial_repair

open_type: rotational_open_then_failed_reclaim

lunch_behavior: breakdown_from_failed_reclaim

afternoon_drive: partial_repair_below_morning_range

goat_direction: down

close_near_extreme: no_mid_lower_range

CONFIDENCE NOTES

The main risk is that yesterday's afternoon breakout demand remains active and turns the pre-open drop into another buyable flush. I am least sure about the open type because price is close to prior close, not deeply gapped. The most likely invalidation trigger is acceptance back above 29,555, since that would put price back inside the overnight upper balance and above the failed-breakdown zone.

CANARY THESIS

Bearish bias remains actionable only if the open fails to reclaim 29,535–29,555 and trades below VWAP into late morning.

JSON
{
  "regime_read": "Recent regime is bullish but stretched/rotational: four of the last five completed sessions closed green, with 2026-05-08 as the clean trend-up impulse and 2026-05-13 as a bullish reclaim into afternoon breakout. Today should not naively chase that pattern because pre-open MNQ has rejected the overnight upper band near 29570-29590 and is now trading back near prior close/late demand around 29475-29500. Lean: mildly down to flat, looking for failed upside continuation rather than another clean trend-up day.",
  "same_dow_references": [
    "2026-05-07: Strong morning upside failed into a noon breakdown; useful warning if today makes an early HOD and loses the open/VWAP.",
    "2026-04-30: Opening flush reversed into afternoon reclaim; useful if early liquidation holds above prior-day demand and reclaims VWAP by lunch.",
    "2026-04-23: Morning rally failed into lunch/early-PM flush; best structural analogue if price cannot reclaim 29535-29555 after the open."
  ],
  "predictions": {
    "direction": "down",
    "direction_confidence": "med",
    "open_type": "rotational_open_then_failed_reclaim",
    "structure": "morning_high_failure_midday_flush_afternoon_partial_repair",
    "expected_move_size": "med",
    "predicted_net_pct_lo": -0.55,
    "predicted_net_pct_hi": -0.10,
    "predicted_intraday_span_lo_pts": 260,
    "predicted_intraday_span_hi_pts": 430
  },
  "time_window_expectations": {
    "10am": "Choppy open, likely testing whether 29500-29535 can become resistance instead of support.",
    "12pm": "If below VWAP and under 29500, expect the main short window into a midday flush.",
    "2pm": "Lower-value balance or partial repair attempt, but only bullish if back above 29555.",
    "4pm": "Close likely mid-lower range unless afternoon reclaims the morning range."
  },
  "probable_goat": {
    "direction": "short",
    "time_window": "morning_to_midday",
    "rationale": "Overnight failed above prior HOD/value extension, and the best asymmetric move is a failed reclaim below 29535-29555 into liquidation."
  },
  "tactical_bias": {
    "bias": "sell_failed_reclaims_below_29555",
    "invalidation": "Invalid if 09:30-09:45 accepts above 29555 and holds above VWAP; invalid if the first pullback after open holds above 29535 with rising buy volume; invalid if price breaks 29590 before 10:30 without immediate rejection."
  },
  "prediction_tags": {
    "direction": "down",
    "structure": "morning_high_failure_midday_flush_afternoon_partial_repair",
    "open_type": "rotational_open_then_failed_reclaim",
    "lunch_behavior": "breakdown_from_failed_reclaim",
    "afternoon_drive": "partial_repair_below_morning_range",
    "goat_direction": "down",
    "close_near_extreme": "no_mid_lower_range"
  },
  "confidence_notes": "The main risk is that yesterday's afternoon breakout demand remains active and turns the pre-open drop into another buyable flush. I am least sure about the open type because price is close to prior close, not deeply gapped. The most likely invalidation trigger is acceptance back above 29555, since that would put price back inside the overnight upper balance and above the failed-breakdown zone.",
  "canary": {
    "thesis_summary": "Bearish bias remains actionable only if the open fails to reclaim 29535-29555 and trades below VWAP into late morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "level_sanity_open_area",
        "label": "Open remains near forecast ladder",
        "rationale": "The forecast levels are only usable if RTH opens within the current plausible pre-session area.",
        "check_type": "price_level_window",
        "evaluate_at": "09:35",
        "params": {
          "window": "09:30-09:35",
          "high_of_window_below": 29620
        },
        "weight": 2
      },
      {
        "id": "failed_upper_reclaim",
        "label": "No acceptance above 29555",
        "rationale": "Reclaiming 29555 would negate the failed-overnight-high thesis and restore bullish control.",
        "check_type": "price_level",
        "evaluate_at": "09:45",
        "params": {
          "price_below": 29555
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open does not classify as bullish drive",
        "rationale": "A gap-and-go or trend-break-up open would invalidate the short-first read.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "rotational_open",
          "tolerated": [
            "rotational_open",
            "trend_break_down",
            "dip_then_reclaim"
          ]
        },
        "weight": 1
      },
      {
        "id": "vwap_control",
        "label": "Price below session VWAP",
        "rationale": "Short bias needs sellers controlling value after the open, not just a pre-open liquidation.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:00",
        "params": {
          "side": "below"
        },
        "weight": 2
      },
      {
        "id": "morning_support_break",
        "label": "Morning loses 29475 support shelf",
        "rationale": "A clean break of the prior close/late-demand shelf confirms downside continuation rather than balance.",
        "check_type": "price_level",
        "evaluate_at": "11:00",
        "params": {
          "price_below": 29475
        },
        "weight": 2
      }
    ]
  }
}
