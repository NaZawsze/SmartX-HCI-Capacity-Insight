import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";

vi.mock("../services/api", async () => ({
  api: {
    summary: vi.fn().mockResolvedValue({
      kpis: { tower_count: 0, cluster_count: 0, vm_count: 0, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
      top_vms: [],
      clusters: [],
      towers: []
    }),
    runCollection: vi.fn()
  },
  formatBytes: (value: number) => `${value} B`
}));

describe("DashboardPage", () => {
  it("renders storage overview", () => {
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 2, vm_count: 3, used_bytes: 100, total_bytes: 200, used_ratio: 0.5 },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={vi.fn()}
      />
    );
    expect(screen.getByText("SmartX ZBS")).toBeInTheDocument();
    expect(screen.getByText("50.00%")).toBeInTheDocument();
  });
});
