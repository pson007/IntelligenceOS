---
symbol: MNQ1
date: 2026-05-01
dow: Fri
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260501_091041.png
based_on_priors: ['2026-04-24', '2026-04-23', '2026-04-22', '2026-04-21', '2026-04-20']
same_dow_refs: ['2026-04-24', '2026-04-17', '2026-04-10']
model: chatgpt_thinking
made_at: 2026-05-01T09:11:22
---
REGIME READ

Current regime is rotational-to-bullish reclaim, not clean trend continuation. Overnight sold off for hours, based near the 27,540–27,560 area, then reclaimed 27,600 into the pre-open; that favors a buy-dips-on-reclaim thesis, but only while 27,560–27,570 holds. Recent priors are mixed, but the highest-quality bullish analogs are 2026-04-24 and 2026-04-22: both used early weakness or stop-hunt behavior as fuel for later upside continuation and near-HOD closes. 

Pasted text

SAME-DOW REFERENCES

2026-04-24: Best same-Friday analog: early pullback into demand, midday reclaim, afternoon continuation, close near HOD.

2026-04-17: Supports upside bias if the open holds strength, but warns of a meaningful early-PM shakeout before late recovery.

2026-04-10: Suggests a bullish morning can still suffer a violent noon flush; do not overtrust early breakout unless lunch holds above reclaimed levels.

PREDICTIONS

Direction: up, confidence med

Open type: open_dip_then_reclaim

Structure: stop_hunt_reclaim_then_afternoon_grind

Expected move size: med

Net pct range: +0.20% to +0.70%

Intraday span range: 180–330 pts

TIME WINDOW EXPECTATIONS

10:00: Opening dip or rotation should hold above 27,540–27,560 and reclaim 27,600 if long thesis is alive.

12:00: Price should be basing above 27,600–27,620; failure there turns the day into balance/fade risk.

14:00: If above VWAP and 27,650+, expect controlled upside grind rather than explosive expansion.

16:00: Close favored upper range, potentially near HOD if no post-lunch reversal attempt appears.

PROBABLE GOAT

Direction: long

Time window: opening/morning

Rationale: Best edge is a stop-hunt or shallow open flush that holds above overnight demand and reclaims 27,600.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions: 09:30–10:00 accepts below 27,560; price remains below session VWAP after 10:15; first push above 27,625 fails and reverses back below 27,590.

PREDICTION TAGS

direction: up

structure: stop_hunt_reclaim_then_afternoon_grind

open_type: open_dip_then_reclaim

lunch_behavior: bullish_hold_above_reclaim_zone

afternoon_drive: controlled_upside_grind

goat_direction: up

close_near_extreme: yes_closer_to_HOD

CONFIDENCE NOTES

Main risk is that the overnight reclaim is just a pre-open squeeze into supply, not real acceptance. The least certain piece is magnitude: Friday priors support upside, but the overnight chart still shows prior sell pressure. The most likely invalidation trigger is a failed push above 27,625 followed by acceptance back under 27,590.

CANARY THESIS

Bias remains actionable only if the open flush is reclaimed quickly and price accepts above 27,600/VWAP by mid-morning.

JSON
{
  "regime_read": "Current regime is rotational-to-bullish reclaim, not clean trend continuation. Overnight sold off for hours, based near the 27540-27560 area, then reclaimed 27600 into the pre-open; that favors a buy-dips-on-reclaim thesis, but only while 27560-27570 holds. Recent priors are mixed, but the highest-quality bullish analogs are 2026-04-24 and 2026-04-22: both used early weakness or stop-hunt behavior as fuel for later upside continuation and near-HOD closes.",
  "same_dow_references": [
    "2026-04-24: Best same-Friday analog: early pullback into demand, midday reclaim, afternoon continuation, close near HOD.",
    "2026-04-17: Supports upside bias if the open holds strength, but warns of a meaningful early-PM shakeout before late recovery.",
    "2026-04-10: Suggests a bullish morning can still suffer a violent noon flush; do not overtrust early breakout unless lunch holds above reclaimed levels."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "open_dip_then_reclaim",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.2,
    "predicted_net_pct_hi": 0.7,
    "predicted_intraday_span_lo_pts": 180,
    "predicted_intraday_span_hi_pts": 330
  },
  "time_window_expectations": {
    "10am": "Opening dip or rotation should hold above 27540-27560 and reclaim 27600 if long thesis is alive.",
    "12pm": "Price should be basing above 27600-27620; failure there turns the day into balance/fade risk.",
    "2pm": "If above VWAP and 27650+, expect controlled upside grind rather than explosive expansion.",
    "4pm": "Close favored upper range, potentially near HOD if no post-lunch reversal attempt appears."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "opening/morning",
    "rationale": "Best edge is a stop-hunt or shallow open flush that holds above overnight demand and reclaims 27600."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if 09:30-10:00 accepts below 27560, price remains below session VWAP after 10:15, or first push above 27625 fails and reverses back below 27590."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "stop_hunt_reclaim_then_afternoon_grind",
    "open_type": "open_dip_then_reclaim",
    "lunch_behavior": "bullish_hold_above_reclaim_zone",
    "afternoon_drive": "controlled_upside_grind",
    "goat_direction": "up",
    "close_near_extreme": "yes_closer_to_HOD"
  },
  "confidence_notes": "Main risk is that the overnight reclaim is just a pre-open squeeze into supply, not real acceptance. The least certain piece is magnitude: Friday priors support upside, but the overnight chart still shows prior sell pressure. The most likely invalidation trigger is a failed push above 27625 followed by acceptance back under 27590.",
  "canary": {
    "thesis_summary": "Long bias depends on an open dip holding above overnight demand and reclaiming 27600/VWAP by mid-morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "overnight_demand_hold",
        "label": "Opening weakness holds above overnight demand",
        "rationale": "The long thesis requires the pre-open reclaim to remain structurally intact.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 27540
        },
        "weight": 2
      },
      {
        "id": "reclaim_27600",
        "label": "Price reclaims 27600 by 10:00",
        "rationale": "27600 is the key reclaimed shelf from the pre-open rally; failure to hold it implies balance or fade.",
        "check_type": "price_level",
        "evaluate_at": "10:00",
        "params": {
          "price_above": 27600
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open prints dip-then-reclaim or controlled rotation",
        "rationale": "The forecast assumes a stop-hunt/reclaim mechanism rather than immediate downside acceptance.",
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
        "id": "vwap_acceptance",
        "label": "Price is above session VWAP by 10:15",
        "rationale": "Above-VWAP acceptance confirms buyers control the post-open auction.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:15",
        "params": {
          "side": "above"
        },
        "weight": 2
      },
      {
        "id": "midmorning_breakout_base",
        "label": "Mid-morning holds above 27625",
        "rationale": "Acceptance above 27625 shifts the day from reclaim-only to afternoon grind potential.",
        "check_type": "price_level",
        "evaluate_at": "11:30",
        "params": {
          "price_above": 27625
        },
        "weight": 1
      }
    ]
  }
}
