---
symbol: MNQ1!
date: 2026-03-18
stage: reconciliation
made_at: 2026-04-20T21:02:28-04:00
forecasts_graded: [F1@10:00, F2@12:00, F3@14:00]
ground_truth: profiles/MNQ1_2026-03-18.json
---

# Reconciliation — 2026-03-18

## ACTUAL OUTCOME (ground truth)

- **Open:** 24,980 · **Close:** 24,623.50 · **HOD:** 25,040 · **LOD:** 24,605
- **Shape:** Failed opening push → trend-down bear flag; midday grind lower, brief 2 PM retest, then selloff finishing near the lows.

## F1 GRADE — made at 10:00  →  **3/6**

| Criterion | Predicted | Actual | Hit? |
|---|---|---|---|
| Direction | down | down | ✓ |
| Close range | 24,780–24,860 | 24,623.50 | ✗ (miss by 156pt) |
| Rest-of-day HOD | 24,950–25,000 | ~24,940 | ✗ (miss by ~10pt) |
| Rest-of-day LOD | 24,760–24,810 | 24,605 | ✗ (miss by 155pt) |
| Structural tags | ✓ bearish / bounce fail | ✓ | partial |
| Bias if traded | short | short-was-correct | ✓ |

**Biggest miss:** Got the day bearish, but badly underestimated the magnitude of the afternoon extension and closing flush.

## F2 GRADE — made at 12:00  →  **4/6**

| Criterion | Predicted | Actual | Hit? |
|---|---|---|---|
| Direction | down | down | ✓ |
| Close range | 24,810–24,890 | 24,623.50 | ✗ (miss by 186pt) |
| Rest-of-day HOD | 24,950–24,980 | ~24,920 | ✗ (miss by ~30pt) |
| Rest-of-day LOD | 24,780–24,805 | 24,605 | ✗ (miss by 175pt) |
| Structural tags | bear_flag_lower_high_continuation | ✓ matched | ✓ |
| Bias if traded | short | ✓ | ✓ |

**Biggest miss:** Structural call was strong, but downside targets too conservative for late-session liquidation.

## F3 GRADE — made at 14:00  →  **5/6**

| Criterion | Predicted | Actual | Hit? |
|---|---|---|---|
| Direction | down | down | ✓ |
| Close range | 24,760–24,820 | 24,623.50 | ✗ (miss by 136pt) |
| Rest-of-day HOD | 24,915–24,935 | ~24,920 | **✓** |
| Rest-of-day LOD | 24,745–24,785 | 24,605 | ✗ (miss by 140pt) |
| Structural tags | lower_high_bearish_continuation | ✓ | ✓ |
| Bias if traded | short | ✓ | ✓ |

**Biggest miss:** Finally nailed the ceiling, but did not price in the true washout into the close.

## FORECAST EVOLUTION

Forecasts improved monotonically:
- **F1** caught the regime early (failed strength → bearish bias)
- **F2** upgraded the structural read to bear-flag continuation — best regime call
- **F3** delivered the most precise map, correctly capping upside, but still under-pricing the downside air-pocket

**Key signal missed across all three:** once the session kept failing to reclaim resistance and stayed in persistent lower highs, the forecasts should have expanded downside distributions far more aggressively — especially for a close-near-LOD on a true trend day.

## LESSONS

1. **On trend days, widen downside close/LOD bands after each failed rally.** Repeated lower highs + inability to reclaim value should force larger tail-risk assumptions.
2. **Use `close_near_extreme` more aggressively.** If that tag is on, the close range should include a true trend-day extreme scenario, not just a modest drift.
3. **Separate regime accuracy from magnitude accuracy.** These forecasts read direction and structure well; they systematically underpriced range extension.
4. **After 14:00, prioritize liquidation scenarios.** On a weak trend day, late-session imbalance produces non-linear moves. F3 should have included a deeper flush case below 24,745.
5. **Anchor HOD by time elapsed.** After a failed opening push and mid-morning rejection, rest-of-day HOD odds should have been capped lower earlier than F3.

**Net:** F1 identified the day type, F2 confirmed continuation structure, F3 delivered the tactical map. Recurring weakness: underestimating trend-day downside expansion.
