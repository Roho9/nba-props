"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { postJSON } from "@/lib/api";

const NAV = [
  ["/", "Today"],
  ["/slate", "Slate Explorer"],
  ["/markets", "Market Comparison"],
  ["/tracker", "Prediction Tracker"],
  ["/validation", "Validation"],
  ["/methodology", "Methodology"],
] as const;

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = async () => {
    try {
      const r = await postJSON<{ message: string }>("/api/refresh");
      setMsg(r.message);
      window.dispatchEvent(new Event("slate-refresh-started"));
    } catch (e) {
      setMsg(String(e));
    }
    setTimeout(() => setMsg(null), 6000);
  };
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold tracking-wide">NBA PROP RESEARCH</span>
            <span className="text-[11px] text-faint">paper mode · decision support only</span>
          </div>
          <nav className="flex flex-wrap gap-1">
            {NAV.map(([href, label]) => (
              <Link key={href} href={href}
                className={clsx("rounded px-2.5 py-1 text-[13px]", path === href ? "bg-panel-2 text-ink" : "text-mute hover:text-ink")}>
                {label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {msg && <span className="text-[12px] text-mute">{msg}</span>}
            <button onClick={refresh}
              className="inline-flex items-center gap-1.5 rounded border border-line-2 bg-panel-2 px-2.5 py-1 text-[13px] text-ink hover:border-mute">
              <RefreshCw size={13} /> Refresh data
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1500px] px-4 py-5">{children}</main>
      <footer className="mx-auto max-w-[1500px] px-4 pb-8 text-[11px] leading-relaxed text-faint">
        Estimates are model outputs with stated uncertainty, not guarantees. Historical hit rates are not future probabilities.
        No wagers are placed by this software. If gambling stops being fun, call 1-800-GAMBLER.
      </footer>
    </div>
  );
}
