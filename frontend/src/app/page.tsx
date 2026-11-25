"use client";
import { useState } from "react";
import { ChevronDown, ChevronRight, ShieldAlert, TriangleAlert } from "lucide-react";
import { useSlate } from "@/components/use-slate";
import { Badge, Card, Empty, KV, Stat, riskTone } from "@/components/ui";
import { DistributionChart, GameBars, MinutesChart, UsageChart } from "@/components/charts";
import { am, ago, dateTime, minutesSince, num, pct, signed, time } from "@/lib/fmt";
import type { Candidate, Overview } from "@/lib/types";

export default function Today() {
  const { data, error } = useSlate();
  if (error) return <Empty>Backend unreachable: {error}. Start it with <code>make backend</code>.</Empty>;
  if (!data) return <Empty>Loading…</Empty>;
  const o = data.overview;
  return (
    <div className="space-y-5">
      {data.pipeline?.running && <Badge tone="warn">Refresh running: pulling odds, injuries and re-running the model…</Badge>}
      {data.pipeline?.last_error && <Badge tone="bad">Last refresh failed: {data.pipeline.last_error}</Badge>}
      {!o ? <Empty>{data.message}</Empty> : (
        <>
          {data.is_today === false && (
            <div className="rounded border border-warn/50 bg-warn-dim/40 px-4 py-2 text-sm text-warn">
              Showing the {o.slate_date} evaluation. Today is {data.today}: press Refresh data.
            </div>
          )}
          <OverviewPanel o={o} />
          <TopThree o={o} cands={data.candidates} />
          {data.candidates.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-[13px] font-medium tracking-wide text-mute">DETAILED RESEARCH BREAKDOWN</h2>
              {data.candidates.map((c) => <Breakdown key={`${c.athlete_id}-${c.market}-${c.side}`} c={c} />)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function OverviewPanel({ o }: { o: Overview }) {
  const oddsAge = minutesSince(o.odds_freshest);
  const injAge = minutesSince(o.injury_report_at);
  return (
    <Card title={`Daily overview · ${new Date(o.slate_date + "T12:00:00").toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" })}`}
      right={<span className="text-[11px] text-faint">model {o.model_version} · run #{o.run_id}</span>}>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="NBA games" value={o.n_games} sub={`${o.n_games_evaluated} pregame evaluated`} />
        <Stat label="Players analyzed" value={o.n_players} />
        <Stat label="Unique props" value={o.n_props} sub="main + alternate lines" />
        <Stat label="Sportsbook offers" value={o.n_offers} sub={o.books.join(", ") || "none"} />
        <Stat label="Passed all filters" value={o.n_passed_filters} sub="before ranking" />
        <Stat label="Qualifying" value={o.n_qualifying} tone={o.n_qualifying ? "good" : "warn"} sub="max 3" />
        <Stat label="Odds freshness" value={ago(o.odds_freshest)} tone={oddsAge > 45 ? "bad" : "good"} sub={dateTime(o.odds_freshest)} />
        <Stat label="Injury report" value={ago(o.injury_report_at)} tone={injAge > 120 ? "bad" : "good"} sub="ESPN feed" />
        <Stat label="Last model run" value={ago(o.generated_at)} sub={dateTime(o.generated_at)} />
        <Stat label="Validation status" value={o.validation.validated ? "PASSED" : "NOT VALIDATED"} tone={o.validation.validated ? "good" : "bad"}
          sub={o.validation.report_generated_at ? `report ${ago(o.validation.report_generated_at)}` : "no report"} />
        <Stat label="Model weight vs market" value={pct(o.validation.blend_weight, 0)} sub="fit walk-forward" />
        <Stat label="Mode" value="PAPER" sub="no wagers placed" />
      </div>
      {!o.validation.validated && (
        <div className="mt-4 flex gap-2 rounded border border-down/40 bg-down-dim/30 p-3 text-[12.5px] leading-relaxed text-ink">
          <ShieldAlert size={16} className="mt-0.5 shrink-0 text-down" />
          <div><b className="text-down">Recommendation claims disabled.</b> {o.validation.reason}</div>
        </div>
      )}
      <details className="mt-3 text-[12px] text-mute">
        <summary className="cursor-pointer select-none text-mute hover:text-ink">Market coverage and known gaps ({o.missing_coverage.length})</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">{o.missing_coverage.map((m) => <li key={m}>{m}</li>)}</ul>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] text-[12px]">
            <thead className="text-left text-faint"><tr><th className="py-1">Game</th><th>Tip</th><th>Spread (home)</th><th>Total</th><th>Main props</th><th>Alt lines</th><th>Players</th><th>Books</th></tr></thead>
            <tbody className="num">{o.coverage.map((g) => (
              <tr key={g.game_id} className="border-t border-line/60">
                <td className="py-1 font-sans text-ink">{g.matchup}</td><td>{time(g.start)}</td><td>{num(g.spread_home)}</td><td>{num(g.total)}</td>
                <td className={g.evaluated && !g.main_props ? "text-down" : ""}>{g.evaluated ? g.main_props : "started"}</td><td>{g.alt_props}</td><td>{g.players}</td><td className="font-sans">{g.books.join(", ")}</td>
              </tr>))}</tbody>
          </table>
        </div>
        {Object.keys(o.rejection_counts).length > 0 && (
          <div className="mt-3">Most common exclusion reasons: {Object.entries(o.rejection_counts).slice(0, 8).map(([k, v]) => `${k} (${v})`).join(" · ")}</div>
        )}
      </details>
    </Card>
  );
}

function statusBadge(status: string): { tone: "good" | "warn" | "mute"; label: string } {
  if (status === "qualified") return { tone: "good", label: "QUALIFIED" };
  if (status === "research_only") return { tone: "warn", label: "RESEARCH ONLY · +EV, UNVALIDATED" };
  return { tone: "mute", label: "WATCHLIST · NOT A PICK" };
}

function TopThree({ o, cands }: { o: Overview; cands: Candidate[] }) {
  const nWatch = cands.filter((c) => c.status === "watchlist").length;
  const nResearch = cands.filter((c) => c.status === "research_only").length;
  return (
    <div className="space-y-3">
      {o.headline && (
        <div className="rounded-lg border border-warn/50 bg-warn-dim/30 px-5 py-4">
          <div className="text-base font-semibold tracking-wide text-warn">{o.headline}</div>
          <div className="mt-1 space-y-1 text-[12.5px] text-mute">
            <p>Avoiding all wagers today is the rational conclusion under this system&apos;s rules.</p>
            {nResearch > 0 && <p>{nResearch} slot(s) hold props with positive EV against the other books&apos; consensus price. That signal has not been validated historically (no free multi-book history exists), so they are research only.</p>}
            {nWatch > 0 && <p>{nWatch} slot(s) hold the research watchlist: props that pass every data, availability, stability and stress check but fail a market check (negative EV, or only one other book to compare against). Each card says which. They show what is closest to playable, not what to play.</p>}
          </div>
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-3">
        {[0, 1, 2].map((i) => {
          const c = cands[i];
          if (!c) return (
            <div key={i} className="flex min-h-[220px] items-center justify-center rounded-lg border border-dashed border-line-2 p-4 text-center text-[12.5px] text-mute">
              Slot {i + 1} empty: no{i > 0 ? " further" : ""} prop passed every hard filter and stress test with positive conservative EV.
            </div>
          );
          return <CandidateCard key={i} c={c} />;
        })}
      </div>
    </div>
  );
}

function CandidateCard({ c }: { c: Candidate }) {
  const l20 = c.history?.windows?.L20;
  const evLoss = -1;
  return (
    <div className={`rounded-lg border bg-panel p-4 ${c.status === "qualified" ? "border-up/40" : c.status === "watchlist" ? "border-dashed border-line-2" : "border-warn/40"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] text-faint">#{c.rank} · {c.matchup} · {time(c.game_start)}</div>
          <div className="truncate text-[15px] font-medium">{c.athlete_name} <span className="text-mute">({c.team} vs {c.opp})</span></div>
          <div className="mt-0.5 text-[14px]">
            <span className="uppercase">{c.side}</span> <span className="num">{c.line}</span> {c.market_label}
            <span className="num ml-2 text-mute">{am(c.american)} · {c.book}</span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge tone={statusBadge(c.status).tone}>{statusBadge(c.status).label}</Badge>
          <Badge tone={riskTone(c.risk)}>{c.risk} risk</Badge>
        </div>
      </div>
      {c.status === "watchlist" && (c.watchlist_reasons?.length ?? 0) > 0 && (
        <div className="mt-2 rounded border border-line-2 bg-panel-2 px-2.5 py-1.5 text-[11.5px] leading-snug text-mute">
          Not a pick: {c.watchlist_reasons!.join(" ")}
        </div>
      )}
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Stat label="Estimate" value={pct(c.p_final)} sub={c.blend_weight === 0 ? "market-based" : `±${pct(c.p_sd)} sd`} />
        <Stat label="Conservative" value={pct(c.p_conservative)} sub="lower bound used" />
        <Stat label="Break-even" value={pct(c.break_even)} sub={`market ${pct(c.p_market_novig)}`} />
      </div>
      <div className="mt-3">
        <KV k="Model projection" v={`${num(c.projection_mean)} on ${num(c.minutes_proj)} min`} />
        <KV k="EV per unit (point / conservative)" v={`${signed(c.ev)} / ${signed(c.ev_conservative)}`} tone={(c.ev_conservative ?? 0) > 0 ? "good" : "bad"} />
        <KV k="Potential loss per unit" v={`${evLoss.toFixed(2)} (if it misses)`} tone="bad" />
        <KV k="Historical hit rate, last 20" v={l20 ? `${l20.hits}/${l20.n} (${pct(l20.hit_rate_vs_line, 0)})` : "n/a"} />
        <KV k="Market reference" v={c.market_basis ?? "n/a"} />
        <KV k="Odds data" v={`${ago(c.retrieved_at)} · ${c.side_verification}`} />
      </div>
      {c.shared_risk?.length > 0 && <div className="mt-2 text-[11px] text-warn">Shares a game with: {c.shared_risk.join(", ")}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-faint">{title}</h3>
      <div className="text-[12.5px] leading-relaxed text-ink">{children}</div>
    </div>
  );
}

function Breakdown({ c }: { c: Candidate }) {
  const [open, setOpen] = useState(c.rank === 1);
  const h = c.history;
  const d = c.diagnostics as Record<string, number | number[] | string | object[] | null>;
  const ctx = c.context;
  const ex = c.explanation;
  const windows = ["L5", "L10", "L15", "L20", "L30"].filter((k) => h.windows[k]);
  return (
    <Card title={
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 text-left">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        #{c.rank} {c.athlete_name} · {c.side.toUpperCase()} {c.line} {c.market_label} · {am(c.american)} {c.book}
      </button>} right={<Badge tone={statusBadge(c.status).tone}>{statusBadge(c.status).label}</Badge>}>
      {!open ? <div className="text-[12px] text-mute">{ex.thesis}</div> : (
        <div className="space-y-5">
          <Section title="Research thesis">
            <p>{ex.thesis}</p>
            <p className="mt-1 text-[11px] text-faint">Generated by: {ex.generator}. Every figure comes from the model payload.</p>
          </Section>

          <div className="grid gap-5 lg:grid-cols-2">
            <Section title="Historical evidence (observations, not forecasts)">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-[12px]">
                  <thead className="text-left text-faint"><tr><th>Window</th><th>Mean</th><th>Median</th><th>SD</th><th>IQR</th><th>Min/Max</th><th>Over {c.line}</th></tr></thead>
                  <tbody className="num">{windows.map((k) => {
                    const w = h.windows[k];
                    return <tr key={k} className="border-t border-line/60"><td className="py-1">{k}</td><td>{w.mean}</td><td>{w.median}</td><td>{w.sd}</td><td>{w.iqr[0]}-{w.iqr[1]}</td><td>{w.min}/{w.max}</td><td>{w.hits}/{w.n}</td></tr>;
                  })}</tbody>
                </table>
              </div>
              {h.current_season && <p className="mt-2 text-[12px] text-mute">This season: n={h.current_season.n}, mean {h.current_season.mean} (95% CI {h.current_season.ci95_mean[0]} to {h.current_season.ci95_mean[1]}), skew {h.current_season.skew}, over-line rate {pct(h.current_season.hit_rate_vs_line, 0)}.
                {h.previous_season && ` Last season: n=${h.previous_season.n}, mean ${h.previous_season.mean}, over-line rate ${pct(h.previous_season.hit_rate_vs_line, 0)}.`}</p>}
              <p className="mt-1 text-[11px] text-faint">A high past hit rate is not tonight&apos;s probability: the model shrinks recent form toward longer-run rates.</p>
            </Section>
            <Section title="Probability and market">
              <KV k="Model M1 (minutes × rate, NB)" v={pct(c.p_model)} />
              <KV k="Model M2 (empirical, minutes-scaled)" v={pct(c.p_empirical)} />
              <KV k="Model disagreement" v={num(c.model_disagreement, 3)} tone={(c.model_disagreement ?? 1) > 0.07 ? "warn" : undefined} />
              <KV k={`Blend (${pct(c.blend_weight, 0)} model / rest no-vig market)`} v={pct(c.p_final)} />
              <KV k="10th to 90th pct across parameter draws" v={`${pct(c.p_interval[0])} - ${pct(c.p_interval[1])}`} />
              <KV k="Conservative probability" v={pct(c.p_conservative)} />
              <KV k="Push probability" v={pct(c.p_push)} />
              <KV k="Break-even at offered price" v={pct(c.break_even)} />
              <KV k={`Market reference (${c.market_basis ?? "n/a"})`} v={pct(c.p_market_novig)} />
              <KV k="This book's own no-vig / overround" v={`${pct(c.p_book_novig)} / ${pct(c.overround)}`} />
              <KV k="Raw model before recalibration (sd)" v={`${pct(c.p_model_raw)} (±${pct(c.p_sd_model)})`} />
              <KV k="Estimated fair odds" v={am(c.fair_american)} />
              <KV k="EV per 1 unit (point / conservative)" v={`${signed(c.ev)} / ${signed(c.ev_conservative)}`} tone={(c.ev_conservative ?? 0) > 0 ? "good" : "bad"} />
              <KV k="Max loss per 1 unit staked" v="-1.00" tone="bad" />
            </Section>
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <Section title="Minutes and usage">
              <KV k="Projected minutes" v={num(c.minutes_proj)} />
              <KV k="Minutes after game script" v={num(d.expected_minutes_after_script as number)} />
              <KV k="Minutes SD / CV" v={`${num(d.minutes_sd as number)} / ${num(d.minutes_cv as number, 2)}`} />
              <KV k="Started, last 5" v={pct(d.starter_share_l5 as number, 0)} />
              <KV k="Last 5 minutes" v={(d.minutes_l5 as number[])?.join(", ")} />
              <KV k="Per-minute rate (prior)" v={`${num(d.rate_per_min as number, 3)} (${num(d.prior_rate as number, 3)})`} />
              <KV k="Teammate usage factor" v={num(c.diagnostics.teammate_factor as number ?? 1, 3)} />
            </Section>
            <Section title="Matchup">
              <KV k="Opponent positional factor" v={num(d.opp_factor as number, 3)} tone={(d.opp_factor as number) > 1 === (c.side === "over") ? "good" : "warn"} />
              <KV k="Opp defensive rating (L15)" v={num(ctx.opponent?.def_rating)} />
              <KV k="Opp allows reb / ast per 100" v={`${num(ctx.opponent?.opp_reb_per100)} / ${num(ctx.opponent?.opp_ast_per100)}`} />
              <KV k="Opp allows 3PA / 3PM per 100" v={`${num(ctx.opponent?.opp_3pa_per100)} / ${num(ctx.opponent?.opp_3pm_per100)}`} />
              <KV k="Opp forces TOV per 100" v={num(ctx.opponent?.forced_tov_per100)} />
              <KV k="Pace team / opp / expected" v={`${num(ctx.team_pace)} / ${num(ctx.opp_pace)} / ${num(ctx.expected_possessions)}`} />
              <KV k="Vs this opponent (n)" v={h.vs_opponent.n ? `${h.vs_opponent.mean} avg (${h.vs_opponent.n})` : "none"} />
            </Section>
            <Section title="Game environment">
              <KV k="Venue" v={ctx.home ? "Home" : "Away"} />
              <KV k="Spread (team) / total" v={`${num(ctx.spread_for_team)} / ${num(ctx.game_total)}`} />
              <KV k="Implied team total" v={num(ctx.implied_team_total)} />
              <KV k="Back-to-back" v={ctx.back_to_back ? "yes" : "no"} tone={ctx.back_to_back ? "warn" : undefined} />
              <KV k="P(20+ point margin)" v={pct(d.p_blowout_20 as number)} />
              <KV k="P(overtime)" v={pct(d.p_overtime as number)} />
              <KV k="Home / away (this season)" v={`${num(h.home_away.home?.mean)} / ${num(h.home_away.away?.mean)}`} />
            </Section>
          </div>

          <Section title="Injury and lineup">
            <div className="grid gap-3 md:grid-cols-2">
              {([["Team", ctx.team_injuries], ["Opponent", ctx.opp_injuries]] as const).map(([k, list]) => (
                <div key={k}>
                  <div className="text-[11px] text-faint">{k} report</div>
                  {list.length === 0 ? <div className="text-mute">No listed injuries.</div> :
                    <ul className="space-y-0.5">{list.map((i) => <li key={i.name}><Badge tone={i.status === "Out" ? "bad" : "warn"}>{i.status}</Badge> {i.name} <span className="text-mute">{i.comment}</span></li>)}</ul>}
                </div>
              ))}
            </div>
            {(d.teammate_adjustments as object[])?.length > 0 && <p className="mt-2 text-[12px] text-mute">With/without adjustments: {JSON.stringify(d.teammate_adjustments)}</p>}
            <p className="mt-1 text-[11px] text-faint">Confirmed starting lineups are not available from the connected sources; role is inferred from recent starts.</p>
          </Section>

          <Section title="Market analysis">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[12px]">
                <thead className="text-left text-faint"><tr><th>Book</th><th>Kind</th><th>Line</th><th>Side</th><th>Price</th><th>Open</th><th>Break-even</th><th>No-vig</th><th>Model</th><th>EV</th></tr></thead>
                <tbody className="num">{c.market_compare.filter((m) => m.side === c.side || m.kind === "main").sort((a, b) => a.line - b.line).map((m, i) => (
                  <tr key={i} className={`border-t border-line/60 ${m.line === c.line && m.side === c.side && m.kind === c.kind ? "bg-panel-2" : ""}`}>
                    <td className="py-1 font-sans">{m.book}</td><td className="font-sans">{m.kind}</td><td>{m.line}</td><td className="font-sans">{m.side}</td><td>{am(m.american)}</td>
                    <td>{m.open_line ?? "?"} @ {am(m.open_american)}</td><td>{pct(m.break_even)}</td><td>{pct(m.p_market_novig)}</td><td>{pct(m.p_final)}</td>
                    <td className={(m.ev ?? 0) > 0 ? "text-up" : "text-down"}>{signed(m.ev)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
            <p className="mt-1 text-[11px] text-faint">Alternate lines trade a higher hit probability for a lower payout; EV compares both on the same footing. Line movement is shown as data only; it is not read as sharp or public money.</p>
          </Section>

          <div className="grid gap-5 lg:grid-cols-2">
            <Section title="Strongest arguments against">
              <ul className="list-disc space-y-1 pl-5">{ex.contradicting.map((x) => <li key={x}>{x}</li>)}</ul>
            </Section>
            <Section title="Supporting evidence">
              <ul className="list-disc space-y-1 pl-5">{ex.supporting.map((x) => <li key={x}>{x}</li>)}</ul>
            </Section>
          </div>

          <Section title="Sensitivity analysis (stress tests)">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-[12px]">
                <thead className="text-left text-faint"><tr><th>Scenario</th><th>Probability</th><th>Change</th><th>EV at offered price</th><th>vs break-even</th></tr></thead>
                <tbody className="num">{c.stress.scenarios.map((s) => (
                  <tr key={s.code} className="border-t border-line/60">
                    <td className="py-1 font-sans">{s.label}</td><td>{pct(s.p)}</td>
                    <td className={s.delta < -0.05 ? "text-down" : s.delta < -0.02 ? "text-warn" : ""}>{signed(s.delta * 100, 1)} pts</td>
                    <td className={s.ev > 0 ? "text-up" : "text-down"}>{signed(s.ev)}</td>
                    <td className="font-sans">{s.p >= (c.break_even ?? 1) ? "above" : <span className="text-down">below</span>}</td>
                  </tr>))}</tbody>
              </table>
            </div>
            <p className="mt-1 text-[12px] text-mute">Most influential assumptions: {c.stress.most_sensitive.join(", ")}. Worst single-scenario probability {pct(c.stress.worst_p)}.</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[12px] text-mute">{ex.invalidators.map((x) => <li key={x}>Invalidated if: {x}</li>)}</ul>
          </Section>

          <Section title={`Historical performance charts (last ${h.games.length} games)`}>
            <GameBars games={h.games} line={c.line} label={c.market_label} />
            <div className="mt-3 grid gap-4 lg:grid-cols-3">
              <div><div className="text-[11px] text-faint">Minutes played</div><MinutesChart games={h.games} projected={c.minutes_proj ?? 0} /></div>
              <div><div className="text-[11px] text-faint">Usage proxy: (FGA + 0.44·FTA + TOV) per 36 min</div><UsageChart games={h.games} /></div>
              <div><div className="text-[11px] text-faint">Predictive vs observed distribution</div><DistributionChart pmf={c.distribution.pmf} games={h.games} line={c.line} side={c.side} /></div>
            </div>
            <p className="mt-1 text-[11px] text-faint">Model 80% interval for the outcome: {c.distribution.p10} to {c.distribution.p90}, median {c.distribution.median}.</p>
          </Section>

          <Section title="Risk flags">
            {c.reasons.length === 0 ? <span className="text-mute">No caution flags.</span> :
              <ul className="space-y-1">{c.reasons.map((f) => (
                <li key={f.code} className="flex gap-2"><TriangleAlert size={13} className={f.severity === "caution" ? "mt-0.5 text-warn" : "mt-0.5 text-down"} />{f.text}</li>))}</ul>}
          </Section>

          <Section title="Sources">
            <ul className="space-y-0.5">{c.sources.map((s) => (
              <li key={s.label}><a className="text-series1 underline-offset-2 hover:underline" href={s.url} target="_blank" rel="noreferrer">{s.label}</a>
                <span className="ml-2 text-[11px] text-faint">{s.retrieved_at ? `retrieved ${dateTime(s.retrieved_at)}` : "reproducible from stored box scores"}</span></li>))}</ul>
          </Section>
        </div>
      )}
    </Card>
  );
}
