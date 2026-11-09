// Remembers the previous page in the app, so "back" buttons can say where they go.
import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

let previous: { pathname: string; search: string } | null = null;

/** Call once in the layout: records the page the person was on before the current one. */
export function useTrackPrevious(): void {
  const location = useLocation();
  const current = useRef<{ pathname: string; search: string } | null>(null);
  useEffect(() => {
    const here = { pathname: location.pathname, search: location.search };
    if (current.current && current.current.pathname !== here.pathname) previous = current.current;
    current.current = here;
  }, [location.pathname, location.search]);
}

export function previousPage() { return previous; }

/** A readable name for a page, for "Back to …". */
export function pageName(pathname: string): string {
  if (pathname === "/") return "dashboard";
  if (pathname === "/players") return "players";
  if (/^\/players\/\d+$/.test(pathname)) return "previous player";
  if (pathname.startsWith("/builder")) return "squad builder";
  if (pathname.startsWith("/improve")) return "Improve my club";
  if (pathname.startsWith("/compare")) return "comparison";
  if (pathname === "/scenarios") return "saved scenarios";
  if (/^\/scenarios\/\d+$/.test(pathname)) return "scenario";
  return "previous page";
}

/** Where a back button goes: the previous page in the app if there is one, otherwise the fallback. */
export function backTarget(fallback: string, fallbackName: string): { to: string | -1; label: string } {
  const p = previous;
  if (p && window.history.state && typeof window.history.state.idx === "number" && window.history.state.idx > 0) {
    return { to: -1, label: `Back to ${pageName(p.pathname)}` };
  }
  return { to: fallback, label: `Back to ${fallbackName}` };
}
