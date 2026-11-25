"use client";
import { useMemo, useState } from "react";
import { useSlate } from "@/components/use-slate";
import { Badge, Card, Empty } from "@/components/ui";
import { ago, am, minutesSince, pct } from "@/lib/fmt";
import type { SlateRow } from "@/lib/types";

export default function Markets() {
  const { data } = useSlate();
  const [q, setQ] = useState("");
  const [market, setMarket] = useState("Points");
  const rows = data?.slate ?? [];
  const books = useMemo(() => Array.from(new Set(rows.map((r) => r.book))).sort(), [rows]);
  const markets = useMemo(() => Array.from(new Set(rows.map((r) => r.market_label))).sort(), [rows]);
  const groups = useMemo(() => {
    const g = new Map<string, { player: string; matchup: string; rows: SlateRow[] }>();
    for (const r of rows) {
      if (r.kind !== "main" || r.market_label !== market) continue;
      if (q && !r.athlete_name.toLowerCase().includes(q.toLowerCase())) continue;
      const k = `${r.athlete_id}`;
      if (!g.has(k)) g.set(k, { player: r.athlete_name, matchup: r.matchup, rows: [] });
      g.get(k)!.rows.push(r);
    }
    return Array.from(g.values()).sort((a, b) => a.matchup.localeCompare(b.matchup) || a.player.localeCompare(b.player));
  }, [rows, q, market]);
  if (!data) return <Empty>Loading…</Empty>;
  if (!rows.length) return <Empty>No market data yet.</Empty>;
  return (
    <Card title="Market comparison · main lines by book" right={<span className="text-[11px] text-faint">{books.length} book(s): {books.join(", ")}</span>}>
      <div className="mb-3 flex flex-wrap gap-2">
        <input className="w-44 rounded border border-line-2 bg-panel-2 px-2 py-1 text-[12px]" placeholder="Search player" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="rounded border border-line-2 bg-panel-2 px-2 py-1 text-[12px]" value={market} onChange={(e) => setMarket(e.target.value)}>
          {markets.map((m) => <option key={m}>{m}</option>)}
        </select>
        {books.length < 2 && <Badge tone="warn">Single book: cross-book consensus and best-price comparison need an ODDS_API_KEY</Badge>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-[12px]">
          <thead className="text-left text-faint">
            <tr><th className="py-1.5">Player</th><th>Game</th>
              {books.map((b) => <th key={b}>{b} line · over / under</th>)}
              <th>Consensus no-vig over</th><th>Best over</th><th>Best under</th><th>Open → current</th><th>Quote age</th></tr>
          </thead>
          <tbody className="num">
            {groups.map((g) => {
              const byBook = (b: string, side: string) => g.rows.find((r) => r.book === b && r.side === side);
              const overs = g.rows.filter((r) => r.side === "over");
              const unders = g.rows.filter((r) => r.side === "under");
              const lines = new Set(g.rows.map((r) => r.line));
              const nv = overs.map((r) => r.p_market_novig).filter((x): x is number => x != null);
              const bestO = overs.slice().sort((a, b) => b.american - a.american)[0];
              const bestU = unders.slice().sort((a, b) => b.american - a.american)[0];
              const o = overs[0];
              const age = Math.max(...g.rows.map((r) => minutesSince(r.retrieved_at)));
              return (
                <tr key={g.player} className="border-t border-line/60">
                  <td className="py-1 font-sans">{g.player}</td><td className="font-sans text-mute">{g.matchup}</td>
                  {books.map((b) => {
                    const ov = byBook(b, "over"), un = byBook(b, "under");
                    return <td key={b}>{ov ? <>{ov.line} · {am(ov.american)} / {am(un?.american)}</> : <span className="text-faint">missing</span>}</td>;
                  })}
                  <td>{nv.length ? pct(nv.reduce((a, b) => a + b, 0) / nv.length) : "n/a"}{lines.size > 1 && <Badge tone="warn">lines differ</Badge>}</td>
                  <td>{bestO ? `${bestO.line} ${am(bestO.american)} ${bestO.book}` : "n/a"}</td>
                  <td>{bestU ? `${bestU.line} ${am(bestU.american)} ${bestU.book}` : "n/a"}</td>
                  <td>{o?.open_line != null ? `${o.open_line} @ ${am(o.open_american)} → ${o.line} @ ${am(o.american)}` : "n/a"}</td>
                  <td className={age > 45 ? "text-down" : "text-mute"}>{ago(g.rows[0]?.retrieved_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-faint">Lines at different thresholds are not treated as equivalent; differing thresholds are flagged instead of averaged. Movement is shown as data only.</p>
    </Card>
  );
}
