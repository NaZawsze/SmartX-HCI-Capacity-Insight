import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReportsPage } from "./ReportsPage";

const apiMock = vi.hoisted(() => ({
  report: vi.fn(),
  exportReport: vi.fn()
}));

vi.mock("../services/api", async () => ({
  api: apiMock,
  formatBytes: (value: number | null | undefined) => `${value ?? 0} B`
}));

describe("ReportsPage", () => {
  it("renders v2 report contract and lets vm rows jump to the vm page", async () => {
    const onSelectVm = vi.fn();
    apiMock.report.mockResolvedValue({
      clusters: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", cluster: "Cluster A" },
          forecast: { status: "ok", slope_per_day: 10, current: 190, forecast_90d: 1090, exhaustion_days: null },
          points: [],
          total: 1000,
          warning: 900
        }
      ],
      fastest_growing_vms: [],
      day_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-day", vm: "Day VM" },
          forecast: { status: "ok", slope_per_day: 2, current: 120 },
          growth_amount: 20,
          growth_ratio: 0.2
        }
      ],
      month_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-month", vm: "Month VM" },
          forecast: { status: "ok", slope_per_day: 4, current: 240 },
          growth_amount: 120,
          growth_ratio: 0.5,
          sample_span_days: 31
        }
      ],
      day_new_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-new-day", vm: "New Day VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 10 },
          first_seen_at: "2026-06-06T01:00:00+08:00"
        }
      ],
      month_new_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-new-month", vm: "New Month VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 30 },
          first_seen_at: "2026-06-01T01:00:00+08:00"
        }
      ],
      cluster_growth_rate: { per_day: 10, per_month: 300, per_quarter: 900 },
      window_days: 30,
      chart_days: 365,
      growth_rate_window_days: 7,
      forecast_days: 90
    });

    render(
      <ReportsPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 4, used_bytes: 190, total_bytes: 1000, used_ratio: 0.19 },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSelectVm={onSelectVm}
        addTask={vi.fn()}
        updateTask={vi.fn()}
      />
    );

    await waitFor(() => expect(apiMock.report).toHaveBeenCalledWith(undefined, undefined, 365));
    expect(await screen.findByText("Cluster A")).toBeInTheDocument();
    expect(screen.getByText("90 天后 1090 B")).toBeInTheDocument();
    expect(screen.getByText("日增长最快 VM")).toBeInTheDocument();
    expect(screen.getByText("月增长最快 VM")).toBeInTheDocument();
    expect(screen.getByText("本日新建 VM")).toBeInTheDocument();
    expect(screen.getByText("本月新建 VM")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Month VM"));
    expect(onSelectVm).toHaveBeenCalledWith("vm-month", "Month VM");
  });
});
