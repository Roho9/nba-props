"use client";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import type { GameRow } from "@/lib/types";

const AXIS = { stroke: "#2a2f37", tick: { fill: "#8b929c", fontSize: 11 }, tickLine: false } as const;
const GRID = { stroke: "#1e2228", vertical: false } as const;
const UP = "#10b981";
const DOWN = "#ef4444";
const S1 = "#3987e5";
const S2 = "#d95926";
const INK = "#e7e9ec";

function TipBox({ children }: { children: React.ReactNode }) {
  return <div className="rounded border border-line-2 bg-panel-2 px-2.5 py-2 text-[12px] leading-5 text-ink shadow-lg">{children}</div>;
}

export function GameBars({ games, line, label }: { games: GameRow[]; line: number; label: string }) {
  const data = games.map((g, i) => {
    const w = games.slice(Math.max(0, i - 4), i + 1).map((x) => x.value ?? 0);
    return { ...g, idx: i, l5: w.reduce((a, b) => a + b, 0) / w.length, tick: g.date.slice(5) };
  });
  return (
    <div>
      <div className="mb-1 flex flex-wrap gap-3 text-[11px] text-mute">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: UP }} />Over the line (hit for over)</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: DOWN }} />At/under the line</span>
        <span><i className="mr-1 inline-block h-0.5 w-3 align-middle" style={{ background: S1 }} />5-game rolling average</span>
        <span><i className="mr-1 inline-block h-0 w-3 border-t border-dashed align-middle" style={{ borderColor: INK }} />Today&apos;s line {line}</span>
      </div>
      <ResponsiveContainer width="100%" height={230}>
        <ComposedChart data={data} barCategoryGap={2} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="tick" {...AXIS} interval="preserveStartEnd" minTickGap={18} />
          <YAxis {...AXIS} allowDecimals={false} />
          <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const g = payload[0].payload as GameRow & { l5: number };
            return (
              <TipBox>
                <div className="font-medium">{g.date} {g.home ? "vs" : "@"} {g.opp}</div>
                <div>{label}: <b className="num">{g.value}</b> ({g.hit ? "over" : "not over"} {line})</div>
                <div className="text-mute">Minutes {g.minutes} · {g.starter ? "started" : "bench"}</div>
                <div className="num text-mute">PTS {g.pts} · REB {g.reb} · AST {g.ast} · 3PM {g.fg3m}</div>
                <div className="num text-mute">STL {g.stl} · BLK {g.blk} · TOV {g.tov}</div>
              </TipBox>
            );
          }} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.idx} fill={d.hit ? UP : DOWN} fillOpacity={0.85} />)}
          </Bar>
          <Line dataKey="l5" stroke={S1} strokeWidth={2} dot={false} isAnimationActive={false} />
          <ReferenceLine y={line} stroke={INK} strokeDasharray="4 3" strokeWidth={1.25} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MinutesChart({ games, projected }: { games: GameRow[]; projected: number }) {
  const data = games.map((g) => ({ ...g, tick: g.date.slice(5) }));
  return (
    <ResponsiveContainer width="100%" height={150}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="tick" {...AXIS} interval="preserveStartEnd" minTickGap={18} />
        <YAxis {...AXIS} domain={[0, 48]} />
        <Tooltip content={({ active, payload }) => active && payload?.length ? (
          <TipBox>{(payload[0].payload as GameRow).date}: <b className="num">{(payload[0].payload as GameRow).minutes}</b> min</TipBox>) : null} />
        <Line dataKey="minutes" stroke={S1} strokeWidth={2} dot={{ r: 2.5, fill: S1, strokeWidth: 0 }} isAnimationActive={false} />
        <ReferenceLine y={projected} stroke={INK} strokeDasharray="4 3" label={{ value: `projected ${projected}`, fill: "#8b929c", fontSize: 10, position: "insideBottomRight" }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function UsageChart({ games }: { games: GameRow[] }) {
  const data = games.map((g) => ({ ...g, tick: g.date.slice(5) }));
  return (
    <ResponsiveContainer width="100%" height={150}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="tick" {...AXIS} interval="preserveStartEnd" minTickGap={18} />
        <YAxis {...AXIS} />
        <Tooltip content={({ active, payload }) => active && payload?.length ? (
          <TipBox>{(payload[0].payload as GameRow).date}: <b className="num">{(payload[0].payload as GameRow).usage_proxy}</b> usage events / 36 min</TipBox>) : null} />
        <Line dataKey="usage_proxy" stroke={S2} strokeWidth={2} dot={{ r: 2.5, fill: S2, strokeWidth: 0 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function DistributionChart({ pmf, games, line, side }: { pmf: number[]; games: GameRow[]; line: number; side: string }) {
  const vals = games.map((g) => g.value ?? 0);
  const maxX = Math.max(pmf.length - 1, ...vals);
  const data = Array.from({ length: maxX + 1 }, (_, x) => ({
    x, model: pmf[x] ?? 0, hist: vals.length ? vals.filter((v) => v === x).length / vals.length : 0,
    win: side === "over" ? x > line : x < line,
  }));
  return (
    <div>
      <div className="mb-1 flex flex-wrap gap-3 text-[11px] text-mute">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: S1 }} />Model predictive distribution (tonight)</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: S2 }} />Observed, last {vals.length} games</span>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} barGap={2} barCategoryGap={1} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="x" {...AXIS} interval="preserveStartEnd" minTickGap={10} />
          <YAxis {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
          <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload as (typeof data)[number];
            return (
              <TipBox>
                <div className="font-medium">Value {d.x} ({d.win ? `wins the ${side}` : `loses the ${side}`})</div>
                <div>Model: <span className="num">{(d.model * 100).toFixed(1)}%</span></div>
                <div>Observed: <span className="num">{(d.hist * 100).toFixed(1)}%</span></div>
              </TipBox>
            );
          }} />
          <Bar dataKey="model" fill={S1} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="hist" fill={S2} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          <ReferenceLine x={Math.floor(line)} stroke={INK} strokeDasharray="4 3" label={{ value: `line ${line}`, fill: "#8b929c", fontSize: 10, position: "top" }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EquityChart({ data, height = 220 }: { data: { date: string; units: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => String(d).slice(5)} minTickGap={24} />
        <YAxis {...AXIS} />
        <ReferenceLine y={0} stroke="#5b626c" />
        <Tooltip content={({ active, payload }) => active && payload?.length ? (
          <TipBox>{(payload[0].payload as { date: string }).date}: <b className="num">{(payload[0].payload as { units: number }).units.toFixed(2)}</b> units</TipBox>) : null} />
        <Line dataKey="units" stroke={S1} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function CalibrationChart({ series }: { series: { name: string; color: string; points: { pred: number; obs: number; n: number }[] }[] }) {
  return (
    <div>
      <div className="mb-1 flex flex-wrap gap-3 text-[11px] text-mute">
        {series.map((s) => <span key={s.name}><i className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: s.color }} />{s.name}</span>)}
        <span><i className="mr-1 inline-block h-0 w-3 border-t border-dashed align-middle" style={{ borderColor: "#5b626c" }} />Perfect calibration</span>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart margin={{ top: 8, right: 12, left: -10, bottom: 4 }}>
          <CartesianGrid stroke="#1e2228" />
          <XAxis type="number" dataKey="pred" domain={[0, 1]} {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}`} name="Predicted" />
          <YAxis type="number" dataKey="obs" domain={[0, 1]} {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}`} name="Observed" />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#5b626c" strokeDasharray="4 3" />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const p = payload[0].payload as { pred: number; obs: number; n: number };
            return <TipBox>Predicted {(p.pred * 100).toFixed(1)}% · observed {(p.obs * 100).toFixed(1)}% · n={p.n}</TipBox>;
          }} />
          {series.map((s) => <Scatter key={s.name} data={s.points} fill={s.color} stroke="#0f1114" strokeWidth={2} isAnimationActive={false} />)}
          <Legend content={() => null} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
