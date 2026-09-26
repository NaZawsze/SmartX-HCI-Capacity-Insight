import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StorageBar } from "./StorageBar";

vi.mock("../services/api", () => ({
  formatBytes: (value: number) => `${value} B`
}));

function segmentWidths() {
  const segments = document.querySelectorAll<HTMLElement>(".storage-track > div");
  return Array.from(segments).map((segment) => segment.style.width);
}

function metaValues() {
  const meta = document.querySelector<HTMLElement>(".storage-meta");
  if (!meta) return { labels: [], values: [] as string[] };
  return {
    labels: Array.from(meta.querySelectorAll(".storage-meta-label")).map((node) => node.textContent),
    values: Array.from(meta.querySelectorAll(".storage-meta-value")).map((node) => node.textContent)
  };
}

describe("StorageBar", () => {
  it("stacks used and allocated segments capped at total capacity", () => {
    render(<StorageBar used={70} total={100} allocated={270} />);

    expect(segmentWidths()).toEqual(["70%", "30%"]);
    expect(metaValues()).toEqual({
      labels: ["已使用", "总容量", "已分配"],
      values: ["70 B · 70.00%", "100 B", "270 B · 270.00%"]
    });
  });

  it("hides the allocated segment when nothing is allocated", () => {
    render(<StorageBar used={40} total={100} />);

    expect(segmentWidths()).toEqual(["40%", "0%"]);
    expect(metaValues().values).toEqual(["40 B · 40.00%", "100 B", "0 B · 0.00%"]);
  });

  it("does not draw an allocated segment inside already used space", () => {
    render(<StorageBar used={40} total={100} allocated={20} />);

    expect(segmentWidths()).toEqual(["40%", "0%"]);
    expect(metaValues().values).toEqual(["40 B · 40.00%", "100 B", "20 B · 20.00%"]);
  });

  it("renders zero widths when total capacity is unknown", () => {
    render(<StorageBar used={40} total={0} allocated={20} />);

    expect(segmentWidths()).toEqual(["0%", "0%"]);
    expect(metaValues().values).toEqual(["40 B · 0.00%", "0 B", "20 B · 0.00%"]);
  });
});
