import { describe, expect, it } from "vitest";
import { forecastBandSeries } from "./forecastBand";

describe("forecastBandSeries", () => {
  it("以 hw(t) = bandNow + bandPerDay × t 展开上下界", () => {
    const projected = [
      { label: "2026-09-19", value: 1000, days: 0 },
      { label: "2026-10-19", value: 1300, days: 30 }
    ];

    const { upper, lower } = forecastBandSeries(projected, 50, 2);

    expect(upper.get("2026-09-19")).toBe(1050);
    expect(lower.get("2026-09-19")).toBe(950);
    expect(upper.get("2026-10-19")).toBe(1300 + 50 + 60);
    expect(lower.get("2026-10-19")).toBe(1300 - 110);
  });

  it("下限不为负", () => {
    const projected = [{ label: "2026-09-19", value: 20, days: 60 }];

    const { lower } = forecastBandSeries(projected, 100, 10);

    expect(lower.get("2026-09-19")).toBe(0);
  });

  it("零带宽时上下界等于预测值本身", () => {
    const projected = [{ label: "2026-09-19", value: 800, days: 15 }];

    const { upper, lower } = forecastBandSeries(projected, 0, 0);

    expect(upper.get("2026-09-19")).toBe(800);
    expect(lower.get("2026-09-19")).toBe(800);
  });
});
