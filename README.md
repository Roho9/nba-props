# NBA Prop Research Terminal

A local, risk-averse research dashboard for NBA player props. Each day it evaluates every prop
it can legitimately see, estimates probabilities with stated uncertainty, rejects anything fragile,
stress-tests the survivors, and shows at most three research candidates. It publishes
**NO QUALIFYING PICKS** whenever the evidence does not support a recommendation, and that has
been every day so far, because the walk-forward validation has not passed (see
[Current validation result](#current-validation-result)).

Paper mode only. The software never places wagers, never builds parlays, and never describes
anything as safe or guaranteed.

## Quick start

```bash
cd ~/nba-props
make setup        # Python 3.13 venv + npm install; copies .env.example to backend/.env
make backfill     # ~30 min cold: 2 seasons of box scores + this season's DraftKings prop boards
make backtest     # walk-forward validation -> backend/data/validation_report.json
make backend      # terminal 1: FastAPI on http://127.0.0.1:8000
make frontend     # terminal 2: dashboard on http://localhost:3000
```

Open **http://localhost:3000** and press **Refresh data**. The backend also refreshes on its own
every `AUTO_REFRESH_MIN` minutes between 09:00 and 23:59 in `TIMEZONE`.

Python 3.15 (the Homebrew default) is too new for the scientific wheels, so the Makefile uses
`python3.13` (override with `make setup PY_SYS=/path/to/python3.13`).

## Configuration (backend/.env)

| Variable | Default | Purpose |
|---|---|---|
| `TIMEZONE` | America/New_York | Determines "today" |
| `ESPN_ENABLED` | true | ESPN public JSON (undocumented; see Data sources) |
| `ODDS_API_KEY` | empty | The Odds API key for FanDuel/BetMGM/Caesars plus steals/blocks/turnovers markets |
| `ANTHROPIC_API_KEY` | empty | Optional LLM rewording of the research note; it cannot add numbers |
| `AUTO_REFRESH_MIN` | 30 | Background refresh interval (0 disables) |
| `ODDS_STALE_AFTER_MIN` / `INJURIES_STALE_AFTER_MIN` | 45 / 120 | Freshness limits that exclude props |

Keys are read only by the backend. The browser reaches FastAPI through a Next.js rewrite, so no key
or backend URL appears in client code.

## Data sources

Full table, costs and terms: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

- **ESPN public JSON** (free, undocumented, opt-in): schedule, box scores, game spreads and totals, injuries, and **DraftKings player props**, including the last quoted lines for this season's finished games. That last feed is what makes a real betting backtest possible.
- **The Odds API** (authorized; free 500 credits/month, paid from about $30/month): multi-book props with labeled sides. Wired in and unit-tested on fixture payloads. Not exercised live, because no key was provided.
- **Not used:** stats.nba.com (times out), NBA CDN and the official injury PDF (HTTP 403), Basketball Reference (terms), and paid feeds (no purchase authorization).

When a source fails, the affected props are excluded and the gap appears under "Market coverage and
known gaps". There is no mock or simulated fallback anywhere in the live path.

## Forecasting methodology

Details and formulas: [docs/METHODOLOGY.md](docs/METHODOLOGY.md). Literature and how each finding was
used: [docs/RESEARCH.md](docs/RESEARCH.md).

1. **Minutes model**: recency-weighted, shrunk to last season, with a back-to-back adjustment, plus teammate with/without splits (shrunk).
2. **Game script**: margin drawn from the spread; an empirical blowout-minutes curve; overtime calibrated to the league rate.
3. **Per-minute production**: recency-weighted and shrunk toward a prior, times a shrunk opponent positional factor.
4. **Negative binomial counts.** Dispersion is estimated out of sample. Combination props are fit on the summed series, so their correlation is kept.
5. **200 parameter draws × 400 script draws** with fixed seeds give a probability and its uncertainty.
6. **Second, independent model**: the empirical minutes-scaled distribution. Disagreement above 0.10 excludes a prop.
7. **Market blend**: the model is blended with the no-vig price, at a weight learned walk-forward. If the market forecasts better, the weight goes to zero.

An LLM never produces a number. The research note is generated deterministically from the payload.
The optional LLM rewording is discarded if it contains any number not in its input.

## Risk methodology

- **Hard exclusions:** any injury designation; stale odds or injury data; fewer than 8 games; volatile minutes; role in flux; probability SD above 0.07; model disagreement; outlier dependence; non-positive point or conservative EV; unverified over/under labels; alternate lines (not covered by validation); double-doubles (single model).
- **Stress tests** (minutes, usage, efficiency, pace, blowout, teammate return, better defense, no overtime, line move, worse price) exclude props that depend on overtime, on a competitive script, or on a teammate's absence, and props that fall below break-even in 4 or more scenarios.
- **Ranking** is by EV computed with the conservative probability. There is no invented confidence score. Candidates are limited to one per player and one per game, and any shared-game risk is disclosed.
- **Gate:** candidates are labeled QUALIFIED only if the validation report passes. Otherwise they are RESEARCH ONLY, and the headline says no qualifying picks.

## Backtesting methodology

`make backtest` runs `backend/app/backtest/run.py`:

- **Betting validation**: this season's DraftKings main lines (ladder-verified sides), last quote before tip-off. Weekly walk-forward folds: the blend weight and edge threshold for week *k* are fit on weeks before *k*. All projections use only games before the game date. Players who did not play are voided.
- **Outcome validation**: last season, every 6th game day, proxy thresholds (floor of last-10 mean + 0.5). It reports calibration only and is never presented as a profit result.
- **Reported:** Brier score, log loss, ECE and reliability tables for the model, the market and the baselines; the log-loss improvement against the market with a bootstrap CI; ROI with CI, drawdown, losing streak, and breakdowns by prop, probability band, role and month; plus projection bias.

## Current validation result

See the Validation page or `make summary`. The latest run is described in
[docs/VALIDATION_RESULTS.md](docs/VALIDATION_RESULTS.md).

## How to read the probabilities

- **Estimate**: the blended probability for that side. **± sd**: its spread across parameter draws.
- **Conservative**: the pessimistic version used for ranking, not a second forecast.
- **Break-even**: what the offered price requires. A 75% estimate at -400 (80% break-even) is a losing bet.
- **Historical hit rate**: observed frequency. It is shown next to the forecast and never substituted for it.
- **Potential loss**: always the full stake (-1 unit) when a prop misses.

## Tests

```bash
make test
```

Covers odds math and settlement, ESPN and Odds API parsing (including over/under verification and
API-key stripping from stored URLs), Monte Carlo reproducibility and stability, absence of look-ahead,
monotonicity, exclusion rules, negative EV at high probability, and ranking de-correlation.

## Known limitations

[docs/LIMITATIONS.md](docs/LIMITATIONS.md). In short: one sportsbook unless you add a key; unofficial
data source; ESPN's injury feed rather than the official report; no pregame lineups or tracking
data; backtest prices are near-closing; one partial season of real prop prices.

## Layout

```
backend/app/providers   espn.py, odds_api.py      data adapters
backend/app/ingest.py                             backfill + daily refresh
backend/app/models/engine.py                      forecasting (M1, M2)
backend/app/risk/engine.py                        filters, stress tests, ranking
backend/app/pipeline.py                           daily workflow, immutable predictions, invalidation, settlement
backend/app/backtest/run.py                       walk-forward validation
backend/app/api/main.py                           FastAPI
frontend/src/app                                  Today, Slate Explorer, Market Comparison, Tracker, Validation, Methodology
```

SQLite lives in `backend/data/`. Every table uses portable types. To move to PostgreSQL, set
`DATABASE_URL=postgresql+psycopg://...` and install `psycopg[binary]`.
