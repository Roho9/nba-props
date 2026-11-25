# Research log

Each entry lists what kind of evidence it is, what it found, its limits, and what it changed in the
code. Evidence classes: **peer-reviewed**, **preprint**, **thesis** (graduate or undergraduate, not
peer-reviewed), **reproducible project** (code you can run), **vendor documentation**, **anecdotal**
(blogs, marketing, course descriptions).

I found no peer-reviewed study that directly measures how efficiently sportsbooks price NBA
player props. The design therefore leans on general findings about betting-market efficiency and
probability calibration, and then tests them here against real DraftKings prop prices
(see `backend/data/validation_report.json`).

## Market efficiency and why the market is the baseline to beat

| Source | Class | Finding | Limits | Effect on implementation |
|---|---|---|---|---|
| Moskowitz, "Asset Pricing and Sports Betting", NBER conference paper. https://conference.nber.org/conf_papers/f92072/f92072.pdf | working paper | Momentum and value effects exist in sports betting markets, but they are much smaller than in financial asset markets. | Game-level markets (sides and totals), not props. | The no-vig market probability is the main benchmark. The model must beat it out of sample before any recommendation claim is enabled. |
| Bouchard, Harvard senior thesis (2019), MLB line movement. https://dash.harvard.edu/bitstream/handle/1/37364609/BOUCHARD-SENIORTHESIS-2019.pdf | thesis | Across about 88,000 MLB games, larger relative line moves are less accurate on average, which suggests the market overreacts to some news. | Different sport, game lines only. | Line movement is shown as data and never treated as "sharp money". We do not trade on movement. |
| Kuper, Berkeley, NFL closing money-line efficiency. https://econ.berkeley.edu/sites/default/files/Kuper.pdf | thesis | Tests the efficiency of NFL closing lines. | NFL, game lines. | Supports using the closing price as a strong benchmark, and measuring CLV where open and close are both observed. |
| Borghesi (2009), NBA contracts on Tradesports. https://ideas.repec.org/a/buc/jpredm/v3y2009i2p65-77.html | peer-reviewed (J. Prediction Markets) | Contracts in some price bands were mispriced, but the market was more efficient than the NFL one. | Exchange, game outcomes, old. | Performance is broken down by probability band, to check whether any edge is concentrated in particular ranges. |
| Wornow (2026), Claremont McKenna thesis: NBA player deviations from FanDuel closing prop lines. https://scholarship.claremont.edu/cmc_theses/4171 | thesis | 178 players, 2022-2025: players in states with legal mobile betting deviate more from their prop lines, but in no consistent direction. | Difference-in-differences on deviations; not a profitability test. | Treat prop lines as unbiased but noisy. No directional over/under prior. |
| arXiv 2605.00864 (2026), Polymarket NBA microstructure. https://arxiv.org/html/2605.00864v1 | preprint | Executable single-market anomalies are very rare and short-lived (a median of 3.6 seconds). | Exchange microstructure, mostly in-game. | Supports the expectation that durable edges are rare. Zero qualifying picks is the default state, not a failure. |
| "Beyond the odds" course listing (Udemy) | anecdotal | Claims CLV may be meaningless in props. | Marketing text, no data. | Not relied on. CLV is reported only where open and close are both observed for the same line. |
| DEV Community "sharp vs public money" posts | anecdotal | Self-reported line-movement statistics. | Unsourced. | Ignored. |

## Calibration over accuracy

| Source | Class | Finding | Limits | Effect |
|---|---|---|---|---|
| Walsh & Joshi (2024), "Machine learning for sports betting: Should model selection be based on accuracy or calibration?", *Machine Learning with Applications* 16. https://doaj.org/article/2e36e6f3ec6a46b7b54308dee2d11c23 (preprint arXiv 2303.06021) | peer-reviewed | On NBA games, choosing models by calibration rather than accuracy produced much better betting ROI. The published and preprint figures differ, so the direction is more reliable than the magnitudes. | Game moneylines, one test season. | Models are scored on log loss, Brier score and expected calibration error, with reliability tables. The model/market blend weight is fit on log loss, walk-forward. Accuracy (hit rate) is never the selection metric. |

## Player-level count modeling

| Source | Class | Finding | Limits | Effect |
|---|---|---|---|---|
| Attard, Suda & Sammut (2023), Bayesian hierarchical modelling of NBA team performance, SCITEPRESS. https://www.scitepress.org/Papers/2023/121591/121591.pdf | peer-reviewed (conference) | A negative binomial fits basketball scoring counts better than a Poisson (overdispersion). | Team-level. | Counts use a negative binomial with dispersion shrunk from the player toward a league value. |
| Franks et al., "Meta-Analytics: Tools for Understanding the Statistical Properties of Sports Metrics", arXiv 1609.09830. https://arxiv.org/pdf/1609.09830 | preprint (later published in JQAS) | Many per-player metrics are unstable at small samples. Empirical-Bayes shrinkage improves out-of-sample prediction. | Season-level metrics. | Per-minute rates shrink toward last season or a positional prior (120 pseudo-minutes). Opponent factors shrink heavily (600 pseudo-minutes) and are clipped to ±15%. With/without teammate splits shrink with 8 pseudo-games. |
| Williams et al., Expected Points Above Average, arXiv 2405.10453. https://arxiv.org/abs/2405.10453 | preprint | Hierarchical shrinkage of shooting by player cluster. | Shot-level, descriptive. | Supports positional pooling for opponent and prior rates. |
| kfoofw/nba_espn, GitHub. https://github.com/kfoofw/nba_espn | reproducible project | Hierarchical negative binomial for points per game by position, built on ESPN data. | Personal project, not validated against lines. | Confirms that ESPN box scores are a workable data source, and the NB-by-position structure. |

## Design choices taken from basic statistics (no external claim needed)

- **Minutes times rate.** Counting stats scale with playing time, and minutes are the most volatile input, so minutes and per-minute production are modeled separately. Minutes volatility is a hard filter.
- **Combination props on the summed series.** Var(P+R+A) includes the covariances. Fitting the dispersion on the summed series keeps them, where independent marginals would understate the variance.
- **Game-script Monte Carlo.** The spread defines a margin distribution, and starters lose minutes in blowouts. The minutes-by-margin curve and the overtime rate are estimated from prior games only.
- **Parameter uncertainty.** The spread of P(side) across posterior draws of the rate and mean minutes is the reported uncertainty, and its 10th percentile feeds the conservative probability.

## Data-provider research (summary; details in DATA_SOURCES.md)

| Source | Result from this machine (2026-11-25) |
|---|---|
| stats.nba.com | Timed out (blocks non-browser clients). Not used. |
| cdn.nba.com live and schedule JSON, official injury PDF (ak-static.cms.nba.com) | HTTP 403. Not used. |
| ESPN site and core JSON | HTTP 200. Schedule, box scores, game lines, injuries, and DraftKings props including finished games this season. Undocumented, no published API terms. |
| The Odds API | Keyed. Free 500 credits/month. Player props per event, costed at markets × regions. Historical props need a paid plan (from May 2023). https://the-odds-api.com/sports/nba-odds.html , https://the-odds-api.com/historical-odds-data/ |
| BALLDONTLIE | HTTP 401 without a key. Not integrated. |
| Basketball Reference | HTTP 200, but its terms restrict automated access. Not scraped. |
| SportsDataIO, Sportradar | Paid and licensed. Not integrated (no authorization to purchase). |
