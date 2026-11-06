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

/** A metric's raw value: rates as a percentage, per-90 values with two decimals. */
export function metricValue(kind: "per90" | "rate", value: number | null): string {
  if (value == null) return "–";
  return kind === "rate" ? `${Math.round(value * 100)}%` : value.toFixed(2);
}

/** Value for money: score points above (+) or below (−) what the player's price predicts. */
export function signed(n: number | null | undefined, digits = 1): string {
  if (n == null) return "–";
  const t = Math.abs(n).toFixed(digits);
  return n > 0 ? `+${t}` : n < 0 ? `−${t}` : t;
}

export const RELIABILITY_TEXT: Record<string, string> = {
  high: "High: 1,800+ league minutes",
  medium: "Medium: 900–1,799 league minutes",
  low: "Low: under 900 minutes, or many statistics missing",
};

export function num(n: number | null | undefined): string {
  return n == null ? "–" : n.toLocaleString("en");
}


/** A money amount as the forms accept it: 2500000 -> "2.5m", 750000 -> "750k". */
export function moneyText(n: number): string {
  return n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(2)}m` : n >= 1_000 ? `${Math.round(n / 1_000)}k` : `${n}`;
}
