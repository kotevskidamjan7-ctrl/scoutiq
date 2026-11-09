import { describe, expect, it } from "vitest";
import { pageName } from "./backTo";

describe("pageName", () => {
  it("names the pages a person can come back to", () => {
    expect(pageName("/")).toBe("dashboard");
    expect(pageName("/players")).toBe("players");
    expect(pageName("/players/42")).toBe("previous player");
    expect(pageName("/improve")).toBe("Improve my club");
    expect(pageName("/builder")).toBe("squad builder");
    expect(pageName("/compare")).toBe("comparison");
    expect(pageName("/scenarios")).toBe("saved scenarios");
    expect(pageName("/scenarios/3")).toBe("scenario");
    expect(pageName("/something")).toBe("previous page");
  });
});
