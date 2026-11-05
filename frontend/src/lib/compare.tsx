// Players picked for comparison (up to 4). Kept for this browser tab so a refresh keeps the picks.
import { createContext, ReactNode, useCallback, useContext, useState } from "react";

export interface Pick { id: number; name: string; role: string; }
export const MAX_COMPARE = 4;
const KEY = "scoutiq.compare";

const load = (): Pick[] => { try { return JSON.parse(sessionStorage.getItem(KEY) ?? "[]"); } catch { return []; } };
const save = (p: Pick[]) => { try { sessionStorage.setItem(KEY, JSON.stringify(p)); } catch { /* storage unavailable */ } };

interface CompareState { picks: Pick[]; has: (id: number) => boolean; toggle: (p: Pick) => void; clear: () => void; full: boolean; }
const Ctx = createContext<CompareState | null>(null);

export function CompareProvider({ children }: { children: ReactNode }) {
  const [picks, setPicks] = useState<Pick[]>(load);
  const update = useCallback((fn: (p: Pick[]) => Pick[]) => setPicks((cur) => { const next = fn(cur); save(next); return next; }), []);
  const toggle = useCallback((p: Pick) => update((cur) =>
    cur.some((x) => x.id === p.id) ? cur.filter((x) => x.id !== p.id) : cur.length >= MAX_COMPARE ? cur : [...cur, p]), [update]);
  const clear = useCallback(() => update(() => []), [update]);
  return (
    <Ctx.Provider value={{ picks, has: (id) => picks.some((p) => p.id === id), toggle, clear, full: picks.length >= MAX_COMPARE }}>
      {children}
    </Ctx.Provider>
  );
}

export function useCompare(): CompareState {
  const c = useContext(Ctx);
  if (!c) throw new Error("useCompare outside CompareProvider");
  return c;
}
