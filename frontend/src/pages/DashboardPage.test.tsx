import { fireEvent, render, screen, within } from "@testing-library/react";
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
    expect(screen.getAllByText(/风险集群/).length).toBeGreaterThan(0);
  });

  it("keeps capacity risk, tower, and cluster as separate metric cards in the first row", () => {
    const { container } = render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 3, cluster_count: 6, vm_count: 30, used_bytes: 100, total_bytes: 200, used_ratio: 0.5 },
          capacity_risk: {
            level: "normal",
            title: "容量风险正常",
            description: "当前所有集群暂无明显容量风险",
            cluster_count: 6,
            warning_count: 0,
            danger_count: 0,
            top_clusters: []
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

    const row = container.querySelector(".dashboard-metrics-row");
    expect(row).toBeTruthy();
    const cards = Array.from(row!.children);
    expect(cards).toHaveLength(5);
    expect(cards[0]).toHaveTextContent("容量风险正常");
    expect(cards[1]).toHaveTextContent("Tower");
    expect(cards[1]).toHaveTextContent("3");
    expect(cards[2]).toHaveTextContent("集群");
    expect(cards[2]).toHaveTextContent("6");
    expect(cards[0]).not.toHaveTextContent("Tower");
    expect(cards[1]).not.toHaveTextContent("集群");
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

  it("opens the riskiest cluster report when capacity risk is clicked", () => {
    const onOpenRiskReport = vi.fn();
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
            top_clusters: [{ tower_id: "7", cluster_id: "cluster-risk", cluster: "风险集群", used_ratio: 0.8 }]
          },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={vi.fn()}
        onOpenRiskReport={onOpenRiskReport}
      />
    );

    fireEvent.click(screen.getAllByRole("button", { name: /容量高风险/ })[0]);

    expect(onOpenRiskReport).toHaveBeenCalledWith({ type: "cluster", towerId: 7, clusterId: "cluster-risk" });
  });

  it("shows top growth vms in the risk panel and opens vm detail while keeping the top risk card report link", () => {
    const onOpenRiskReport = vi.fn();
    const onSelectVm = vi.fn();
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 2, vm_count: 3, used_bytes: 100, total_bytes: 200, used_ratio: 0.5 },
          capacity_risk: {
            level: "danger",
            title: "容量高风险",
            description: "风险集群 使用率超过 80%，容量风险较高。",
            cluster_count: 2,
            warning_count: 0,
            danger_count: 1,
            top_clusters: [
              {
                tower_id: "7",
                cluster_id: "cluster-risk",
                cluster: "风险集群",
                used_ratio: 0.82,
                top_growth_vms: [
                  {
                    tower_id: 7,
                    cluster_id: "cluster-risk",
                    vm_id: "vm-risk-1",
                    vm_name: "风险增长 VM",
                    current_bytes: 120,
                    growth_amount: 20,
                    growth_ratio: 0.2
                  }
                ]
              }
            ]
          },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={onSelectVm}
        onOpenRiskReport={onOpenRiskReport}
      />
    );

    fireEvent.click(screen.getAllByRole("button", { name: /容量高风险/ })[0]);
    expect(onOpenRiskReport).toHaveBeenCalledWith({ type: "cluster", towerId: 7, clusterId: "cluster-risk" });

    const riskPanel = screen.getByText("主要增长 VM").closest("section")!;
    expect(within(riskPanel).getByText("风险增长 VM")).toBeInTheDocument();
    fireEvent.click(within(riskPanel).getByRole("button", { name: /风险增长 VM/ }));

    expect(onSelectVm).toHaveBeenCalledWith("vm-risk-1", "风险增长 VM");
  });

  it("shows an empty top growth source message when risky clusters have no growing vms", () => {
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 0, used_bytes: 90, total_bytes: 100, used_ratio: 0.9 },
          capacity_risk: {
            level: "danger",
            title: "容量高风险",
            description: "风险集群 使用率超过 80%，容量风险较高。",
            cluster_count: 1,
            warning_count: 0,
            danger_count: 1,
            top_clusters: [{ tower_id: "1", cluster_id: "cluster-risk", cluster: "风险集群", used_ratio: 0.9, top_growth_vms: [] }]
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

    expect(screen.getByText("风险集群暂无明显 VM 增长来源")).toBeInTheDocument();
  });

  it("renders cluster capacity details inside the SmartX ZBS card sorted by usage", () => {
    const onOpenRiskReport = vi.fn();
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 3, vm_count: 3, used_bytes: 100, total_bytes: 300, used_ratio: 1 / 3 },
          top_vms: [],
          clusters: [
            { metric: { tower_id: "1", cluster_id: "cluster-low", cluster: "低使用集群" }, value: 20, total_bytes: 100 },
            { metric: { tower_id: "1", cluster_id: "cluster-risk", cluster: "高风险集群" }, value: 90, total_bytes: 100 },
            { metric: { tower_id: "1", cluster_id: "cluster-warning", cluster: "关注集群" }, value: 76, total_bytes: 100 }
          ],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={vi.fn()}
        onOpenRiskReport={onOpenRiskReport}
      />
    );

    const zbsCard = screen.getByText("集群容量明细").closest("section")!;
    const zbs = within(zbsCard);

    const clusterButtons = zbs.getAllByRole("button", { name: /集群/ }).filter((button) => button.className.includes("cluster-capacity-row"));
    expect(clusterButtons[0]).toHaveTextContent("高风险集群");
    expect(clusterButtons[0]).toHaveTextContent("已使用 90 B");
    expect(clusterButtons[0]).toHaveTextContent("总容量 100 B");
    expect(clusterButtons[0]).toHaveTextContent("90.00%");
    expect(clusterButtons[1]).toHaveTextContent("关注集群");
    expect(clusterButtons[2]).toHaveTextContent("低使用集群");

    fireEvent.click(clusterButtons[0]);
    expect(onOpenRiskReport).toHaveBeenCalledWith({ type: "cluster", towerId: 1, clusterId: "cluster-risk" });
  });

  it("shows insufficient data for cluster capacity rows without total capacity", () => {
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 0, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
          top_vms: [],
          clusters: [{ metric: { tower_id: "1", cluster_id: "cluster-empty", cluster: "容量未知集群" }, value: 0, total_bytes: 0 }],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={vi.fn()}
      />
    );

    const zbsCard = screen.getByText("集群容量明细").closest("section")!;
    const zbs = within(zbsCard);
    expect(zbs.getByText("容量未知集群")).toBeInTheDocument();
    expect(zbs.getByText("数据不足")).toBeInTheDocument();
  });
});
