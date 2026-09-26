import { describe, expect, it } from "vitest";
import { hasSampleSpan, TOP_GROWTH_VM_LIMIT } from "./growth";

describe("hasSampleSpan", () => {
  it("keeps items whose span meets the period requirement", () => {
    expect(hasSampleSpan({ sample_span_days: 1 }, 1)).toBe(true);
    expect(hasSampleSpan({ sample_span_days: 30 }, 30)).toBe(true);
    expect(hasSampleSpan({ sample_span_days: 30.5 }, 30)).toBe(true);
  });

  it("drops items whose span is shorter than the period requirement", () => {
    expect(hasSampleSpan({ sample_span_days: 0.5 }, 1)).toBe(false);
    expect(hasSampleSpan({ sample_span_days: 14 }, 30)).toBe(false);
  });

  it("keeps items without span information (legacy payloads)", () => {
    expect(hasSampleSpan({}, 1)).toBe(true);
    expect(hasSampleSpan({ sample_span_days: null }, 30)).toBe(true);
  });

  it("shares one display limit between both pages", () => {
    expect(TOP_GROWTH_VM_LIMIT).toBe(50);
  });
});
