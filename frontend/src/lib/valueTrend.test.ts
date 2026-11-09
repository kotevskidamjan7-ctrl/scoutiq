import { describe, expect, it } from "vitest";
import { valueTrend } from "./valueTrend";

describe("valueTrend", () => {
  it("compares with the last valuation at least a year earlier and finds the peak", () => {
    const t = valueTrend([
      { date: "2024-01-10", value_eur: 8_000_000 },
      { date: "2025-03-01", value_eur: 10_000_000 },
      { date: "2025-06-20", value_eur: 20_000_000 },
      { date: "2026-06-12", value_eur: 15_000_000 },
    ])!;
    expect(t.yearAgo?.date).toBe("2025-03-01");
    expect(t.changePct).toBe(50);
    expect(t.peak.value_eur).toBe(20_000_000);
    expect(t.belowPeakPct).toBe(25);
  });
  it("has no yearly change when the history is shorter than a year", () => {
    const t = valueTrend([{ date: "2026-01-01", value_eur: 1_000_000 }, { date: "2026-06-01", value_eur: 2_000_000 }])!;
    expect(t.changePct).toBeNull();
    expect(t.belowPeakPct).toBe(0);
  });
  it("is null without valuations", () => expect(valueTrend([])).toBeNull());
});
