import { describe, expect, it } from "vitest";
import { eur, parseMoney, surname } from "./format";

describe("parseMoney", () => {
  it("reads the ways people type budgets", () => {
    expect(parseMoney("15m")).toBe(15_000_000);
    expect(parseMoney("500k")).toBe(500_000);
    expect(parseMoney("€2.5m")).toBe(2_500_000);
    expect(parseMoney("2,500,000")).toBe(2_500_000);
    expect(parseMoney(" 1.25 M ")).toBe(1_250_000);
  });
  it("rejects what it cannot read", () => {
    expect(parseMoney("")).toBeNull();
    expect(parseMoney("fifteen")).toBeNull();
    expect(parseMoney("-5m")).toBeNull();
    expect(parseMoney("0")).toBeNull();
  });
});

describe("eur", () => {
  it("formats like the backend", () => {
    expect(eur(14_800_000)).toBe("€14.8m");
    expect(eur(15_000_000)).toBe("€15m");
    expect(eur(750_000)).toBe("€750k");
    expect(eur(null)).toBe("–");
  });
});

describe("surname", () => {
  it("keeps everything after the first name", () => {
    expect(surname("Marc Bartra")).toBe("Bartra");
    expect(surname("Lucas Vázquez Iglesias")).toBe("Vázquez Iglesias");
    expect(surname("Pedro")).toBe("Pedro");
  });
});
