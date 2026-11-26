"use client";
import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";
import { Badge, Card, Empty, Stat } from "@/components/ui";
import { CalibrationChart, EquityChart } from "@/components/charts";
import { am, dateTime, pct } from "@/lib/fmt";

interface TRow {
  id: number; date: string; player: string; team: string; opp: string; market: string; side: string; line: number; book: string;
  american: number; p_model: number; p_conservative: number; status: string; model_version: string; created_at: string;
  invalidated_at: string | null; invalidation_reason: string | null; closing_line: number | null; closing_american: number | null;
  clv_implied: number | null; actual: number | null; result: string | null; paper_profit: number | null;
}
interface Tracker {
  rows: TRow[]; n: number; settled: number; wins: number; units: number; max_drawdown: number;
  equity: { date: string; units: number }[]; calibration: { bin: string; n: number; predicted: number; observed: number }[];
  rolling: { n: number; rolling_hit_rate_20: number }[]; note: string;
  by_status?: Record<string, { settled: number; wins: number; units: number }>;
}

export default function TrackerPage() {
  const [t, setT] = useState<Tracker | null>(null);
  useEffect(() => { getJSON<Tracker>("/api/tracker").then(setT).catch(() => setT(null)); }, []);
  if (!t) return <Empty>Loading…</Empty>;
  return (
    <div className="space-y-4">
      <Card title="Historical prediction tracker (paper)" right={<span className="text-[11px] text-faint">{t.note}</span>}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-6">
          <Stat label="Published" value={t.n} />
          <Stat label="Settled (W/L)" value={t.settled} />
          <Stat label="Hit rate" value={t.settled ? pct(t.wins / t.settled) : "n/a"} />
          <Stat label="Paper units" value={t.units.toFixed(2)} tone={t.units >= 0 ? "good" : "bad"} />
          <Stat label="Max drawdown" value={t.max_drawdown.toFixed(2)} tone="bad" />
          <Stat label="Rolling 20 hit rate" value={t.rolling.length ? pct(t.rolling[t.rolling.length - 1].rolling_hit_rate_20) : "n/a"} />
        </div>
        {t.by_status && (
          <table className="mt-4 text-[12px]">
            <thead className="text-left text-faint"><tr><th className="pr-6">Status</th><th className="pr-6">Settled</th><th className="pr-6">Hit rate</th><th>Paper units</th></tr></thead>
            <tbody className="num">{Object.entries(t.by_status).map(([k, v]) => (
              <tr key={k} className="border-t border-line/60"><td className="py-0.5 pr-6 font-sans">{k.replace("_", " ")}</td><td>{v.settled}</td>
                <td>{v.settled ? pct(v.wins / v.settled) : "n/a"}</td><td className={v.units >= 0 ? "text-up" : "text-down"}>{v.units.toFixed(2)}</td></tr>))}</tbody>
          </table>
        )}
        <p className="mt-2 text-[11px] text-faint">Watchlist entries are tracked separately: they were never recommendations, so they must not flatter or drag the pick record.</p>
        {t.settled < 30 && <p className="mt-3 text-[12px] text-warn">Fewer than 30 settled predictions: these numbers are dominated by noise and say little about the method.</p>}
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Cumulative paper performance (units)">{t.equity.length ? <EquityChart data={t.equity} /> : <Empty>Nothing settled yet.</Empty>}</Card>
        <Card title="Live calibration (predicted vs observed)">
          {t.calibration.length ? <CalibrationChart series={[{ name: "Published predictions", color: "#3987e5", points: t.calibration.map((c) => ({ pred: c.predicted, obs: c.observed, n: c.n })) }]} /> : <Empty>Nothing settled yet.</Empty>}
        </Card>
      </div>
      <Card title="All published predictions (immutable; outcomes appended after the game)">
        {!t.rows.length ? <Empty>No predictions published yet.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-[12px]">
              <thead className="text-left text-faint"><tr><th className="py-1.5">Date</th><th>Player</th><th>Prop</th><th>Line</th><th>Odds</th><th>Book</th><th>Est.</th><th>Cons.</th><th>Status</th><th>Model</th><th>Published</th><th>Closing</th><th>CLV (implied)</th><th>Actual</th><th>Result</th><th>Paper P/L</th></tr></thead>
              <tbody className="num">{t.rows.map((r) => (
                <tr key={r.id} className="border-t border-line/60">
                  <td className="py-1">{r.date}</td><td className="font-sans">{r.player} <span className="text-faint">{r.team} v {r.opp}</span></td>
                  <td className="font-sans">{r.side} {r.market}</td><td>{r.line}</td><td>{am(r.american)}</td><td className="font-sans">{r.book}</td>
                  <td>{pct(r.p_model)}</td><td>{pct(r.p_conservative)}</td>
                  <td className="font-sans">{r.status === "qualified" ? <Badge tone="good">qualified</Badge> : r.status === "watchlist" ? <Badge>watchlist</Badge> : r.status === "high_probability" ? <Badge>high probability</Badge> : <Badge tone="warn">research only</Badge>}
                    {r.invalidated_at && <span title={r.invalidation_reason ?? ""}><Badge tone="bad">invalidated</Badge></span>}</td>
                  <td className="text-faint">{r.model_version}</td><td className="text-mute">{dateTime(r.created_at)}</td>
                  <td>{r.closing_line != null ? `${r.closing_line} @ ${am(r.closing_american)}` : "n/a"}</td>
                  <td>{r.clv_implied != null ? pct(r.clv_implied) : "n/a"}</td>
                  <td>{r.actual ?? "n/a"}</td>
                  <td className={r.result === "win" ? "text-up" : r.result === "loss" ? "text-down" : "text-mute"}>{r.result ?? "pending"}</td>
                  <td className={(r.paper_profit ?? 0) >= 0 ? "text-up" : "text-down"}>{r.paper_profit?.toFixed(2) ?? "n/a"}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-[11px] text-faint">Invalidated predictions stay in the record and are still settled: hiding them would bias the track record.</p>
      </Card>
    </div>
  );
}
