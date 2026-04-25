---
symbol: MNQ1
date: 2026-04-24
dow: Fri
stage: pre_session_forecast
mode: live_prerth
screenshot: /Users/pson/Desktop/TradingView/MNQ1_presession_20260424_091515.png
based_on_priors: ['2026-04-22', '2026-04-21', '2026-04-20', '2026-04-17', '2026-04-16']
same_dow_refs: ['2026-04-17', '2026-04-10', '2026-04-03']
model: chatgpt_thinking
made_at: 2026-04-24T09:16:06
---
REGIME READ

Short-term regime has flipped back to trend-up / grind continuation after the 4/21 liquidation break. 4/22 confirmed a stop-hunt reclaim → trend day, and overnight action continues that pattern with steady higher lows and expansion above prior value (~27000). However, coming after a sharp recovery sequence, this sits between continuation vs. exhaustion, so bias is up but with reduced confidence.

SAME-DOW REFERENCES

2026-04-17: Gap-up trend with midday shakeout → late reclaim; supports continuation but with an afternoon stress event.

2026-04-10: Morning strength → midday flush → afternoon repair; warns against chasing early highs.

2026-04-03: Early push failed → afternoon drift down; reminds that Friday can fade if opening strength stalls.

PREDICTIONS

Direction: up (confidence: low–med)

Open type: gap_up_rotational

Structure: early_push_then_midday_shakeout_then_trend_resume

Expected move size: medium

Net pct range: +0.20% to +0.75%

Intraday span range (pts): 140–260

TIME WINDOW EXPECTATIONS

10:00: Initial push or sweep of highs, risk of stall/rejection if momentum weakens

12:00: Midday shakeout / pullback toward VWAP or trend base

14:00: Reclaim attempt if structure intact; trend continuation trigger

16:00 (close): Drift higher into upper range if reclaim succeeds; otherwise mid-upper close

PROBABLE GOAT

Direction: long

Time window: midday_to_afternoon

Rationale: Dip after early extension into trend support offers best R:R for continuation

TACTICAL BIAS

Primary bias: buy_dips_after_failed_breakdown

Invalidation conditions:

Opening drive fails and price accepts back below ~27100 (prior breakout zone)

10:00 shows lower high + inability to reclaim VWAP

Lunch trades persistently below trend pack with no higher low

PREDICTION TAGS

direction: up

structure: early_push_then_midday_shakeout_then_trend_resume

open_type: gap_up_rotational

lunch_behavior: midday_pullback_then_base

afternoon_drive: upside_continuation_if_reclaimed

goat_direction: up

close_near_extreme: no_mid_upper_range

CONFIDENCE NOTES

Primary uncertainty is whether overnight trend is already extended and due for a Friday fade. The most likely failure mode is early strength that cannot hold above prior breakout (~27100), triggering a rotational or down day. Watch the 10:00 reaction closely; failure there likely shifts the day to mean-reversion instead of trend.

JSON
{
  "regime_read": "Short-term trend-up continuation after reclaim, but positioned between continuation and exhaustion following recent recovery.",
  "same_dow_references": [
    "2026-04-17: Gap-up trend with midday shakeout and late reclaim supports continuation with volatility.",
    "2026-04-10: Morning strength followed by midday flush warns against chasing early highs.",
    "2026-04-03: Early push failure led to afternoon fade, highlighting Friday reversal risk."
  ],
  "predictions": {
    "direction": "up",
    "direction_confidence": "low",
    "open_type": "gap_up_rotational",
    "structure": "early_push_then_midday_shakeout_then_trend_resume",
    "expected_move_size": "med",
    "predicted_net_pct_lo": 0.2,
    "predicted_net_pct_hi": 0.75,
    "predicted_intraday_span_lo_pts": 140,
    "predicted_intraday_span_hi_pts": 260
  },
  "time_window_expectations": {
    "10am": "Initial push into highs with risk of stall or rejection",
    "12pm": "Midday pullback toward VWAP or trend support",
    "2pm": "Potential reclaim and continuation if structure holds",
    "4pm": "Upper-range drift close if reclaim succeeds, otherwise mid-range"
  },
  "probable_goat": {
    "direction": "long",
    "time_window": "midday_to_afternoon",
    "rationale": "Midday dip into support likely offers best continuation entry"
  },
  "tactical_bias": {
    "bias": "buy_dips_after_failed_breakdown",
    "invalidation": "Acceptance below 27100, failure to reclaim VWAP by 10:00, or persistent trading below trend support into lunch"
  },
  "prediction_tags": {
    "direction": "up",
    "structure": "early_push_then_midday_shakeout_then_trend_resume",
    "open_type": "gap_up_rotational",
    "lunch_behavior": "midday_pullback_then_base",
    "afternoon_drive": "upside_continuation_if_reclaimed",
    "goat_direction": "up",
    "close_near_extreme": "no_mid_upper_range"
  },
  "confidence_notes": "Low confidence due to extension after recent reclaim trend. Early failure at highs could flip the day to rotational or down. 10:00 structure is the key validation point."
}
