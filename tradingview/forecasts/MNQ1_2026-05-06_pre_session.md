---
symbol: MNQ1
date: 2026-05-06
dow: Wed
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260505_234104.png
based_on_priors: ['2026-05-04', '2026-05-01', '2026-04-30', '2026-04-29', '2026-04-28']
same_dow_refs: ['2026-04-29', '2026-04-22', '2026-04-15']
model: chatgpt_thinking
made_at: 2026-05-05T23:41:47
---
REGIME READ

Current regime is bullish rotational-to-trending, not clean one-way continuation. Recent priors favor upside after early weakness: 04-29, 04-30, and 04-28 all absorbed morning downside and repaired higher, while 05-01 showed a gap-up drive that later balanced under supply. 05-04 is the main warning: upside can fail into a midday flush if morning highs reject. Today's overnight posture is materially stronger than those priors, with MNQ trading around 28,327, above the recent 27,780–27,935 reference area, so the first forecast should lean up, but only if the gap does not immediately reject. 

Pasted text

SAME-DOW REFERENCES

2026-04-29: Opening flush, lunch absorption, late bullish reclaim; supports a buy-the-reclaim framework rather than chasing the first print.

2026-04-22: Stop-hunt reclaim into afternoon grind; closest tactical analog if the open sweeps lower but quickly regains VWAP.

2026-04-15: Early dip-reclaim trend day with a noon reset; supports upside continuation if midday pullback holds above the morning base.

PREDICTIONS

Direction: up, confidence med

Open type: gap_up_rotational_reclaim

Structure: gap_up_open_dip_then_reclaim_afternoon_grind

Expected move size: medium

Net pct range: +0.10% to +0.55%

Intraday span range: 180–320 pts

TIME WINDOW EXPECTATIONS

10:00: Opening gap likely tests lower first; long thesis needs reclaim above 28,300 or firm VWAP hold.

12:00: Expect two-way balance above 28,240–28,270 if buyers are still in control.

14:00: If above 28,330–28,360, afternoon grind toward HOD becomes favored.

16:00: Close favored upper-half / near-HOD unless the morning gap fully fails.

PROBABLE GOAT

Direction: long

Time window: opening/morning

Rationale: Best risk/reward is likely after a gap-up pullback holds demand and reclaims VWAP, not on an immediate chase.

TACTICAL BIAS

Primary bias: buy_dips_on_reclaim

Invalidation conditions: 09:30–10:00 cannot reclaim 28,300; first 30-min low breaks and accepts below 28,220; 10:00 close remains below session VWAP after a failed gap-up push.

PREDICTION TAGS

direction: up

structure: gap_up_open_dip_then_reclaim_afternoon_grind

open_type: gap_up_rotational_reclaim

lunch_behavior: higher_low_balance_above_morning_base

afternoon_drive: upside_grind_if_above_breakout_base

goat_direction: up

close_near_extreme: yes_closer_to_HOD

CONFIDENCE NOTES

The main risk is a gap-up exhaustion fade: overnight already traveled far, so RTH buyers may refuse to extend above 28,350–28,400. The least certain piece is whether the open drives immediately or flushes first. The most likely invalidation trigger is a failed reclaim of 28,300 by 10:00.

CANARY THESIS

The long bias is valid only if the gap holds above pre-session demand and any early flush quickly reclaims 28,300/VWAP.

