---
symbol: MNQ1
date: 2026-05-14
dow: Thu
stage: reconciliation
screenshot: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-14.png
forecasts_graded: ['pre_session', '1000', '1200', '1400']
ground_truth_profile: /Users/pson/Desktop/IntelligenceOS/tradingview/profiles/MNQ1_2026-05-14.json
made_at: 2026-05-14T16:08:46
---
ACTUAL OUTCOME

MNQ opened near 29,674.75, closed slightly higher at 29,686.50, made HOD near 29,783.75, and flushed to LOD near 29,595.25. Shape: bullish early drive → midday/early-PM flush → sharp reclaim → choppy midrange close.

STAGE GRADES
pre_session_forecast

Direction: ✗

Close range hit: ✗ — missed by ~41 pts above bearish close band

HOD captured: ✗

LOD captured: ✗

Tags correct: midday_flush, partial_repair, close_not_near_extreme

Tags wrong: down, rotational_open_then_failed_reclaim, goat_down, breakdown_from_failed_reclaim

Bias profitable if traded: ✗

Invalidation check: ✓ — invalidation fired immediately: open accepted above 29,555, held VWAP, and broke 29,590 before 10:30 without rejection.

Overall score: 2/7

F1

Direction: ✓

Close range hit: ✓

HOD captured: ✓

LOD captured: ✗ — actual LOD was ~40 pts above forecast LOD band

Tags correct: opening_drive, gap_up_drive, dip-buy defense, high-balance/chop, long goat, upper-half/not-extreme close

Tags wrong: lunch_compression_above_VWAP; it became hard flush instead

Bias profitable if traded: ✓

Invalidation check: ✓ — acceptance below 29,520 did not occur.

Overall score: 6/7

F2

Direction: ✓

Close range hit: ✗ — missed by ~33.5 pts below forecast close band

HOD captured: ✗ — missed by ~11 pts below HOD band

LOD captured: ✗ — missed by ~4.75 pts below LOD band

Tags correct: opening_drive, goat_long, afternoon upside attempt/reclaim

Tags wrong: trend-day high-balance, sideways digestion above demand, close_near_extreme

Bias profitable if traded: ✓, but only barely if respecting the 29,595 stop; the trade endured a near-stop flush.

Invalidation check: ✓ mechanically — 29,595 was not broken, but the 29,640–29,665 demand thesis failed.

Overall score: 3/7

F3

Direction: ✓ — from the 14:00 rejection area, price faded into a lower close.

Close range hit: ✗ — missed by ~16.5 pts above forecast close band

HOD captured: ✓ — identified the prior high near 29,780 and capped post-14:00 upside as a failed probe

LOD captured: ✓ — LOD band included the actual 29,595.25 flush low

Tags correct: failed_late_push_then_fade, repair_rally_into_supply, post-HOD liquidation repair, broad rotation

Tags wrong: seller-control below 29,710, goat_down

Bias profitable if traded: ✓ — failed-bounce shorts from 29,680–29,715 were workable, but targets were too low.

Invalidation check: ✓ — sustained reclaim above 29,720 did not hold.

Overall score: 6/7

FORECAST EVOLUTION

Forecast quality improved sharply after the open. The pre-session forecast was mechanically invalidated almost immediately because the market opened far above its bearish ladder and accepted higher. F1 caught the real signal first: gap-up/opening-drive with defended pullbacks, while still underestimating the later flush. F2 overfit the noon strength into a cleaner trend-day continuation and missed the violent early-PM liquidation. F3 correctly recognized the 14:00 upside probe rejection and shifted to fade/rotation, but its close target was too low.

LESSONS

When RTH opens 100+ pts above the forecast ladder, invalidate pre-session direction immediately. Today's bearish levels around 29,535–29,590 were unusable once price opened near 29,675 and held above them.

After a gap-up drive, do not assume lunch compression just because VWAP pullbacks held early. F1 and F2 both underestimated the risk of a hard flush after late-morning highs.

At noon, separate "GOAT long opportunity" from "clean trend-day continuation." The 12:00 long signal was real, but the day still produced a 180+ pt round-trip and did not close near highs.

Use 14:00 probe behavior as a regime reset. The rejection near 29,740–29,755 correctly shifted the read from bullish continuation to rotational/fade.

