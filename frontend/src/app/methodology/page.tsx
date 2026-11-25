import { Card } from "@/components/ui";

const items: [string, string[]][] = [
  ["Data", [
    "Schedule, box scores, game spreads/totals and injuries: ESPN public JSON (undocumented, opt-in, low request rate).",
    "Player props: DraftKings as displayed by ESPN (open and current line and price). Optional multi-book coverage through The Odds API with ODDS_API_KEY.",
    "Every request is logged (fetch_log). Odds are append-only snapshots with retrieval timestamps. Nothing is simulated or substituted when a source fails: the prop is excluded and the gap is reported.",
  ]],
  ["Forecasting (M1)", [
    "Minutes: recency-weighted mean of the last 15 games (half-life 6), shrunk toward last season; SD floor 2 minutes; back-to-back ratio estimated from prior league data.",
    "Game script: final margin ~ Normal(-spread, sigma) with sigma estimated from prior games; minutes scale by an empirical blowout curve (separate for starters and bench); overtime calibrated to the league rate and concentrated in close simulated games.",
    "Production: per-minute rate with recency weights (half-life 10 games, last season down-weighted to 0.35), shrunk with 120 pseudo-minutes toward last season or the positional league rate; opponent positional allowance factor shrunk with 600 pseudo-minutes and clipped to ±15%; teammate with/without split shrunk with 8 pseudo-games.",
    "Counts: negative binomial with player dispersion shrunk toward the league value. Combination props are modeled on the summed series so their correlation is preserved.",
    "Uncertainty: 200 parameter draws × 400 game-script draws with a fixed seed. The spread of P(side) across parameter draws is the reported uncertainty.",
  ]],
  ["Cross-check (M2) and blend", [
    "M2 is the recency-weighted empirical distribution of past outcomes rescaled to tonight's minutes. |M1 − M2| above 0.10 excludes a prop.",
    "The final probability blends M1 with the no-vig market at a weight fit walk-forward on log loss. If the market is better, that weight goes to zero and the system says so.",
    "Conservative probability = blend of min(M1 10th percentile, M2) with the market. Ranking uses EV computed with that conservative probability.",
  ]],
  ["Hard exclusions", [
    "Any injury designation for the player; stale odds (>45 min) or stale injuries (>2 h); fewer than 8 current-season games; minutes CV > 0.25; role in flux (started 20-80% of last 5); recent minutes shift > 20%.",
    "Probability SD > 0.07; model disagreement > 0.10; outlier dependence (top 2 games removed moves the empirical probability > 0.12); non-positive point or conservative EV.",
    "Over/under labels unverified (ESPN lists sides unlabeled; we verify each pair against the alternate-line ladder and drop pairs that cannot be checked).",
    "Stress: overtime reliance (> 3 points), blowout dependence (> 15 points), teammate-return dependence (> 6 points), or 4+ scenarios below break-even.",
    "Double-doubles: single empirical model, never qualifies. Parlays are never constructed. At most one candidate per player and per game.",
  ]],
  ["Validation gate", [
    "Walk-forward by week on this season's real DraftKings lines; blend weight and edge threshold for week k use weeks < k only. Previous season: outcome-only validation with proxy thresholds.",
    "Live candidates are marked QUALIFIED only if the blend beats the market on out-of-sample log loss (90% CI above zero) and the top-3 rule shows positive ROI (90% CI above zero) on at least 150 bets. Otherwise they are RESEARCH ONLY and the headline reads NO QUALIFYING PICKS.",
  ]],
  ["How to read the numbers", [
    "Estimate: model probability for the side. Conservative: the deliberately pessimistic version used for ranking. Break-even: the probability the offered price requires.",
    "EV per unit: expected profit per 1 unit staked at the offered price. Every candidate also shows the full loss (−1 unit) if it misses.",
    "Historical hit rates are observations, not forecasts. A 90% last-10 hit rate typically corresponds to a much lower forward probability after shrinkage.",
  ]],
];

export default function Methodology() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {items.map(([t, xs]) => (
        <Card key={t} title={t}>
          <ul className="list-disc space-y-1.5 pl-5 text-[12.5px] leading-relaxed text-ink">{xs.map((x) => <li key={x}>{x}</li>)}</ul>
        </Card>
      ))}
      <Card title="Full documentation">
        <p className="text-[12.5px] text-mute">See README.md, docs/RESEARCH.md, docs/DATA_SOURCES.md, docs/METHODOLOGY.md and docs/LIMITATIONS.md in the project folder.</p>
      </Card>
    </div>
  );
}
