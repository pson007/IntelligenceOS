---
symbol: MNQ1
date: 2026-04-30
dow: Thu
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260430_073839.png
based_on_priors: ['2026-04-24', '2026-04-23', '2026-04-22', '2026-04-21', '2026-04-20']
same_dow_refs: ['2026-04-23', '2026-04-16', '2026-04-09']
model: chatgpt_thinking
made_at: 2026-04-30T07:39:18
---
REGIME READ

Current regime is bullish rotational-reclaim, not clean continuation. Overnight sold off hard, based near ~27,200, then reclaimed toward ~27,475 pre-open, putting RTH in a stronger posture than the prior bearish Thursday template. Recent priors favor defended-demand reclaim behavior: 2026-04-24 had failed breakdown → midday reclaim → near-HOD close, and 2026-04-22 had stop-hunt reclaim → afternoon grind; against that, 2026-04-23 warns that Thursday strength can fail into a midday flush. Lean up, but only if the open holds above the reclaimed overnight base. 

Pasted text

SAME-DOW REFERENCES

2026-04-23: Bearish Thursday template; morning rally failed into lunch liquidation, so early strength cannot be trusted if price loses VWAP/lower highs.

2026-04-16: Bullish Thursday template; trend morning, then range, suggesting upside can front-load and stall after lunch.

2026-04-09: Best bullish reclaim analog; early flush, defended demand, afternoon breakout, near-HOD close.

PREDICTIONS

Direction: up, confidence med

Open type: open_dip_then_reclaim

Structure: stop_hunt_reclaim_then_afternoon_grind

Expected move size: med

Net pct range: +0.25% to +0.75%

Intraday span range: 240–390 pts

TIME WINDOW EXPECTATIONS

10:00: Initial dip/rotation should hold above ~27,365–27,390 and reclaim VWAP; failure there downgrades the long thesis.

12:00: Expect higher-low base above ~27,420; holding above ~27,440 keeps near-HOD close live.

14:00: If above ~27,500 with no reversal attempt, expect continuation rather than fade.

16:00: Close favored upper range / near HOD, roughly ~27,560–27,680 if morning support holds.

PROBABLE GOAT

Direction: long

Time window: opening/morning

Rationale: Overnight already flushed and reclaimed; best RTH edge is buying the first failed open push down if it holds above reclaimed demand.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions:

09:30–10:00 accepts below ~27,365.

10:00 close remains below session VWAP.

First rally fails below ~27,475 and prints a lower high into 10:30.

PREDICTION TAGS

direction: up

structure: stop_hunt_reclaim_then_afternoon_grind

open_type: open_dip_then_reclaim

lunch_behavior: bullish_higher_low_base

afternoon_drive: controlled_upside_continuation

goat_direction: up

close_near_extreme: yes_closer_to_HOD

CONFIDENCE NOTES

Main risk is that the overnight reclaim is already exhausted and RTH repeats 2026-04-23: morning strength, lower high, lunch flush. Least certain is whether the open dips first or immediately drives. The most likely invalidation trigger is a failed reclaim above VWAP by 10:00.

CANARY THESIS

Long bias remains actionable only if the open treats ~27,365–27,390 as reclaimed support and price is back above VWAP by mid-morning.

JSON
{
  "regime_read": "Current regime is bullish rotational-reclaim, not clean continuation. Overnight sold off hard, based near ~27200, then reclaimed toward ~27475 pre-open, putting RTH in a stronger posture than the prior bearish Thursday template. Recent priors favor defended-demand reclaim behavior: 2026-04-24 had failed breakdown to midday reclaim to near-HOD close, and 2026-04-22 had stop-hunt reclaim to afternoon grind; against that, 2026-04-23 warns that Thursday strength can fail into a midday flush. Lean up, but only if the open holds above the reclaimed overnight base.",
  "same_dow_references": [
    "2026-04-23: Bearish Thursday template; morning rally failed into lunch liquidation, so early strength cannot be trusted if price loses VWAP/lower highs.",
    "2026-04-16: Bullish Thursday template; trend morning, then range, suggesting upside can front-load and stall after lunch.",
    "2026-04-09: Best bullish reclaim analog; early flush, defended demand, afternoon breakout, near-HOD close."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "open_dip_then_reclaim",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.25,
    "predicted_net_pct_hi": 0.75,
    "predicted_intraday_span_lo_pts": 240,
    "predicted_intraday_span_hi_pts": 390
  },
  "time_window_expectations": {
    "10am": "Initial dip/rotation should hold above 27365-27390 and reclaim VWAP; failure there downgrades the long thesis.",
    "12pm": "Expect higher-low base above 27420; holding above 27440 keeps near-HOD close live.",
    "2pm": "If above 27500 with no reversal attempt, expect continuation rather than fade.",
    "4pm": "Close favored upper range / near HOD, roughly 27560-27680 if morning support holds."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "opening/morning",
    "rationale": "Overnight already flushed and reclaimed; best RTH edge is buying the first failed open push down if it holds above reclaimed demand."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if 09:30-10:00 accepts below 27365, if 10:00 remains below session VWAP, or if the first rally fails below 27475 and prints a lower high into 10:30."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "open_type": "open_dip_then_reclaim",
    "lunch_behavior": "bullish_higher_low_base",
    "afternoon_drive": "controlled_upside_continuation",
    "goat_direction": "up",
    "close_near_extreme": "yes_closer_to_HOD"
  },
  "confidence_notes": "Main risk is that the overnight reclaim is already exhausted and RTH repeats 2026-04-23: morning strength, lower high, lunch flush. Least certain is whether the open dips first or immediately drives. The most likely invalidation trigger is a failed reclaim above VWAP by 10:00.",
  "canary": {
    "thesis_summary": "Long bias remains actionable only if the open treats 27365-27390 as reclaimed support and price is back above VWAP by mid-morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "preopen_reclaim_support",
        "label": "Open holds above reclaimed overnight support",
        "rationale": "The bullish thesis depends on the overnight reclaim remaining accepted, not becoming a failed premarket squeeze.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_above": 27365
        },
        "weight": 2
      },
      {
        "id": "opening_pattern",
        "label": "Opening print does not become trend-down",
        "rationale": "An open dip is acceptable, but immediate downside continuation would align with the bearish Thursday reversal template.",
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
        "id": "first_30_low",
        "label": "First 30 minutes avoids deep support failure",
        "rationale": "A break below 27340 would show the overnight reclaim is failing and would reopen the lower range.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 27340
        },
        "weight": 2
      },
      {
        "id": "vwap_reclaim",
        "label": "Price is above VWAP by 10:00",
        "rationale": "Reclaim-trend days need VWAP acceptance; below-VWAP trade by 10:00 favors chop or liquidation.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:00",
        "params": {
          "side": "above"
        },
        "weight": 2
      },
      {
        "id": "midmorning_acceptance",
        "label": "Price accepts above pre-open high zone",
        "rationale": "Holding above 27475 by 10:30 confirms buyers are not just defending but extending.",
        "check_type": "price_level",
        "evaluate_at": "10:30",
        "params": {
          "price_above": 27475
        },
        "weight": 1
      }
    ]
  }
}
