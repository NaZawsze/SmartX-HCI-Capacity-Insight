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
    const allVolumes = await screen.findByLabelText("所有虚拟卷");
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
