import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";
import { api } from "../services/api";

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

  it("marks the first-row capacity risk card as danger when cluster risk is high", () => {
    const { container } = render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 3, used_bytes: 88, total_bytes: 100, used_ratio: 0.88 },
          capacity_risk: {
            level: "high",
            title: "容量高风险",
            description: "风险集群 使用率超过 80%，容量风险较高。",
            cluster_count: 1,
            warning_count: 0,
            danger_count: 1,
            top_clusters: [{ tower_id: "1", cluster_id: "cluster-risk", cluster: "风险集群", used_ratio: 0.88 }]
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

    const riskCard = container.querySelector(".capacity-risk-mini");
    expect(riskCard).toHaveClass("danger");
    expect(riskCard).not.toHaveClass("warning");
  });

  it("places risk summary below SmartX ZBS and pairs collection/growth cards with their detail cards", () => {
    const { container } = render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 2, used_bytes: 88, total_bytes: 100, used_ratio: 0.88 },
          capacity_risk: {
            level: "high",
            title: "容量高风险",
            description: "风险集群 使用率超过 80%，容量风险较高。",
            cluster_count: 1,
            warning_count: 0,
            danger_count: 1,
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

    const cardTitles = Array.from(container.querySelectorAll(".dashboard-grid > .card .card-title h2")).map((item) => item.textContent);
    expect(cardTitles).toEqual(["SmartX ZBS", "风险提示", "采集状态", "日增长最快 VM", "集群容量", "本日新建 VM"]);
    expect(screen.getByText("风险提示").closest("section")).toHaveClass("risk-wide-card");
  });

  it("keeps normal risk summary aligned with the icon instead of centered", () => {
    const { container } = render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 2, used_bytes: 40, total_bytes: 100, used_ratio: 0.4 },
          capacity_risk: {
            level: "normal",
            title: "容量风险正常",
            description: "当前所有集群暂无明显容量风险",
            cluster_count: 1,
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

    const riskSection = screen.getByRole("heading", { name: "风险提示" }).closest("section")!;
    expect(riskSection.querySelector(".risk-summary-main")).toHaveClass("normal");
    expect(container.querySelector(".risk-summary")).toHaveClass("normal");
    expect(within(riskSection).queryByRole("button", { name: "查看风险报表" })).not.toBeInTheDocument();
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

  it("shows risk clusters instead of vms in the risk panel and opens the selected cluster vm details", () => {
    const onOpenRiskReport = vi.fn();
    const onOpenRiskVms = vi.fn();
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
            warning_count: 1,
            danger_count: 1,
            risk_clusters: [
              {
                tower_id: "7",
                cluster_id: "cluster-risk",
                cluster: "风险集群",
                risk_level: "high",
                used_bytes: 880,
                total_bytes: 1000,
                used_ratio: 0.88,
                forecast_90d: 1080,
                exhaustion_days: 24
              },
              {
                tower_id: "8",
                cluster_id: "cluster-warning",
                cluster: "关注集群",
                risk_level: "warning",
                used_bytes: 760,
                total_bytes: 1000,
                used_ratio: 0.76,
                forecast_90d: 930,
                exhaustion_days: 72
              }
            ],
            top_clusters: [
              {
                tower_id: "7",
                cluster_id: "cluster-risk",
                cluster: "风险集群",
                used_ratio: 0.88
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
        onOpenRiskVms={onOpenRiskVms}
      />
    );

    fireEvent.click(screen.getAllByRole("button", { name: /容量高风险/ })[0]);
    expect(onOpenRiskReport).toHaveBeenCalledWith({ type: "cluster", towerId: 7, clusterId: "cluster-risk" });

    const riskPanel = screen.getByRole("heading", { name: "风险提示" }).closest("section")!;
    expect(within(riskPanel).queryByText("主要增长 VM")).not.toBeInTheDocument();
    expect(within(riskPanel).getAllByText("风险集群").length).toBeGreaterThan(0);
    expect(within(riskPanel).getByText("1 个高风险，1 个需关注")).toBeInTheDocument();
    expect(within(riskPanel).getByText("容量高风险")).toBeInTheDocument();
    expect(within(riskPanel).queryByText(/当前/)).not.toBeInTheDocument();
    expect(within(riskPanel).queryByText(/90 天后/)).not.toBeInTheDocument();
    expect(within(riskPanel).getAllByText("预计存储耗尽").length).toBeGreaterThan(0);
    expect(within(riskPanel).getByText("24 天")).toHaveClass("exhaustion-days-risk");
    expect(within(riskPanel).getByText("72 天")).toHaveClass("exhaustion-days-risk");
    expect(within(riskPanel).getByText("关注集群")).toBeInTheDocument();
    expect(riskPanel.querySelector(".risk-cluster-action-icon")).not.toBeInTheDocument();

    fireEvent.click(within(riskPanel).getAllByRole("button", { name: "查看详情" })[1]);
    expect(onOpenRiskVms).toHaveBeenCalledWith({ type: "cluster", towerId: 8, clusterId: "cluster-warning" });
    expect(onOpenRiskReport).toHaveBeenCalledTimes(1);
    expect(onSelectVm).not.toHaveBeenCalled();
  });

  it("falls back to top clusters when risk cluster rows are not provided", () => {
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

    const riskPanel = screen.getByRole("heading", { name: "风险提示" }).closest("section")!;
    expect(within(riskPanel).getByText("1 个高风险")).toBeInTheDocument();
    expect(within(riskPanel).getAllByText("风险集群").length).toBeGreaterThan(0);
    expect(within(riskPanel).getByText("容量高风险 · 90.0%")).toBeInTheDocument();
    expect(within(riskPanel).getByRole("button", { name: "查看详情" })).toBeInTheDocument();
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

  it("adds and updates a task when manual collection runs", async () => {
    vi.mocked(api.runCollection).mockResolvedValueOnce({ run_id: 88, status: "success", message: "采集完成：1 个集群，167 台虚拟机。" });
    vi.mocked(api.summary).mockResolvedValueOnce({
      kpis: { tower_count: 1, cluster_count: 1, vm_count: 167, used_bytes: 100, total_bytes: 200, used_ratio: 0.5 },
      top_vms: [],
      clusters: [],
      towers: []
    });
    const addTask = vi.fn();
    const updateTask = vi.fn();
    render(
      <DashboardPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 0, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSummary={vi.fn()}
        onSelectVm={vi.fn()}
        addTask={addTask}
        updateTask={updateTask}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /立即采集/ }));

    expect(addTask).toHaveBeenCalledWith(
      expect.objectContaining({
        id: expect.stringMatching(/^collection-run-local-/),
        kind: "download",
        title: "执行采集",
        status: "running",
        progress: 10,
        detail: "正在采集 Tower/集群容量数据"
      })
    );
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(
        expect.stringMatching(/^collection-run-local-/),
        expect.objectContaining({
          status: "succeeded",
          progress: 100,
          detail: "采集完成：1 个集群，167 台虚拟机。"
        })
      );
    });
  });
});
