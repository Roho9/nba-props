"use client";
import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";
import { Badge, Card, Empty, Stat } from "@/components/ui";
import { CalibrationChart, EquityChart } from "@/components/charts";
import { pct, signed } from "@/lib/fmt";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;

const NAMES: Record<string, string> = {
  model_m1: "Model M1 (minutes × rate NB), raw", model_m1_calibrated_wf: "Model M1, walk-forward recalibrated", model_m2_empirical: "Model M2 (empirical)", market_no_vig: "Market no-vig (DraftKings)",
  blend_walk_forward: "Walk-forward blend", baseline_l10_hit_rate: "Baseline: last-10 hit rate", baseline_coin_flip: "Baseline: 50%",
  p_m1: "Model M1", p_m2: "Model M2", l10: "Baseline: last-10 hit rate", l20: "Baseline: last-20 hit rate",
};

function MetricTable({ metrics }: { metrics: Record<string, Any> }) {
  const best = Math.min(...Object.values(metrics).map((m: Any) => m.log_loss));
  return (
    <table className="w-full text-[12px]">
      <thead className="text-left text-faint"><tr><th className="py-1">Forecaster</th><th>Brier</th><th>Log loss</th><th>Calibration error (ECE)</th></tr></thead>
      <tbody className="num">{Object.entries(metrics).map(([k, m]: [string, Any]) => (
        <tr key={k} className="border-t border-line/60"><td className="py-1 font-sans">{NAMES[k] ?? k}{m.log_loss === best && <Badge tone="good">best</Badge>}</td>
          <td>{m.brier}</td><td>{m.log_loss}</td><td>{m.ece}</td></tr>))}</tbody>
    </table>
  );
}

function Strategy({ s, title }: { s: Any; title: string }) {
  if (!s || !s.n) return <Card title={title}><Empty>No out-of-sample bets selected.</Empty></Card>;
  return (
    <Card title={title}>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Bets (OOS)" value={s.n} sub={`${s.pushes} pushes`} />
        <Stat label="Hit rate" value={pct(s.hit_rate)} sub={`expected ${pct(s.expected_hit_rate)} · break-even ${pct(s.avg_break_even)}`} />
        <Stat label="ROI / unit" value={signed(s.roi)} tone={s.roi > 0 ? "good" : "bad"} sub={`90% CI ${s.roi_ci90?.[0]} to ${s.roi_ci90?.[1]}`} />
        <Stat label="Units" value={s.units} tone={s.units > 0 ? "good" : "bad"} />
        <Stat label="Max drawdown" value={`${s.max_drawdown_units} u`} tone="bad" />
        <Stat label="Longest losing streak" value={s.longest_losing_streak} />
      </div>
      <div className="mt-3"><EquityChart data={s.equity_curve} height={180} /></div>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <table className="text-[12px]"><thead className="text-left text-faint"><tr><th>By prop</th><th>n</th><th>Hit</th><th>ROI</th></tr></thead>
          <tbody className="num">{Object.entries(s.by_market).map(([k, v]: [string, Any]) => <tr key={k} className="border-t border-line/60"><td className="py-0.5 font-sans">{k}</td><td>{v.n}</td><td>{pct(v.hit)}</td><td>{signed(v.roi)}</td></tr>)}</tbody></table>
        <table className="text-[12px]"><thead className="text-left text-faint"><tr><th>By est. probability</th><th>n</th><th>Expected</th><th>Realized</th><th>ROI</th></tr></thead>
          <tbody className="num">{Object.entries(s.by_probability).map(([k, v]: [string, Any]) => <tr key={k} className="border-t border-line/60"><td className="py-0.5">{k}</td><td>{v.n}</td><td>{pct(v.expected_hit)}</td><td>{pct(v.realized_hit)}</td><td>{signed(v.roi)}</td></tr>)}</tbody></table>
        <table className="text-[12px]"><thead className="text-left text-faint"><tr><th>By role</th><th>n</th><th>ROI</th></tr></thead>
          <tbody className="num">{Object.entries(s.by_role).map(([k, v]: [string, Any]) => <tr key={k} className="border-t border-line/60"><td className="py-0.5 font-sans">{k}</td><td>{v.n}</td><td>{signed(v.roi)}</td></tr>)}</tbody></table>
        <table className="text-[12px]"><thead className="text-left text-faint"><tr><th>By month</th><th>n</th><th>ROI</th></tr></thead>
          <tbody className="num">{Object.entries(s.by_month).map(([k, v]: [string, Any]) => <tr key={k} className="border-t border-line/60"><td className="py-0.5">{k}</td><td>{v.n}</td><td>{signed(v.roi)}</td></tr>)}</tbody></table>
      </div>
    </Card>
  );
}

