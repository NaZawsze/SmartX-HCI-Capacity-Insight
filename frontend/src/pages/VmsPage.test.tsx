import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
    expect(apiMock.vmVolumesAll).not.toHaveBeenCalled();
    expect(await screen.findByText("Root")).toBeInTheDocument();
  });
});
