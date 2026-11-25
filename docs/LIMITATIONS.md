# Known limitations

1. **One book by default.** Without `ODDS_API_KEY`, only DraftKings (via ESPN) is covered. "Best available price" and cross-book consensus are not meaningful with one book.
2. **Unofficial data source.** ESPN endpoints are undocumented and could change or disappear without notice. Their terms do not explicitly grant API use. They are used at a low rate for personal research.
3. **Injury feed is not the official NBA report.** ESPN's feed lags and simplifies designations. Any designation excludes the player, which is conservative but also drops some playable props.
4. **No confirmed lineups pregame.** Role is inferred from recent starts.
5. **Usage is a box-score proxy** ((FGA + 0.44·FTA + TOV) per 36). There is no tracking data: touches, potential assists and rebound chances are unavailable from free sources.
6. **Individual defensive matchups are not modeled.** The opponent factor is positional and team-level.
7. **Backtest prices are near-closing.** Bets in the backtest are priced at ESPN's last stored DraftKings quote. CLV is not measurable for them. Only one partial season of real prop prices is available.
8. **No historical injury reports.** The backtest cannot replay the live availability filter. Teammate absences use a no-look-ahead proxy.
9. **Stress tests are not replayed in the backtest** (cost), so the live rule is stricter than the rule that was backtested.
10. **Double-doubles** use one empirical model and never qualify. Steals, blocks and turnovers markets appear only when a provider supplies them.
11. **Coaching changes and trades** are captured only through the data: a traded player's history follows the player, and the role-change and minutes-shift filters are the safeguard.
12. **Small samples early in the season.** Shrinkage and the 8-game minimum handle this, but uncertainty is genuinely larger in October and November.
