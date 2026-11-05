import { describe, expect, it } from "vitest";
import { eur, metricValue, parseMoney, signed, surname } from "./format";

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


describe("metricValue and signed", () => {
  it("formats rates as percentages and per-90 values with two decimals", () => {
    expect(metricValue("rate", 0.537)).toBe("54%");
    expect(metricValue("per90", 1.2345)).toBe("1.23");
    expect(metricValue("per90", null)).toBe("–");
  });
  it("puts a sign on value for money", () => {
    expect(signed(12.34)).toBe("+12.3");
    expect(signed(-4)).toBe("−4.0");
    expect(signed(null)).toBe("–");
  });
});
