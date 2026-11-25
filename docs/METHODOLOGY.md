# Methodology

The concise version is on the dashboard's Methodology page. This file adds the formulas.

## Notation
For player *i*, market *s* (possibly a sum of box-score stats), game *g* on date *d*. Only games
with date < *d* are visible.

## Minutes
- m̂ = Σ wₖ minₖ / Σ wₖ over the last 15 current-season games, wₖ = 0.5^(age/6).
- If last season has ≥ 10 games: m̂ ← (n_eff·m̂ + 2·m̄_prev)/(n_eff + 2).
- σₘ = weighted SD, floored at 2.0. Minutes CV = σₘ/m̂.
- Back-to-back: m̂ × r_b2b, where r_b2b is the league ratio for players averaging ≥ 24 minutes on zero-rest nights, estimated from the prior 400 days and clipped to [0.90, 1.02].
- Teammate out (listed Out, averaging ≥ 24 minutes): minutes and rate ratios from with/without games, shrunk by n/(n+8), clipped.

## Game script
- Margin M ~ N(−spread_team, σ). σ is the SD of (final margin + closing spread) over prior games, clipped to [9, 16].
- Minutes multiplier f(|M|) is the empirical mean of minutes/season-average by margin bucket (0-6, 6-11, 11-16, 16-21, 21-26, 26+), separately for starters and bench.
- Overtime happens only when |M| < 3, with probability set so the overall rate matches the prior league OT rate. It adds 5·min(1, m̂/34) minutes.

## Production
- r̂ = (Σ wₖ yₖ + K·r₀)/(Σ wₖ minₖ + K), K = 120 minutes, wₖ = 0.5^(age/10) × (1 or 0.35 for last season).
- r₀ = last-season rate (≥ 15 games), else the league per-minute rate for the position group.
- Opponent factor: the per-minute rate this opponent allowed to the position group over its last 20 games, divided by the league rate, shrunk with 600 pseudo-minutes, clipped to [0.85, 1.15].
- μ = minutes × r × opp × teammate.

## Distribution and uncertainty
- Y | μ ~ NegBin(mean μ, dispersion α). α_player is method of moments on the residuals, shrunk to α_league with weight n/(n+20).
- Parameter draws b = 1..200: r_b ~ Gamma(mean r̂, var r̂(1+30αr̂)/E), mean minutes ~ N(m̂, σₘ/√n_eff). Script draws s = 1..400.
- P_b(over) = mean over s of P(Y > line | μ_bs). Reported: mean, SD and 10th/90th percentiles across b.
- Seeds are fixed (MC_SEED plus a hash of player, market and day). A test checks reproducibility and checks that a different seed moves P by less than 0.02.

## Second model (M2)
Recency-weighted empirical distribution of round(yₖ × m̂/minₖ × opp × teammate) over games with ≥ 10 minutes.

## Market
- Implied probability = 1/decimal odds. No-vig is the proportional two-way normalization. EV per unit = p·(dec−1) − (1−p−p_push).
- p_final = w·p_M1 + (1−w)·p_novig, with w fit walk-forward on log loss (grid 0..1).
- p_cons = w·min(P10_M1, p_M2) + (1−w)·p_novig. The ranking key is EV at p_cons.

## Validation
See `backend/app/backtest/run.py` and the Validation page. Weekly walk-forward. Blend weight and
edge threshold are chosen on prior weeks. Gate: the blend's log-loss improvement over the market
has a 90% bootstrap CI above zero, and the top-3 rule's ROI has a 90% CI above zero on ≥ 150 bets.
