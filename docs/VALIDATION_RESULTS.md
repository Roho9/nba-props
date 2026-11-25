# Validation results (2026-11-25, model nb-minutes-rate-1.1)

**Status: FAILED.** Recommendation claims are disabled, and the dashboard shows NO QUALIFYING PICKS.

## Setup
- Out-of-sample window: 2026-11-04 to 2026-11-24. 5886 DraftKings main-line props (ladder-verified sides, last quote before tip-off), weekly walk-forward folds after a 14-day burn-in.
- Previous season (2025-26, ESPN season year 2026): 6460 outcome-only forecasts at proxy thresholds (floor(last-10 mean) + 0.5).

## A. Probability quality, this season, against real lines (P(over), pushes removed)
| Forecaster | Brier | Log loss | ECE |
|---|---|---|---|
| model_m1 | 0.25868 | 0.7161 | 0.0659 |
| model_m1_calibrated_wf | 0.24948 | 0.69214 | 0.019 |
| model_m2_empirical | 0.26941 | 0.76132 | 0.1077 |
| market_no_vig | 0.2449 | 0.68279 | 0.02 |
| blend_walk_forward | 0.24501 | 0.68303 | 0.0222 |
| baseline_l10_hit_rate | 0.26487 | 0.72932 | 0.0965 |
| baseline_coin_flip | 0.25 | 0.69315 | 0.0265 |

Log-loss improvement over the market (positive = better than the market), 90% bootstrap CI:
raw model [-0.0393, -0.0278], calibrated model [-0.0118, -0.0069], blend [-0.0005, -0.0].

## By prop (Brier, lower is better)
| Prop | n | Model | Market |
|---|---|---|---|
| ast | 842 | 0.24793 | 0.24432 |
| blk | 176 | 0.246 | 0.22946 |
| fg3m | 1035 | 0.26006 | 0.2465 |
| pa | 536 | 0.2661 | 0.24891 |
| pr | 637 | 0.27025 | 0.24737 |
| pra | 481 | 0.2723 | 0.24798 |
| pts | 662 | 0.26993 | 0.24881 |
| ra | 553 | 0.25983 | 0.24919 |
| reb | 587 | 0.25308 | 0.24366 |
| stl | 377 | 0.22467 | 0.22391 |

## A2. Previous season, outcome-only (no prices)
| Forecaster | Brier | Log loss | ECE |
|---|---|---|---|
| p_m1 | 0.2462 | 0.6859 | 0.0502 |
| p_m2 | 0.2489 | 0.69417 | 0.0681 |
| l10 | 0.24853 | 0.68944 | 0.059 |
| l20 | 0.24327 | 0.67837 | 0.0449 |

## B. Betting strategy
Walk-forward blend weight on the model: [0.1, 0.1, 0.0] by fold. With weight around 0 the
estimate equals the no-vig price, so no side has positive EV after the vig, and the selection rule placed
0 out-of-sample bets. No ROI, drawdown or hit-rate figure exists to report, and none is claimed.

## Interpretation
- The model's point projections are informative (correlation 0.84 with actual outcomes), but DraftKings' line is more informative (0.86, with lower absolute error in every major market).
- Where the model disagrees with the line, the disagreement has essentially no predictive value (correlation -0.03 between model-minus-line and actual-minus-line). The walk-forward recalibration slope is only 0.1498.
- Raw model probabilities were overconfident: predictions around 70% hit about 51%. Walk-forward Platt recalibration fixes the calibration (ECE 0.019) but leaves log loss above the market's.
- Last season, the model was slightly worse than a plain last-20 hit rate at proxy thresholds, so the extra structure is not earning its keep yet.
- Conclusion: on this data, the market is the better forecaster, and avoiding these wagers is the rational choice. This matches the efficient-market evidence in RESEARCH.md.

## What would change the conclusion
- More books (an Odds API key), so stale or outlying prices can be compared against consensus. Disagreement among books, not the model against one book, is where documented prop inefficiencies usually come from.
- Earlier timestamps (opening lines with recorded retrieval times, collected by the daily refresh from now on), which make CLV measurable.
- A longer sample: the gate needs at least 150 out-of-sample bets.
