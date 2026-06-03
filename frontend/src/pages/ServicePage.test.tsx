import { describe, expect, it } from "vitest";
import { formatVersionForDisplay } from "./ServicePage";

describe("formatVersionForDisplay", () => {
  it("displays canonical prefixed software versions", () => {
    expect(formatVersionForDisplay("v0.4.0")).toBe("v0.4.0");
  });

  it("keeps existing v prefix unchanged", () => {
    expect(formatVersionForDisplay("v0.1.0")).toBe("v0.1.0");
  });

  it("keeps empty display placeholder unchanged", () => {
    expect(formatVersionForDisplay("-")).toBe("-");
  });
});
