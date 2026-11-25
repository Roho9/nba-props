"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "@/lib/api";
import type { SlateResponse } from "@/lib/types";

export function useSlate() {
  const [data, setData] = useState<SlateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await getJSON<SlateResponse>("/api/slate"));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);
  useEffect(() => {
    load();
    // Poll quickly while a pipeline run is in progress, slowly otherwise.
    let t: ReturnType<typeof setTimeout>;
    const tick = async () => {
      await load();
      t = setTimeout(tick, document.hidden ? 120000 : 15000);
    };
    t = setTimeout(tick, 15000);
    const onStart = () => setTimeout(load, 1500);
    window.addEventListener("slate-refresh-started", onStart);
    return () => {
      clearTimeout(t);
      window.removeEventListener("slate-refresh-started", onStart);
    };
  }, [load]);
  return { data, error, reload: load };
}
