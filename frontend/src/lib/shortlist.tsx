// The logged-in user's shortlist: which players are starred, shared by every page.
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { useAuth } from "./auth";

interface ShortlistState {
  ids: Set<number>;
  ready: boolean;
  has: (id: number) => boolean;
  toggle: (id: number) => Promise<void>;
  refresh: () => Promise<void>;
  error: string | null;
  clearError: () => void;
}
const Ctx = createContext<ShortlistState | null>(null);

export function ShortlistProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [ids, setIds] = useState<Set<number>>(new Set());
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!user) { setIds(new Set()); setReady(false); return; }
    try { setIds(new Set((await api.shortlist()).map((x) => x.player_id))); setReady(true); }
    catch { setReady(true); }
  }, [user]);

  useEffect(() => { refresh(); }, [refresh]);

  const clearError = useCallback(() => setError(null), []);

  const toggle = useCallback(async (id: number) => {
    const on = ids.has(id);
    setError(null);
    setIds((cur) => { const n = new Set(cur); if (on) n.delete(id); else n.add(id); return n; });  // show it at once
    try {
      if (on) await api.shortlistRemove(id); else await api.shortlistAdd(id);
    } catch (e) {
      setIds((cur) => { const n = new Set(cur); if (on) n.add(id); else n.delete(id); return n; });  // undo
      setError(e instanceof ApiError ? e.message : "The shortlist could not be changed.");
    }
  }, [ids]);

  return (
    <Ctx.Provider value={{ ids, ready, has: (id) => ids.has(id), toggle, refresh, error, clearError }}>
      {children}
    </Ctx.Provider>
  );
}

export function useShortlist(): ShortlistState {
  const c = useContext(Ctx);
  if (!c) throw new Error("useShortlist outside ShortlistProvider");
  return c;
}
