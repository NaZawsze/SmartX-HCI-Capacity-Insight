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
    expect(screen.getAllByText("50.00%").length).toBeGreaterThan(0);
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

  it("renders v2 day growth and day new vm as separate cards", () => {
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 2, used_bytes: 100, total_bytes: 200, used_ratio: 0.5 },
          top_vms: [],
          day_fastest_growing_vms: [
            {
              metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-1", vm: "VM One", cluster: "Cluster A" },
              value: 120,
              growth_amount: 20,
              previous_value: 100,
              growth_ratio: 0.2
            }
          ],
          day_new_vms: [
            {
              metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-2", vm: "VM Two", cluster: "Cluster A" },
              value: 10
            }
          ],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={vi.fn()}
      />
    );

    expect(screen.getAllByText("日增长最快 VM").length).toBeGreaterThan(0);
    expect(screen.getByText("本日新建 VM")).toBeInTheDocument();
    expect(screen.getByText("VM One")).toBeInTheDocument();
    expect(screen.getByText("VM Two")).toBeInTheDocument();
  });
});