For late-day fade forecasts, avoid over-targeting downside after demand has already held once. F3 got the fade right but projected too low; after a defended 29,600 flush, close targets should stay closer to midrange unless demand breaks again.

JSON
{
  "actual_summary": {
    "direction": "up",
    "open_approx": 29674.75,
    "close_approx": 29686.5,
    "hod_approx": 29783.75,
    "lod_approx": 29595.25,
    "net_range_pct_open_to_close": 0.0396,
    "intraday_span_pts": 188.5
  },
  "grades": {
    "pre_session_forecast": {
      "direction_hit": false,
      "close_in_band": false,
      "close_miss_pts": 41.4,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 120.25,
      "tags_correct": [
        "midday_flush",
        "partial_repair",
        "close_not_near_extreme"
      ],
      "tags_wrong": [
        "down",
        "rotational_open_then_failed_reclaim",
        "goat_down",
        "breakdown_from_failed_reclaim"
      ],
      "bias_profitable": false,
      "invalidation_correct": true,
      "overall_score": 2,
      "overall_max": 7,
      "biggest_miss": "Bearish pre-session thesis was invalidated immediately by a gap-up drive and acceptance above all key bearish levels."
    },
    "F1": {
      "direction_hit": true,
      "close_in_band": true,
      "close_miss_pts": 0,
      "hod_in_band": true,
      "lod_in_band": false,
      "lod_miss_pts": 40.25,
      "tags_correct": [
        "opening_drive",
        "gap_up_drive",
        "dip-buy defense",
        "high-balance rotation",
        "goat_long",
        "upper-half close not clean HOD close"
      ],
      "tags_wrong": [
        "lunch_compression_above_VWAP"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Correctly read the bullish open, but underestimated the depth and violence of the early-PM flush."
    },
    "F2": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 33.5,
      "hod_in_band": false,
      "lod_in_band": false,
      "lod_miss_pts": 4.75,
      "tags_correct": [
        "opening_drive",
        "goat_long",
        "afternoon upside attempt"
      ],
      "tags_wrong": [
        "trend-day high-balance",
        "sideways digestion above demand",
        "close_near_extreme"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 3,
      "overall_max": 7,
      "biggest_miss": "Overfit noon strength into trend-day continuation and missed the deep 13:20 liquidation."
    },
    "F3": {
      "direction_hit": true,
      "close_in_band": false,
      "close_miss_pts": 16.5,
      "hod_in_band": true,
      "lod_in_band": true,
      "lod_miss_pts": 0,
      "tags_correct": [
        "failed_late_push_then_fade",
        "repair_rally_into_supply",
        "post-HOD liquidation repair",
        "broad rotation"
      ],
      "tags_wrong": [
        "seller-control below 29710",
        "goat_down"
      ],
      "bias_profitable": true,
      "invalidation_correct": true,
      "overall_score": 6,
      "overall_max": 7,
      "biggest_miss": "Fade direction was right, but downside close target was too aggressive after demand near 29600 had already held."
    }
  },
  "evolution": "Forecasts improved after live structure became visible. The pre-session bearish plan failed immediately due to a gap-up drive above its entire level ladder. F1 caught the first real signal by identifying opening-drive strength and defended demand. F2 regressed by treating noon strength as clean continuation and missed the deep flush. F3 recovered by correctly identifying the 14:00 upside rejection and late rotational fade.",
  "summary": "The best forecast was F1 for full-day framing and F3 for late-day tactical adjustment. The main reconciliation is that the day was bullish-green but structurally messy: early drive and noon strength were real, yet neither produced clean trend-day continuation.",
  "lessons": [
    "When RTH opens 100+ pts above the forecast ladder, invalidate pre-session direction immediately instead of carrying stale bearish levels forward.",
    "After a gap-up drive, do not assume lunch compression just because early VWAP pullbacks held; late-morning highs can still trigger a hard liquidation leg.",
    "At noon, separate a valid GOAT long from a clean trend-day continuation call; today produced a long setup but not a high-close trend day.",
    "Use 14:00 probe rejection as a regime reset; failure near 29740-29755 correctly shifted the read from continuation to rotation/fade.",
    "For late-day fades after a defended 29600 flush, keep close targets nearer midrange unless demand breaks again."
  ]
}
