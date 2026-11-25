"use client";
import { Fragment, useMemo, useState } from "react";
import { useSlate } from "@/components/use-slate";
import { Badge, Card, Empty, riskTone } from "@/components/ui";
import { am, pct, signed } from "@/lib/fmt";
import type { SlateRow } from "@/lib/types";

type SortKey = "ev_conservative" | "p_final" | "ev" | "athlete_name" | "american";

const sel = "rounded border border-line-2 bg-panel-2 px-2 py-1 text-[12px] text-ink";

export default function SlateExplorer() {
  const { data } = useSlate();
  const rows = data?.slate ?? [];
  const [q, setQ] = useState("");
  const [f, setF] = useState({ team: "", game: "", book: "", market: "", side: "", risk: "", status: "", kind: "", quality: "" });
  const [minP, setMinP] = useState(0);
  const [minEv, setMinEv] = useState(-1);
  const [oddsMin, setOddsMin] = useState(-2000);
  const [oddsMax, setOddsMax] = useState(2000);
  const [sort, setSort] = useState<SortKey>("ev_conservative");
  const [open, setOpen] = useState<number | null>(null);
  const opts = (k: keyof SlateRow) => Array.from(new Set(rows.map((r) => String(r[k] ?? "")))).filter(Boolean).sort();
  const filtered = useMemo(() => {
    const out = rows.filter((r) =>
      (!q || r.athlete_name?.toLowerCase().includes(q.toLowerCase())) &&
      (!f.team || r.team === f.team) && (!f.game || r.matchup === f.game) && (!f.book || r.book === f.book) &&
      (!f.market || r.market_label === f.market) && (!f.side || r.side === f.side) && (!f.risk || r.risk === f.risk) &&
      (!f.status || r.status === f.status) && (!f.kind || r.kind === f.kind) &&
      (!f.quality || r.side_verification === f.quality) &&
      (r.p_final ?? 0) >= minP && (r.ev ?? -9) >= minEv && r.american >= oddsMin && r.american <= oddsMax);
    out.sort((a, b) => {
      const ra = a.status === "rejected" ? 1 : 0, rb = b.status === "rejected" ? 1 : 0;
      if (ra !== rb) return ra - rb; // props still in contention first
      if (sort === "athlete_name") return a.athlete_name.localeCompare(b.athlete_name);
      return ((b[sort] as number) ?? -99) - ((a[sort] as number) ?? -99);
    });
    return out;
  }, [rows, q, f, minP, minEv, oddsMin, oddsMax, sort]);
  if (!data) return <Empty>Loading…</Empty>;
  if (!rows.length) return <Empty>No analyzed props yet. Press Refresh data.</Empty>;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const S = ({ k, label, values }: { k: keyof typeof f; label: string; values: string[] }) => (
    <select className={sel} value={f[k]} onChange={set(k)} aria-label={label}>
      <option value="">{label}: all</option>{values.map((v) => <option key={v} value={v}>{v}</option>)}
    </select>
  );
  return (
    <Card title={`Full slate explorer · ${filtered.length} of ${rows.length} offers`} right={<span className="text-[11px] text-faint">every analyzed quote, both sides</span>}>
      <div className="mb-3 flex flex-wrap gap-2">
        <input className={sel + " w-44"} placeholder="Search player" value={q} onChange={(e) => setQ(e.target.value)} />
        <S k="team" label="Team" values={opts("team")} />
        <S k="game" label="Game" values={opts("matchup")} />
        <S k="book" label="Book" values={opts("book")} />
        <S k="market" label="Prop" values={opts("market_label")} />
        <S k="side" label="Side" values={opts("side")} />
        <S k="kind" label="Line type" values={opts("kind")} />
        <S k="risk" label="Risk" values={opts("risk")} />
        <S k="quality" label="Data quality" values={opts("side_verification")} />
        <S k="status" label="Status" values={opts("status")} />
        <label className="flex items-center gap-1 text-[12px] text-mute">Min prob
          <input type="number" step="0.05" min="0" max="1" className={sel + " w-16"} value={minP} onChange={(e) => setMinP(+e.target.value)} /></label>
        <label className="flex items-center gap-1 text-[12px] text-mute">Min EV
          <input type="number" step="0.01" className={sel + " w-16"} value={minEv} onChange={(e) => setMinEv(+e.target.value)} /></label>
        <label className="flex items-center gap-1 text-[12px] text-mute">Odds
          <input type="number" step="10" className={sel + " w-20"} value={oddsMin} onChange={(e) => setOddsMin(+e.target.value)} />to
          <input type="number" step="10" className={sel + " w-20"} value={oddsMax} onChange={(e) => setOddsMax(+e.target.value)} /></label>
        <select className={sel} value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort">
          <option value="ev_conservative">Sort: conservative EV</option><option value="ev">Sort: EV</option>
          <option value="p_final">Sort: probability</option><option value="american">Sort: odds</option><option value="athlete_name">Sort: player</option>
        </select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-[12px]">
          <thead className="sticky top-0 bg-panel text-left text-faint">
            <tr><th className="py-1.5">Player</th><th>Game</th><th>Prop</th><th>Side</th><th>Line</th><th>Type</th><th>Book</th><th>Odds</th>
              <th>Proj</th><th>Model</th><th>Cons.</th><th>± sd</th><th>Break-even</th><th>No-vig</th><th>EV</th><th>Cons. EV</th><th>Risk</th><th>Status</th></tr>
          </thead>
          <tbody className="num">
            {filtered.slice(0, 600).map((r, i) => {
              const excl = r.reasons?.filter((x) => x.severity === "exclude") ?? [];
              return (
                <Fragment key={i}>
                  <tr className="cursor-pointer border-t border-line/60 hover:bg-panel-2" onClick={() => setOpen(open === i ? null : i)}>
                    <td className="py-1 font-sans text-ink">{r.athlete_name} <span className="text-faint">{r.team}</span></td>
                    <td className="font-sans text-mute">{r.matchup}</td><td className="font-sans">{r.market_label}</td><td className="font-sans">{r.side}</td>
                    <td>{r.line}</td><td className="font-sans text-mute">{r.kind}</td><td className="font-sans text-mute">{r.book}</td><td>{am(r.american)}</td>
                    <td>{r.projection_mean ?? "n/a"}</td><td>{pct(r.p_final)}</td><td>{pct(r.p_conservative)}</td><td>{pct(r.p_sd)}</td>
                    <td>{pct(r.break_even)}</td><td>{pct(r.p_market_novig)}</td>
                    <td className={(r.ev ?? 0) > 0 ? "text-up" : "text-down"}>{signed(r.ev)}</td>
                    <td className={(r.ev_conservative ?? 0) > 0 ? "text-up" : "text-down"}>{signed(r.ev_conservative)}</td>
                    <td className="font-sans"><Badge tone={riskTone(r.risk)}>{r.risk}</Badge></td>
                    <td className="font-sans">{r.status === "rejected" ? <span className="text-mute">rejected · {excl.length}</span> : <span className="text-up">{r.status}</span>}</td>
                  </tr>
                  {open === i && (
                    <tr className="bg-panel-2"><td colSpan={18} className="px-3 py-2 font-sans text-[12px]">
                      {r.reasons?.length ? <ul className="space-y-0.5">{r.reasons.map((x, j) => (
                        <li key={j}><span className={x.severity === "exclude" ? "text-down" : x.severity === "gate" ? "text-warn" : "text-warn"}>[{x.severity}]</span> <b>{x.code}</b>: {x.text}</li>))}</ul> : "No flags."}
                      <div className="mt-1 text-faint">M1 {pct(r.p_model)} · M2 {pct(r.p_empirical)} · disagreement {r.model_disagreement ?? "n/a"} · fair {am(r.fair_american)} · minutes {r.minutes_proj ?? "n/a"} · labels {r.side_verification}</div>
                    </td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {filtered.length > 600 && <div className="mt-2 text-[12px] text-mute">Showing the first 600 rows; narrow the filters to see the rest.</div>}
      </div>
    </Card>
  );
}