export default function Validation() {
  const [r, setR] = useState<Any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getJSON<Any>("/api/validation").then(setR).catch((e) => setErr(String(e))); }, []);
  if (err) return <Empty>No validation report yet. Run <code>make backtest</code>. ({err})</Empty>;
  if (!r) return <Empty>Loading…</Empty>;
  const b = r.betting_validation ?? {};
  const pv = r.outcome_validation_previous_season;
  const cal = (m: Any) => (m?.calibration ?? []).map((c: Any) => ({ pred: c.mean_pred, obs: c.observed, n: c.n }));
  return (
    <div className="space-y-4">
      <Card title="Model validation status" right={<span className="text-[11px] text-faint">generated {r.generated_at} · {r.model_version}</span>}>
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={r.status === "passed" ? "good" : "bad"}>{r.status === "passed" ? "VALIDATION PASSED" : "VALIDATION NOT PASSED"}</Badge>
          <span className="text-[12.5px] text-mute">Out-of-sample window {b.date_range?.[0]} to {b.date_range?.[1]} · {b.n_props_scored} props scored · {b.weeks} weekly folds · lines: {r.data?.lines_source}</span>
        </div>
        {b.reasons?.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-[12.5px]">{b.reasons.map((x: string) => <li key={x}>{x}</li>)}</ul>}
        <p className="mt-3 text-[12px] text-mute">Pass rule: (1) the model/market blend must beat the no-vig DraftKings probability on out-of-sample log loss with a 90% bootstrap interval above zero, and (2) the live top-3 selection rule must show positive ROI with a 90% interval above zero on at least 150 out-of-sample bets. Until both hold, the dashboard shows research candidates only.</p>
        <div className="mt-3 text-[12px]">Log-loss improvement vs market (positive = better than market), 90% CI: raw model {JSON.stringify(b.logloss_improvement_vs_market?.model_m1)} · recalibrated {JSON.stringify(b.logloss_improvement_vs_market?.model_m1_calibrated)} · blend {JSON.stringify(b.logloss_improvement_vs_market?.blend)}</div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="A. Outcome forecasting, this season (real DraftKings lines, over probability)">
          {b.probability_metrics ? <MetricTable metrics={b.probability_metrics} /> : <Empty>Insufficient data.</Empty>}
          {b.probability_metrics && <div className="mt-3"><CalibrationChart series={[
            { name: "Model M1 raw", color: "#3987e5", points: cal(b.probability_metrics.model_m1) },
            { name: "Market no-vig", color: "#d95926", points: cal(b.probability_metrics.market_no_vig) },
            { name: "Model M1 recalibrated", color: "#1baf7a", points: cal(b.probability_metrics.model_m1_calibrated_wf) },
          ]} /></div>}
        </Card>
        <Card title={`A2. Outcome forecasting, previous season (proxy thresholds, no prices)`}>
          {pv?.status === "ok" ? <>
            <p className="mb-2 text-[12px] text-mute">Season {pv.season - 1}-{String(pv.season).slice(2)} · n={pv.n} · threshold = {pv.threshold_rule}. {pv.note}</p>
            <MetricTable metrics={pv.models} />
            <div className="mt-3"><CalibrationChart series={[
              { name: "Model M1", color: "#3987e5", points: cal(pv.models.p_m1) },
              { name: "Last-10 hit rate", color: "#d95926", points: cal(pv.models.l10) },
            ]} /></div>
          </> : <Empty>Not run or insufficient data.</Empty>}
        </Card>
      </div>

      {b.by_market && (
        <Card title="Predictability by prop category (out of sample)">
          <table className="w-full text-[12px]"><thead className="text-left text-faint"><tr><th className="py-1">Prop</th><th>n</th><th>Brier model</th><th>Brier market</th><th>Observed over rate</th><th>Market implied over</th></tr></thead>
            <tbody className="num">{Object.entries(b.by_market).map(([k, v]: [string, Any]) => (
              <tr key={k} className="border-t border-line/60"><td className="py-1 font-sans">{k}</td><td>{v.n}</td>
                <td className={v.brier_model < v.brier_market ? "text-up" : "text-down"}>{v.brier_model}</td><td>{v.brier_market}</td><td>{pct(v.over_rate)}</td><td>{pct(v.mean_market_over)}</td></tr>))}</tbody></table>
        </Card>
      )}

      {b.projection_bias && (
        <Card title="Projection bias (out of sample; positive = model too high)">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Minutes mean error" value={b.projection_bias.minutes_mean_error} />
            <Stat label="Minutes MAE" value={b.projection_bias.minutes_mae} />
            <Stat label="Model minus market P(over)" value={signed(b.projection_bias.mean_model_minus_market_over)} />
          </div>
          <div className="num mt-3 text-[12px] text-mute">Mean error by prop: {Object.entries(b.projection_bias.by_market_mean_error).map(([k, v]) => `${k} ${signed(v as number, 2)}`).join(" · ")}</div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Strategy s={b.strategy_top3} title="B. Betting backtest: live rule (max 3 per day, 1 per game/player)" />
        <Strategy s={b.strategy_all_qualifying} title="B2. Betting backtest: every prop passing the filters" />
      </div>

      {b.folds && (
        <Card title="Walk-forward folds">
          <table className="w-full text-[12px]"><thead className="text-left text-faint"><tr><th className="py-1">Test week</th><th>Train n</th><th>Test n</th><th>Model weight (fit on prior weeks)</th><th>Min conservative EV</th><th>Top-3 bets</th></tr></thead>
            <tbody className="num">{b.folds.map((f: Any) => <tr key={f.week} className="border-t border-line/60"><td className="py-1">{f.week}</td><td>{f.train_n}</td><td>{f.test_n}</td><td>{f.blend_weight}</td><td>{f.min_edge}</td><td>{f.bets_top3}</td></tr>)}</tbody></table>
        </Card>
      )}

      <Card title="What this backtest can and cannot show">
        <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-mute">
          <li>Prices are the last DraftKings quote ESPN kept for each finished game (close to the closing line), so the backtest bets at roughly closing prices. Closing line value cannot be measured for those bets by construction.</li>
          <li>Historical injury reports are not available, so the backtest cannot replay the live &quot;unresolved availability&quot; exclusion; teammate absences use a no-look-ahead proxy (missed this game and the previous one).</li>
          <li>Only one partial season of real prop prices exists in the data. Last season is validated on outcomes only, with proxy thresholds, and never as a betting result.</li>
          <li>Stress tests are not replayed in the backtest (cost), so the live rule is stricter than the backtested rule.</li>
        </ul>
      </Card>
    </div>
  );
}
