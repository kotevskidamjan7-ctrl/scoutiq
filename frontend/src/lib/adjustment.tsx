// Whether league-adjusted scores exist, and the "Compare across leagues" switch that uses them.
import { useEffect, useState } from "react";
import { api } from "./api";

export interface AdjustmentStatus { active: boolean; source: string | null; reason: string | null; }
let cache: AdjustmentStatus | null = null;

export function useAdjustment(): AdjustmentStatus | null {
  const [s, setS] = useState<AdjustmentStatus | null>(cache);
  useEffect(() => {
    if (!cache) api.adjustment().then((r) => { cache = r; setS(r); }).catch(() => setS({ active: false, source: null, reason: null }));
  }, []);
  return s;
}

export function AcrossLeaguesToggle({ checked, onChange, status }: {
  checked: boolean; onChange: (v: boolean) => void; status: AdjustmentStatus | null;
}) {
  const active = !!status?.active;
  return (
    <div>
      <label className={`flex items-start gap-2 text-sm ${active ? "" : "text-ink-faint"}`}>
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-board" disabled={!active}
               checked={active && checked} onChange={(e) => onChange(e.target.checked)} />
        <span>
          <span className="font-semibold">Compare across leagues</span>
          <span className="block text-xs text-ink-faint">
            {active
              ? `League-adjusted scores (${status!.source}): a 90 in a weaker league counts for less than a 90 in a stronger one.`
              : status ? "Not available: no league-strength adjustment is active yet. Scores rank players within their own league."
                : "Checking…"}
          </span>
        </span>
      </label>
    </div>
  );
}
