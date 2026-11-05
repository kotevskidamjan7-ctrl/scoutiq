// Money and label formatting shared across pages.

/** "15m", "500k", "€2.5m", "2,500,000" -> euros. Returns null if it cannot be read. */
export function parseMoney(text: string): number | null {
  const t = text.trim().toLowerCase().replace(/[€\s,]/g, "");
  const m = t.match(/^(\d+(?:\.\d+)?)([km]?)$/);
  if (!m) return null;
  const n = parseFloat(m[1]) * (m[2] === "m" ? 1_000_000 : m[2] === "k" ? 1_000 : 1);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

/** 14_800_000 -> "€14.8m", 750_000 -> "€750k" */
export function eur(amount: number | null | undefined): string {
  if (amount == null) return "–";
  if (Math.abs(amount) >= 1_000_000) return `€${(amount / 1_000_000).toFixed(amount % 1_000_000 === 0 ? 0 : 1)}m`;
  if (Math.abs(amount) >= 1_000) return `€${Math.round(amount / 1_000)}k`;
  return `€${amount}`;
}

export const ROLE_NAMES: Record<string, string> = {
  GK: "Goalkeeper", CB: "Centre-back", FB: "Full-back", CM: "Central midfielder", AW: "Attacking / wide", ST: "Striker",
};

export function surname(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? parts.slice(1).join(" ") : name;
}
