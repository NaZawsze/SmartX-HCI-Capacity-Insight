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

  it("uses cluster-level capacity risk", () => {
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 2, vm_count: 3, used_bytes: 100, total_bytes: 200, used_ratio: 0.5 },
          capacity_risk: {
            level: "danger",
            title: "容量高风险",
            description: "已有集群容量达到高风险阈值：风险集群 当前已使用 80.00%。",
            cluster_count: 2,
            warning_count: 0,
            danger_count: 1,
            top_clusters: [{ cluster: "风险集群", used_ratio: 0.8 }]
          },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={vi.fn()}
      />
    );
    expect(screen.getAllByText("容量高风险").length).toBeGreaterThan(0);
    expect(screen.getByText(/风险集群/)).toBeInTheDocument();
  });
});
