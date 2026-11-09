// A short reading of a market value history: the change over the last year and the peak.
export interface ValuePoint { date: string; value_eur: number; }

export interface ValueTrend {
  latest: ValuePoint;
  yearAgo: ValuePoint | null;       // the last valuation at least 12 months before the latest
  changePct: number | null;         // latest vs yearAgo, in %
  peak: ValuePoint;
  belowPeakPct: number;             // how far the latest is below the peak, in % (0 at the peak)
}

export function valueTrend(points: ValuePoint[]): ValueTrend | null {
  if (points.length === 0) return null;
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const latest = sorted[sorted.length - 1];
  const cutoff = new Date(latest.date);
  cutoff.setFullYear(cutoff.getFullYear() - 1);
  const before = sorted.filter((p) => new Date(p.date) <= cutoff);
  const yearAgo = before.length ? before[before.length - 1] : null;
  const changePct = yearAgo && yearAgo.value_eur > 0
    ? Math.round(((latest.value_eur - yearAgo.value_eur) / yearAgo.value_eur) * 100) : null;
  const peak = sorted.reduce((a, b) => (b.value_eur >= a.value_eur ? b : a));
  const belowPeakPct = peak.value_eur > 0 ? Math.round((1 - latest.value_eur / peak.value_eur) * 100) : 0;
  return { latest, yearAgo, changePct, peak, belowPeakPct };
}
