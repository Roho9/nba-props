import { clsx } from "clsx";
import type { ReactNode } from "react";

export function Card({ title, right, children, className }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={clsx("rounded-lg border border-line bg-panel", className)}>
      {title != null && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[13px] font-medium tracking-wide text-ink">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const tones = {
  good: "border-up/40 bg-up-dim/40 text-up",
  warn: "border-warn/40 bg-warn-dim/40 text-warn",
  bad: "border-down/40 bg-down-dim/40 text-down",
  mute: "border-line-2 bg-panel-2 text-mute",
} as const;
export type Tone = keyof typeof tones;

export function Badge({ tone = "mute", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium", tones[tone])}>
      {children}
    </span>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone }) {
  const color = tone === "good" ? "text-up" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-down" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wider text-faint">{label}</div>
      <div className={clsx("num mt-0.5 truncate text-lg", color)}>{value}</div>
      {sub != null && <div className="mt-0.5 truncate text-[11px] text-mute">{sub}</div>}
    </div>
  );
}

export function KV({ k, v, tone }: { k: ReactNode; v: ReactNode; tone?: Tone }) {
  const color = tone === "good" ? "text-up" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-down" : "text-ink";
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 py-1 text-[12px] last:border-0">
      <span className="text-mute">{k}</span>
      <span className={clsx("num text-right", color)}>{v}</span>
    </div>
  );
}

export function riskTone(risk: string): Tone {
  return risk === "Lower" ? "good" : risk === "Moderate" ? "warn" : risk === "Elevated" || risk === "Excluded" ? "bad" : "mute";
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded border border-dashed border-line-2 p-6 text-center text-sm text-mute">{children}</div>;
}
