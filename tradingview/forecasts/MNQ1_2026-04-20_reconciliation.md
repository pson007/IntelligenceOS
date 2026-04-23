---
symbol: MNQ1
date: 2026-04-20
dow: Mon
stage: reconciliation
screenshot: /Users/pson/Desktop/TradingView/MNQ1_1_20260420_222904.png
forecasts_graded: ['pre_session']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-04-20.json
made_at: 2026-04-22T22:08:24
---
ACTUAL OUTCOME

Open near 26,880, pushed slightly higher to 26,890, then sold off hard to 26,580 before a partial recovery into a 26,743 close; the day finished down with a 310-point span and a trend-down → V-reversal → grind-up shape. Screenshot/context aligns with the supplied completed-day profile. 

Pasted text

STAGE GRADES

Pre-session

Direction: ✗

Close range hit: ✗ (244 pts miss; predicted roughly 26,987–27,148, actual 26,743)

HOD captured: ✓

LOD captured: ✗

Tags correct: intraday span size, early test/reclaim idea only in the weak sense that morning remained unresolved before full break, lunch base then bid partially rhymed after the actual flush

Tags wrong: direction up, open_dip_then_reclaim, bullish staircase, constructive-to-advance lunch framing, resumed-higher afternoon, goat_direction up, close_near_extreme yes_upper_range

Bias profitable if traded: ✗

Invalidation check: Accurate invalidation logic. "Sustained acceptance below opening washout low / failed reclaim after first pullback / noon selloff that doesn't recover" did in substance fire. The forecast thesis was invalidated early and decisively.

Overall score: 2/7

FORECAST EVOLUTION

No later-stage forecasts were provided, so there is no intraday improvement sequence to compare. The only forecast missed the core signal: this was not an open-dip reclaim bullish staircase day, but an open-near-high fade with late-morning capitulation and only partial recovery. The useful part was not the bullish thesis; it was the embedded invalidation logic, which correctly identified the conditions that would kill that thesis once sellers gained acceptance below the opening structure.

LESSONS

After a 5+ green-session streak, do not default to medium-confidence continuation. Mark pre-session direction confidence low unless the first 30 minutes confirm acceptance above opening support and immediate reclaim behavior. Today's streak regime was exhausted, not persistent.

Differentiate "dip then reclaim" from "open near high fade." If price opens near the upper edge of prior value and rejects within the first 15–30 minutes, flip the opening tag immediately; that would have aligned this day with the real 09:45 rejection and 10:15 lower-high trend shift.

When the first reclaim attempt fails before 10:30, remove upper-range close assumptions. Today the forecast kept a +0.4% to +1.0% close band, but the 10:15 lower high should have forced a full reset toward a negative-close scenario.

Do not project midday long GOAT setups before confirming that the flush has already occurred. The real edge was the 11:00 capitulation flush followed by 11:20 base, not a generic noon pullback buy. Future forecasts should explicitly reserve the long GOAT for a post-stop-hunt reclaim if morning liquidation hits first.

Keep HOD/LOD asymmetry tied to structure. A "bullish staircase then balance" call should not carry a span estimate that allows for a deep downside break unless there is a separate exhaustion/failure branch. Today the span size was fine, but the distribution was on the wrong side.

JSON
{
  "actual_summary": {
    "direction": "down",
    "open_approx": 26880.0,
    "close_approx": 26743.0,
    "hod_approx": 26890.0,
    "lod_approx": 26580.0,
    "net_range_pct_open_to_close": -0.51,
    "intraday_span_pts": 310
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 244,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 300,
      "tags_correct": [
        "predicted_intraday_span_lo_hi captured realized 310-pt day"
      ],
      "tags_wrong": [
        "direction_up",
        "open_dip_then_reclaim",
        "open_dip_reclaim_bullish_staircase_then_balance",
        "constructive_consolidation_to_advance",
        "resumed_higher_after_midday_hold",
        "goat_direction_up",
        "close_near_extreme_yes_upper_range"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "The forecast anchored to bullish continuation after a stretched green streak and never matched the actual open-near-high fade, 10:15 lower-high trend break, and 11:00 capitulation flush."
    }
  },
  "evolution": "Only one forecast was provided, so there was no progression to judge. The pre-session call missed the day's true opening mechanism and direction, but its invalidation language was useful because the stated failure conditions broadly matched what actually happened once the morning reclaim failed and sellers gained control.",
  "summary": "The forecast missed direction, close location, and structure, while only getting the day's overall span and approximate HOD area right. The most salvageable element was the invalidation framework, which correctly described the conditions under which the bullish thesis should have been abandoned.",
  "lessons": [
    "After a 5+ green-session streak, downgrade pre-session continuation confidence to low until the first 30 minutes prove buyers can hold and reclaim.",
    "If the session opens near the high and rejects in the first 15-30 minutes, relabel the day immediately as open-near-high-fade rather than forcing a dip-reclaim script.",
    "Once the first reclaim attempt fails before 10:30, delete upper-range close assumptions and re-center the forecast around a negative-close or partial-recovery scenario.",
    "Only assign a midday long GOAT after the stop-hunt flush has actually occurred; otherwise keep the long setup conditional, not primary.",
    "Match span projections to directional distribution: if you allow a 300+ point day, include an explicit downside-expansion branch instead of assuming the range will be used bullishly."
  ]
}
