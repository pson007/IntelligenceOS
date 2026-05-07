---
symbol: MNQ1
date: 2026-05-04
dow: Mon
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260506_194309.png
based_on_priors: ['2026-05-01', '2026-04-30', '2026-04-29', '2026-04-28', '2026-04-27']
same_dow_refs: ['2026-04-27', '2026-04-20', '2026-04-13']
model: chatgpt_thinking
made_at: 2026-05-06T19:43:48
---
REGIME READ

Current regime is bullish but extended / rotational-up, not clean early continuation. Recent priors are strongly skewed bullish: 5/5 latest sessions closed green, but most did it through flush → reclaim → afternoon strength, not simple one-way continuation. The screenshot shows MNQ trading near the upper overnight range around 28,680 after a strong globex advance, so the initial forecast should lean up, but only after an opening dip/reclaim rather than chasing the gap. Key priors: 2026-05-01 opening drive into high balance, 2026-04-30 opening flush to afternoon reclaim, 2026-04-29 flush then late reclaim, and 2026-04-27 Monday reversal trend. 

Pasted text

SAME-DOW REFERENCES

2026-04-27: Monday favored early liquidation into defended demand, then afternoon recovery to near-HOD; today's analog supports buying a morning dip if it reclaims.

2026-04-20: Monday warned that open-near-high can fade first and only partially recover; this is the main risk if the gap is exhausted.

2026-04-13: Monday showed opening washout then trend-up staircase; supports treating early panic weakness as reversal fuel if VWAP/ribbon is reclaimed.

PREDICTIONS

Direction: up, confidence med

Open type: open_dip_then_reclaim

Structure: stop_hunt_reclaim_high_balance_trend_up

Expected move size: med

Net pct range: +0.15% to +0.65%

Intraday span range: 210–360 pts

TIME WINDOW EXPECTATIONS

10:00: Initial dip/rotation should hold above 28,500–28,540 and begin reclaiming VWAP.

12:00: Price should be back above 28,620–28,660 or the long thesis degrades.

14:00: If above 28,700, expect controlled continuation/balance near highs.

16:00: Base case close is upper-range, closer to HOD than midrange.

PROBABLE GOAT

Direction: long

Time window: morning

Rationale: Best asymmetry is likely after an opening stop-hunt into 28,520–28,560 that reclaims VWAP, matching the recent reversal-trend priors.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions: 09:30–10:00 flush holds below 28,500; 10:00 close remains below VWAP; first rebound fails under 28,600 and breaks 28,450.

PREDICTION TAGS

direction: up

structure: stop_hunt_reclaim_high_balance_trend_up

open_type: open_dip_then_reclaim

lunch_behavior: constructive_high_base

afternoon_drive: controlled_upside_continuation

goat_direction: up

close_near_extreme: yes_closer_to_HOD

CONFIDENCE NOTES

Main risk is that the large overnight advance has already spent the upside, creating a 2026-04-20 style open-near-high fade. Least certain variable is whether the open gives a clean reclaim or chops above VWAP without edge. The most likely invalidation trigger is failure to hold above 28,500 during the first 30 minutes.

CANARY THESIS

Long bias remains actionable only if the open absorbs the gap, holds the 28,500 area, and reclaims VWAP by mid-morning.

JSON
{
  "regime_read": "Current regime is bullish but extended / rotational-up, not clean early continuation. Recent priors are strongly skewed bullish: 5/5 latest sessions closed green, but most did it through flush -> reclaim -> afternoon strength, not simple one-way continuation. The screenshot shows MNQ trading near the upper overnight range around 28680 after a strong globex advance, so the initial forecast should lean up, but only after an opening dip/reclaim rather than chasing the gap. Key priors: 2026-05-01 opening drive into high balance, 2026-04-30 opening flush to afternoon reclaim, 2026-04-29 flush then late reclaim, and 2026-04-27 Monday reversal trend.",
  "same_dow_references": [
    "2026-04-27: Monday favored early liquidation into defended demand, then afternoon recovery to near-HOD; today's analog supports buying a morning dip if it reclaims.",
    "2026-04-20: Monday warned that open-near-high can fade first and only partially recover; this is the main risk if the gap is exhausted.",
    "2026-04-13: Monday showed opening washout then trend-up staircase; supports treating early panic weakness as reversal fuel if VWAP/ribbon is reclaimed."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "open_dip_then_reclaim",
    "structure": "stop_hunt_reclaim_high_balance_trend_up",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.15,
    "predicted_net_pct_hi": 0.65,
    "predicted_intraday_span_lo_pts": 210,
    "predicted_intraday_span_hi_pts": 360
  },
  "time_window_expectations": {
    "10am": "Initial dip/rotation should hold above 28500-28540 and begin reclaiming VWAP.",
    "12pm": "Price should be back above 28620-28660 or the long thesis degrades.",
    "2pm": "If above 28700, expect controlled continuation/balance near highs.",
    "4pm": "Base case close is upper-range, closer to HOD than midrange."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "morning",
    "rationale": "Best asymmetry is likely after an opening stop-hunt into 28520-28560 that reclaims VWAP, matching the recent reversal-trend priors."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if 09:30-10:00 flush holds below 28500, 10:00 close remains below VWAP, or first rebound fails under 28600 and breaks 28450."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "stop_hunt_reclaim_high_balance_trend_up",
    "open_type": "open_dip_then_reclaim",
    "lunch_behavior": "constructive_high_base",
    "afternoon_drive": "controlled_upside_continuation",
    "goat_direction": "up",
    "close_near_extreme": "yes_closer_to_HOD"
  },
  "confidence_notes": "Main risk is that the large overnight advance has already spent the upside, creating a 2026-04-20 style open-near-high fade. Least certain variable is whether the open gives a clean reclaim or chops above VWAP without edge. The most likely invalidation trigger is failure to hold above 28500 during the first 30 minutes.",
  "canary": {
    "thesis_summary": "Long bias remains actionable only if the open absorbs the gap, holds the 28500 area, and reclaims VWAP by mid-morning.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "overnight_posture",
        "label": "Opening posture holds above upper demand",
        "rationale": "The long thesis needs the large overnight advance to avoid immediate acceptance back below the breakout base.",
        "check_type": "price_level",
        "evaluate_at": "09:30",
        "params": {
          "price_above": 28500
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open prints dip then reclaim or controlled rotation",
        "rationale": "Chasing a gap is lower quality; the forecast depends on absorption and reclaim, not pure continuation.",
        "check_type": "open_pattern",
        "evaluate_at": "09:35",
        "params": {
          "expected": "dip_then_reclaim",
          "tolerated": [
            "dip_then_reclaim",
            "rotational_open",
            "inside_bar_open"
          ]
        },
        "weight": 1
      },
      {
        "id": "first_30_low",
        "label": "First 30 minutes avoid deeper liquidation",
        "rationale": "A break below 28450 would suggest the overnight markup is being sold, not absorbed.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 28450
        },
        "weight": 2
      },
      {
        "id": "vwap_reclaim",
        "label": "Mid-morning close above VWAP",
        "rationale": "Reclaim-trend days require price to recover VWAP before lunch; otherwise the day becomes fade/balance.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 2
      },
      {
        "id": "midday_acceptance",
        "label": "Price accepts above 28620 by noon",
        "rationale": "Holding above 28620 confirms the morning dip was absorption and keeps upper-range close odds alive.",
        "check_type": "price_level",
        "evaluate_at": "12:00",
        "params": {
          "price_above": 28620
        },
        "weight": 1
      }
    ]
  }
}
