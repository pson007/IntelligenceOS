---
symbol: MNQ1!
date: 2026-04-20
dow: Mon
stage: pre_session_reconciliation
forecast_file: forecasts/MNQ1_2026-04-20_pre_session.json
actual_file: profiles/MNQ1_2026-04-20.json
overall_score: 4/10
made_at: 2026-04-20T22:30:00-04:00
---

# Reconciliation — Pre-Session Forecast vs Actual (2026-04-20)

## ACTUAL OUTCOME (1-line)
Forecast leaned bullish trend-up continuation; actual session was early fade and breakdown, 11:00 downside GOAT, then V-reversal and slow recovery, but still **closed red** and below supply.

## DIRECTION GRADE
- **Forecast: up** | **Actual: down (-0.51%)** | **Hit: ✗**
- Primary directional call missed. Session recovered well off the low, but completed-day result was still a red close after early bearish impulse.

## OPEN-TYPE GRADE
- **Forecast: open_dip_then_reclaim** | **Actual: open_near_high_fade** | **Hit: ✗**

## STRUCTURE GRADE
- Forecast expected dip → reclaim → bullish staircase → balance.
- Actual was opening rejection → trend-down breakdown → capitulation flush → V-reversal → grind-up under supply.
- **Partial overlap only in the afternoon grind/balance idea. Critical first half was materially wrong.**

## RANGE GRADE
- **Forecast:** +0.4% to +1.0% | **Actual:** -0.51%
- **Hit: out of band** (predicted sign AND magnitude both missed)
- Intraday span forecast 260-420pt vs actual 310pt → **span estimate was reasonable**, but net-% sign was wrong.

## GOAT GRADE
- **Forecast:** long, midday | **Actual:** down, 11:00 selloff into LOD
- **Miss on direction.** Window was only loosely adjacent, not a real match.

## TACTICAL BIAS GRADE
- **Forecast:** buy_dips_buy_reclaim
- **Profitable bias: ✓ (partial)** — blind dip-buying EARLY would've been painful, but buying the post-capitulation reclaim around 11:20 worked for the afternoon grind to 15:30.
- The bias was tradable only AFTER the forecast's own invalidation risk had largely appeared.

## TAG-BY-TAG SCORE

| Tag | Forecast | Actual | Hit |
|---|---|---|---|
| direction | up | down | ✗ |
| structure | open_dip_reclaim_bull_staircase | trend_down_v_reversal_grind_up | ✗ |
| open_type | open_dip_then_reclaim | open_near_high_fade | ✗ |
| lunch_behavior | constructive_consolidation_to_advance | base_then_slow_bid (matched) | ✓ |
| afternoon_drive | resumed_higher_after_midday_hold | controlled_bullish_drift (matched) | ✓ |
| goat_direction | up | down | ✗ |
| close_near_extreme | yes_upper_range | no_mid_upper_range | ✗ |

**Score: 2/7 tags hit.**

## CONFIDENCE CALIBRATION
The forecast's `confidence_notes` flagged the EXACT failure mode that materialized: *"exhaustion after five straight up sessions; if Mon opens with failed continuation and sellers achieve actual acceptance below early support, the forecast could be wrong."*

That risk **did** materialize in the first half. So **"med" confidence was appropriate** — model was not overconfident, and the exact downside failure it warned about is what broke the forecast. **The miss was in base-case selection, not in risk framing.**

## OVERALL SCORE

**4 / 10** — good risk framing and decent afternoon/lunch read, but core calls on direction, open type, structure, GOAT, and net range missed.

## LESSONS

1. **Separate trend-regime continuation from exhaustion-after-extension scenarios** when prior week is 5+ green days straight.
2. **Weight opening-fade risk more heavily after close-near-high streaks** — continuation becomes less reliable, not more.
3. **Split GOAT into primary impulse and best reversal trade.** Today's best long came AFTER the bearish GOAT, not instead of it.
4. **Forecast net close outcome and intraday path independently.** Today the path offered a long opportunity even though the day still closed red.
