# Data sources

| Data | Source | Endpoint | Auth / cost | Rate used | Terms status |
|---|---|---|---|---|---|
| Schedule, scores, game spread/total | ESPN site API | `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` | none | ≤ 3 req/s, 1 connection | Undocumented. No published API terms. Opt-in via `ESPN_ENABLED`. Personal, non-commercial research only. |
| Box scores (player and team), closing game lines | ESPN site API | `.../summary?event={id}` | none | same | same |
| Injuries | ESPN site API | `.../injuries` | none | 1 per refresh | same. Not the official NBA report: NBA's PDF host returns 403 to automated clients. |
| Player props, DraftKings (open + current line and price, finished games this season too) | ESPN core API | `sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{id}/competitions/{id}/odds/100/propBets` | none | 1 per game per refresh | same. Over and under are unlabeled. See "Side verification" below. |
| Player props, multiple books | The Odds API | `/v4/sports/basketball_nba/events/{id}/odds` | `ODDS_API_KEY`. Free 500 credits/month; paid from about $30/month | credit-budgeted per call | Authorized, licensed API |
| Historical multi-book props | The Odds API historical | `/v4/historical/...` | paid plans only | not called | Authorized. Would enable a multi-book backtest and true CLV. |

## Side verification (ESPN props)

ESPN lists the two sides of each main line as two unlabeled entries. On 2026-11-25 I compared the
entry order with each player's alternate-line ladder (DraftKings "X+" milestones are overs at
X-0.5) across three prop boards. The first entry was the over in 124 of the 125 pairs that could
be checked. The parser applies that order, then checks every pair against the ladder:

- `ladder_verified`: the ladder agrees. Eligible to qualify.
- `contradicted`: the ladder disagrees. Excluded.
- `order_only`: no ladder rung, or the two prices are too close to tell apart. Excluded from qualification. Shown in the explorer.

## Not used, and why

- **stats.nba.com / nba_api**: requests time out from this machine.
- **cdn.nba.com, official injury PDF**: HTTP 403.
- **Basketball Reference**: its terms restrict automated access.
- **BALLDONTLIE**: needs a key. The free tier's game-log depth was not evaluated.
- **SportsDataIO, Sportradar, licensed DraftKings/FanDuel feeds**: paid contracts. Nothing was purchased.

## Costs at a glance

| Setup | Monthly cost | What you get |
|---|---|---|
| Default (ESPN only) | $0 | DraftKings main and alternate lines, double-doubles; no steals/blocks/turnovers markets on this feed |
| + The Odds API free (configured) | $0 | one pre-tip pull per slate for FanDuel, BetMGM, Caesars; markets trimmed by priority to fit (remaining - 25) / days left in the month |
| + The Odds API 20K plan | about $30 | about 180 full-slate refreshes; cross-book best price and consensus |
| + historical odds (paid plan) | about $30+ | multi-book backtests since May 2023 (not wired to the backtester yet) |

## The Odds API on the free tier (verified 2026-11-25)

- Player props are available on the free plan through the per-event odds endpoint.
- Billing: 1 credit per market that returns data, per region, per game. A 12-market request for MIA @ PHI returned 8 markets and cost 8 credits. The `/sports` and `/events` endpoints cost nothing.
- Schedule: `ODDS_API_PULLS_PER_DAY=1` pull, taken once the next tip-off is within `ODDS_API_LEAD_HOURS=3`. The allowance is (remaining - 25) / days left in the month. Low-priority markets (blocks, steals, turnovers) are dropped first, then the latest games.
- Verification calls are tagged in `fetch_log` so they do not use up the day's scheduled pull. API keys are redacted from every logged URL.