JSON
{
  "regime_read": "Current regime is bullish rotational-to-trending, not clean one-way continuation. Recent priors favor upside after early weakness: 04-29, 04-30, and 04-28 all absorbed morning downside and repaired higher, while 05-01 showed a gap-up drive that later balanced under supply. 05-04 is the main warning: upside can fail into a midday flush if morning highs reject. Today's overnight posture is materially stronger than those priors, with MNQ trading around 28327, above the recent 27780-27935 reference area, so the first forecast should lean up, but only if the gap does not immediately reject.",
  "same_dow_references": [
    "2026-04-29: Opening flush, lunch absorption, late bullish reclaim; supports a buy-the-reclaim framework rather than chasing the first print.",
    "2026-04-22: Stop-hunt reclaim into afternoon grind; closest tactical analog if the open sweeps lower but quickly regains VWAP.",
    "2026-04-15: Early dip-reclaim trend day with a noon reset; supports upside continuation if midday pullback holds above the morning base."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "med",
    "open_type": "gap_up_rotational_reclaim",
    "structure": "gap_up_open_dip_then_reclaim_afternoon_grind",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.1,
    "predicted_net_pct_hi": 0.55,
    "predicted_intraday_span_lo_pts": 180,
    "predicted_intraday_span_hi_pts": 320
  },
  "time_window_expectations": {
    "10am": "Opening gap likely tests lower first; long thesis needs reclaim above 28300 or firm VWAP hold.",
    "12pm": "Expect two-way balance above 28240-28270 if buyers are still in control.",
    "2pm": "If above 28330-28360, afternoon grind toward HOD becomes favored.",
    "4pm": "Close favored upper-half / near-HOD unless the morning gap fully fails."
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "opening/morning",
    "rationale": "Best risk/reward is likely after a gap-up pullback holds demand and reclaims VWAP, not on an immediate chase."
  },
  "tactical_bias": {
    "bias": "buy_dips_on_reclaim",
    "invalidation": "Invalid if 09:30-10:00 cannot reclaim 28300, first 30-min low breaks and accepts below 28220, or 10:00 close remains below session VWAP after a failed gap-up push."
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "gap_up_open_dip_then_reclaim_afternoon_grind",
    "open_type": "gap_up_rotational_reclaim",
    "lunch_behavior": "higher_low_balance_above_morning_base",
    "afternoon_drive": "upside_grind_if_above_breakout_base",
    "goat_direction": "up",
    "close_near_extreme": "yes_closer_to_HOD"
  },
  "confidence_notes": "The main risk is a gap-up exhaustion fade: overnight already traveled far, so RTH buyers may refuse to extend above 28350-28400. The least certain piece is whether the open drives immediately or flushes first. The most likely invalidation trigger is a failed reclaim of 28300 by 10:00.",
  "canary": {
    "thesis_summary": "The long bias is valid only if the gap holds above pre-session demand and any early flush quickly reclaims 28300/VWAP.",
    "default_action_if_passing": "trade_half_size",
    "default_action_if_partial": "trade_smallest",
    "default_action_if_failing": "stand_down",
    "auto_pause_if_failing": true,
    "checks": [
      {
        "id": "gap_hold",
        "label": "Gap holds above lower demand",
        "rationale": "A break below 28220 would convert the gap from acceptance into rejection.",
        "check_type": "price_level_window",
        "evaluate_at": "10:00",
        "params": {
          "window": "09:30-10:00",
          "low_of_window_above": 28220
        },
        "weight": 2
      },
      {
        "id": "open_structure",
        "label": "Open is reclaimable, not failed gap",
        "rationale": "The bullish setup needs either immediate acceptance or a fast dip-then-reclaim.",
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
        "id": "ten_oclock_reclaim",
        "label": "10:00 close above 28300",
        "rationale": "Reclaiming 28300 confirms buyers are defending the overnight breakout area.",
        "check_type": "price_level",
        "evaluate_at": "10:00",
        "params": {
          "price_above": 28300
        },
        "weight": 2
      },
      {
        "id": "vwap_control",
        "label": "Price above session VWAP by mid-morning",
        "rationale": "A gap-up long thesis should not remain below VWAP after the first rotation.",
        "check_type": "vwap_relationship",
        "evaluate_at": "10:30",
        "params": {
          "side": "above"
        },
        "weight": 2
      },
      {
        "id": "lunch_base",
        "label": "Lunch holds above breakout base",
        "rationale": "Holding above 28270 by noon keeps the afternoon grind setup alive.",
        "check_type": "price_level",
        "evaluate_at": "12:00",
        "params": {
          "price_above": 28270
        },
        "weight": 1
      }
    ]
  }
}
