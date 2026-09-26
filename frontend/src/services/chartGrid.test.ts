import { describe, expect, it } from "vitest";
import { buildDailyGrid } from "./chartGrid";

describe("buildDailyGrid", () => {
  it("fills missing days with null so the chart can break the line", () => {
    expect(
      buildDailyGrid([
        ["2026-08-20", 33],
        ["2026-09-12", 37]
      ])
    ).toEqual([
      ["2026-08-20", 33],
      ["2026-08-21", null],
      ["2026-08-22", null],
      ["2026-08-23", null],
      ["2026-08-24", null],
      ["2026-08-25", null],
      ["2026-08-26", null],
      ["2026-08-27", null],
      ["2026-08-28", null],
      ["2026-08-29", null],
      ["2026-08-30", null],
      ["2026-08-31", null],
      ["2026-09-01", null],
      ["2026-09-02", null],
      ["2026-09-03", null],
      ["2026-09-04", null],
      ["2026-09-05", null],
      ["2026-09-06", null],
      ["2026-09-07", null],
      ["2026-09-08", null],
      ["2026-09-09", null],
      ["2026-09-10", null],
      ["2026-09-11", null],
      ["2026-09-12", 37]
    ]);
  });

  it("keeps a continuous series untouched", () => {
    expect(
      buildDailyGrid([
        ["2026-09-12", 1],
        ["2026-09-13", 2],
        ["2026-09-14", 3]
      ])
    ).toEqual([
      ["2026-09-12", 1],
      ["2026-09-13", 2],
      ["2026-09-14", 3]
    ]);
  });

  it("sorts unsorted points and handles single/empty input", () => {
    expect(buildDailyGrid([["2026-09-13", 2], ["2026-09-12", 1]])).toEqual([
      ["2026-09-12", 1],
      ["2026-09-13", 2]
    ]);
    expect(buildDailyGrid([["2026-09-12", 1]])).toEqual([["2026-09-12", 1]]);
    expect(buildDailyGrid([])).toEqual([]);
  });
});
