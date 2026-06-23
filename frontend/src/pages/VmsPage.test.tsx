import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VmsPage } from "./VmsPage";

const apiMock = vi.hoisted(() => ({
  vms: vi.fn(),
  vmDetail: vi.fn(),
  vmTrend: vi.fn(),
  vmVolumes: vi.fn(),
  vmVolumesAll: vi.fn()
}));

vi.mock("../services/api", async () => ({
  api: apiMock,
  formatBytes: (value: number | null | undefined) => `${value ?? 0} B`
}));

vi.mock("../components/TrendChart", () => ({
  TrendChart: ({ gapDates = [] }: { gapDates?: string[] }) => <div data-testid="trend-chart" data-gap-dates={gapDates.join(",")} />
}));

describe("VmsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.vmVolumesAll.mockResolvedValue([]);
  });

  it("loads v2 vm detail and volumes for the selected scoped vm", async () => {
    apiMock.vms.mockResolvedValue([
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-1", vm: "VM One", cluster: "Cluster A" },
        value: 70
      }
    ]);
    apiMock.vmDetail.mockResolvedValue({
      tower_id: 1,
      cluster_id: "cluster-a",
      vm_id: "vm-1",
      vm_name: "VM One",
      used_bytes: 70
    });
    apiMock.vmTrend.mockResolvedValue({
      vm_id: "vm-1",
      metric: "used",
      points: []
    });
    apiMock.vmVolumes.mockResolvedValue({
      vm_id: "vm-1",
      volumes: [{ volume_id: "vol-1", name: "Root", used_bytes: 60, size_bytes: 100, storage_policy: "Replica-2" }]
    });

    render(<VmsPage scope={{ type: "cluster", towerId: 1, clusterId: "cluster-a" }} selectedVmId="vm-1" />);

    await waitFor(() => expect(apiMock.vmDetail).toHaveBeenCalledWith("vm-1", { type: "cluster", towerId: 1, clusterId: "cluster-a" }));
    expect(apiMock.vmVolumes).toHaveBeenCalledWith("vm-1", { type: "cluster", towerId: 1, clusterId: "cluster-a" });
    expect(await screen.findByText("Root")).toBeInTheDocument();
    expect(screen.getAllByText("60 B").length).toBeGreaterThan(0);
    expect(screen.getByText("已使用 60.0%")).toBeInTheDocument();
  });

  it("shows stale collection warning and gap dates for vm trends", async () => {
    apiMock.vms.mockResolvedValue([
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-1", vm: "VM One", cluster: "Cluster A" },
        value: 70
      }
    ]);
    apiMock.vmDetail.mockResolvedValue({
      tower_id: 1,
      cluster_id: "cluster-a",
      vm_id: "vm-1",
      vm_name: "VM One",
      used_bytes: 70
    });
    apiMock.vmTrend.mockResolvedValue({
      vm_id: "vm-1",
      metric: "used",
      latest_success_at: "2026-06-12 02:10:00",
      latest_collection_status: "failed",
      data_freshness: "stale",
      has_collection_gap: true,
      gap_dates: ["2026-06-13"],
      points: [
        [1765497600, 50],
        [1765584000, 70]
      ]
    });
    apiMock.vmVolumes.mockResolvedValue({ vm_id: "vm-1", volumes: [] });

    render(<VmsPage scope={{ type: "cluster", towerId: 1, clusterId: "cluster-a" }} selectedVmId="vm-1" />);

    expect(await screen.findByText("非最新")).toBeInTheDocument();
    expect(screen.getByText(/当前集群最近一次成功采集：2026-06-12 02:10:00/)).toBeInTheDocument();
    expect(screen.getByText(/缺采日期：2026-06-13/)).toBeInTheDocument();
    expect(screen.getByTestId("trend-chart")).toHaveAttribute("data-gap-dates", "2026-06-13");
  });

  it("uses the selected vm metric scope when the page scope includes all clusters", async () => {
    apiMock.vms.mockResolvedValue([
      {
        metric: {
          tower_id: "2",
          cluster_id: "cm551tvrv029a0858up57q8qu",
          vm_id: "vm-global",
          vm: "Global VM",
          cluster: "网络监测平台集群"
        },
        value: 101
      }
    ]);
    apiMock.vmDetail.mockResolvedValue({
      tower_id: 2,
      cluster_id: "cm551tvrv029a0858up57q8qu",
      vm_id: "vm-global",
      vm_name: "Global VM",
      used_bytes: 101
    });
    apiMock.vmTrend.mockResolvedValue({
      vm_id: "vm-global",
      metric: "used",
      points: []
    });
    apiMock.vmVolumes.mockResolvedValue({
      vm_id: "vm-global",
      volumes: []
    });

    render(<VmsPage scope={{ type: "all" }} selectedVmId="vm-global" />);

    const derivedScope = { type: "cluster" as const, towerId: 2, clusterId: "cm551tvrv029a0858up57q8qu" };
    await waitFor(() => expect(apiMock.vmDetail).toHaveBeenCalledWith("vm-global", derivedScope));
    expect(apiMock.vmTrend).toHaveBeenCalledWith("vm-global", "used", 30, derivedScope);
    expect(apiMock.vmVolumes).toHaveBeenCalledWith("vm-global", derivedScope);
    expect(screen.getAllByText("网络监测平台集群").length).toBeGreaterThan(0);
    expect(screen.queryByText("cm551tvrv029a0858up57q8qu")).not.toBeInTheDocument();
  });

  it("renders all volumes and sorts by used or occupied size", async () => {
    apiMock.vms.mockResolvedValue([
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-1", vm: "VM One", cluster: "Cluster A" },
        value: 70
      }
    ]);
    apiMock.vmDetail.mockResolvedValue({
      tower_id: 1,
      cluster_id: "cluster-a",
      vm_id: "vm-1",
      vm_name: "VM One",
      used_bytes: 70
    });
    apiMock.vmTrend.mockResolvedValue({ vm_id: "vm-1", metric: "used", points: [] });
    apiMock.vmVolumes.mockResolvedValue({
      vm_id: "vm-1",
      volumes: [{ volume_id: "vol-1", name: "Root", used_bytes: 60, size_bytes: 100, replica_num: 2 }]
    });
    apiMock.vmVolumesAll.mockResolvedValue([
      {
        tower_id: 1,
        cluster_id: "cluster-a",
        cluster_name: "Cluster A",
        vm_id: "vm-1",
        vm_name: "VM One",
        volumes: [{ volume_id: "vol-small", name: "Small", used_bytes: 10, size_bytes: 100, replica_num: 2 }]
      },
      {
        tower_id: 1,
        cluster_id: "cluster-a",
        cluster_name: "Cluster A",
        vm_id: "vm-2",
        vm_name: "VM Two",
        volumes: [{ volume_id: "vol-large", name: "Large", used_bytes: 80, size_bytes: 100, replica_num: 1 }]
      }
    ]);

    render(<VmsPage scope={{ type: "cluster", towerId: 1, clusterId: "cluster-a" }} selectedVmId="vm-1" />);

    await waitFor(() => expect(apiMock.vmVolumesAll).toHaveBeenCalledWith({ type: "cluster", towerId: 1, clusterId: "cluster-a" }));
    const allVolumes = await screen.findByLabelText("当前集群虚拟卷");
    expect(screen.getByRole("heading", { name: "当前集群虚拟卷" })).toBeInTheDocument();
    expect(within(allVolumes).getByText("Small")).toBeInTheDocument();
    expect(within(allVolumes).getByText("Large")).toBeInTheDocument();

    const namesBefore = within(allVolumes).getAllByTestId("volume-name").map((node) => node.textContent);
    expect(namesBefore).toEqual(["Large", "Small"]);

    fireEvent.click(screen.getByRole("button", { name: "按实际使用空间升序排序" }));
    const namesAfterUsedAsc = within(allVolumes).getAllByTestId("volume-name").map((node) => node.textContent);
    expect(namesAfterUsedAsc).toEqual(["Small", "Large"]);

    fireEvent.click(screen.getByRole("button", { name: "按实际占用集群空间降序排序" }));
    const namesAfterOccupiedDesc = within(allVolumes).getAllByTestId("volume-name").map((node) => node.textContent);
    expect(namesAfterOccupiedDesc).toEqual(["Large", "Small"]);

    fireEvent.click(screen.getByRole("button", { name: "按VM升序排序" }));
    const namesAfterVmAsc = within(allVolumes).getAllByTestId("volume-name").map((node) => node.textContent);
    expect(namesAfterVmAsc).toEqual(["Small", "Large"]);

    fireEvent.click(screen.getByRole("button", { name: "按VM降序排序" }));
    const namesAfterVmDesc = within(allVolumes).getAllByTestId("volume-name").map((node) => node.textContent);
    expect(namesAfterVmDesc).toEqual(["Large", "Small"]);
  });

  it("opens the matching vm trend when clicking a vm in all volumes", async () => {
    apiMock.vms.mockResolvedValue([
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-1", vm: "VM One", cluster: "Cluster A" },
        value: 70
      },
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-2", vm: "VM Two", cluster: "Cluster A" },
        value: 85
      }
    ]);
    apiMock.vmDetail.mockImplementation((vmId: string) =>
      Promise.resolve({ tower_id: 1, cluster_id: "cluster-a", vm_id: vmId, vm_name: vmId === "vm-2" ? "VM Two" : "VM One", used_bytes: vmId === "vm-2" ? 85 : 70 })
    );
    apiMock.vmTrend.mockResolvedValue({ vm_id: "vm-1", metric: "used", points: [] });
    apiMock.vmVolumes.mockResolvedValue({ vm_id: "vm-1", volumes: [] });
    apiMock.vmVolumesAll.mockResolvedValue([
      { tower_id: 1, cluster_id: "cluster-a", cluster_name: "Cluster A", vm_id: "vm-1", vm_name: "VM One", volumes: [{ volume_id: "vol-1", name: "Root", used_bytes: 70, size_bytes: 100 }] },
      { tower_id: 1, cluster_id: "cluster-a", cluster_name: "Cluster A", vm_id: "vm-2", vm_name: "VM Two", volumes: [{ volume_id: "vol-2", name: "Data", used_bytes: 85, size_bytes: 100 }] }
    ]);

    render(<VmsPage scope={{ type: "cluster", towerId: 1, clusterId: "cluster-a" }} selectedVmId="vm-1" />);

    const allVolumes = await screen.findByLabelText("当前集群虚拟卷");
    fireEvent.click(within(allVolumes).getByRole("button", { name: "VM Two" }));

    await waitFor(() => expect(apiMock.vmDetail).toHaveBeenLastCalledWith("vm-2", { type: "cluster", towerId: 1, clusterId: "cluster-a" }));
    expect(screen.getByRole("heading", { name: "VM Two" })).toBeInTheDocument();
  });

  it("renders tower and cluster selector cards plus vm summary cards", async () => {
    apiMock.vms.mockResolvedValue([
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-1", vm: "VM One", cluster: "Cluster A" },
        value: 70
      }
    ]);
    apiMock.vmDetail.mockResolvedValue({
      tower_id: 1,
      cluster_id: "cluster-a",
      vm_id: "vm-1",
      vm_name: "VM One",
      used_bytes: 70
    });
    apiMock.vmTrend.mockResolvedValue({ vm_id: "vm-1", metric: "used", points: [] });
    apiMock.vmVolumes.mockResolvedValue({ vm_id: "vm-1", volumes: [] });

    render(
      <VmsPage
        scope={{ type: "all" }}
        summary={{
          kpis: { tower_count: 1, cluster_count: 2, vm_count: 177, used_bytes: 192.88 * 1024 ** 4, total_bytes: 219.18 * 1024 ** 4, used_ratio: 0.88 },
          capacity_risk: { level: "normal", title: "正常", description: "正常", cluster_count: 2, warning_count: 0, danger_count: 0, top_clusters: [] },
          top_vms: [],
          clusters: [],
          towers: [
            {
              id: 1,
              name: "Tower A",
              base_url: "https://tower-a",
              verify_tls: true,
              enabled: true,
              collection_hour: 2,
              collection_minute: 10,
              collection_retry_enabled: true,
              collection_retry_interval_minutes: 15,
              collection_retry_max_attempts: 3,
              clusters: [
                { cluster_id: "cluster-a", name: "Cluster A", enabled: true },
                { cluster_id: "cluster-b", name: "Cluster B", enabled: true }
              ]
            }
          ]
        }}
      />
    );

    const summaryCards = await screen.findByLabelText("虚拟机页筛选与概览");
    expect(summaryCards).not.toHaveClass("dashboard-metrics-row");
    expect(within(summaryCards).getByText("Tower")).toBeInTheDocument();
    expect(within(summaryCards).getByLabelText("Tower图标")).toBeInTheDocument();
    expect(screen.getByLabelText("虚拟机页Tower")).toHaveValue("all");
    expect(within(summaryCards).getByText("集群")).toBeInTheDocument();
    expect(within(summaryCards).getByLabelText("集群图标")).toBeInTheDocument();
    expect(screen.getByLabelText("虚拟机页集群")).toHaveValue("all");
    expect(within(summaryCards).getByText("虚拟机")).toBeInTheDocument();
    expect(within(summaryCards).getByText("容量使用率")).toBeInTheDocument();
    expect(within(summaryCards).getByText("88.00%")).toBeInTheDocument();
    expect(summaryCards.querySelectorAll(".vm-metric-copy")).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("虚拟机页Tower"), { target: { value: "1" } });
    expect(screen.getByLabelText("虚拟机页Tower")).toHaveValue("1");
    expect(screen.getByLabelText("虚拟机页集群")).toHaveValue("all");
    await waitFor(() => expect(apiMock.vms).toHaveBeenLastCalledWith({ type: "tower", towerId: 1 }));

    fireEvent.change(screen.getByLabelText("虚拟机页集群"), { target: { value: "1:cluster-a" } });
    await waitFor(() => expect(apiMock.vms).toHaveBeenLastCalledWith({ type: "cluster", towerId: 1, clusterId: "cluster-a" }));

    fireEvent.change(screen.getByLabelText("虚拟机页集群"), { target: { value: "all" } });
    expect(screen.getByLabelText("虚拟机页Tower")).toHaveValue("1");
    expect(screen.getByLabelText("虚拟机页集群")).toHaveValue("all");
    await waitFor(() => expect(apiMock.vms).toHaveBeenLastCalledWith({ type: "tower", towerId: 1 }));
    expect(apiMock.vms).toHaveBeenCalledWith({ type: "all" });
  });

  it("shows usage percentage for every vm from all volume data and highlights over 80 percent", async () => {
    apiMock.vms.mockResolvedValue([
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-1", vm: "VM One", cluster: "Cluster A" },
        value: 50
      },
      {
        metric: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-2", vm: "VM Two", cluster: "Cluster A" },
        value: 85
      }
    ]);
    apiMock.vmDetail.mockResolvedValue({ tower_id: 1, cluster_id: "cluster-a", vm_id: "vm-1", vm_name: "VM One", used_bytes: 50 });
    apiMock.vmTrend.mockResolvedValue({ vm_id: "vm-1", metric: "used", points: [] });
    apiMock.vmVolumes.mockResolvedValue({ vm_id: "vm-1", volumes: [] });
    apiMock.vmVolumesAll.mockResolvedValue([
      { tower_id: 1, cluster_id: "cluster-a", cluster_name: "Cluster A", vm_id: "vm-1", vm_name: "VM One", volumes: [{ volume_id: "vol-1", name: "Root", used_bytes: 50, size_bytes: 100 }] },
      { tower_id: 1, cluster_id: "cluster-a", cluster_name: "Cluster A", vm_id: "vm-2", vm_name: "VM Two", volumes: [{ volume_id: "vol-2", name: "Data", used_bytes: 85, size_bytes: 100 }] }
    ]);

    render(<VmsPage scope={{ type: "cluster", towerId: 1, clusterId: "cluster-a" }} selectedVmId="vm-1" />);

    const highUsage = await screen.findByText("已使用 85.0%");
    expect(highUsage).toHaveClass("over-limit");
  });
});
