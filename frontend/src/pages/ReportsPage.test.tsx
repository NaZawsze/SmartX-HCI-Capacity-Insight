import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportsPage } from "./ReportsPage";

const apiMock = vi.hoisted(() => ({
  report: vi.fn(),
  exportReport: vi.fn(),
  exportReportBundle: vi.fn(),
  downloadSavedExport: vi.fn()
}));

vi.mock("../services/api", async () => ({
  api: apiMock,
  formatBytes: (value: number | null | undefined) => `${value ?? 0} B`
}));

describe("ReportsPage", () => {
  beforeEach(() => {
    apiMock.report.mockReset();
    apiMock.exportReport.mockReset();
    apiMock.exportReportBundle.mockReset();
    apiMock.downloadSavedExport.mockReset();
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();
  });

  it("renders v2 report contract and lets vm rows jump to the vm page", async () => {
    const onSelectVm = vi.fn();
    apiMock.report.mockResolvedValue({
      clusters: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", cluster: "Cluster A" },
          forecast: { status: "ok", slope_per_day: 10, current: 190, forecast_90d: 1090, exhaustion_days: 8 },
          points: [],
          total: 1000,
          warning: 900
        },
        {
          labels: { tower_id: "1", cluster_id: "cluster-b", cluster: "Cluster B" },
          forecast: { status: "ok", slope_per_day: 0, current: 100, forecast_90d: 100, exhaustion_days: null },
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
    expect(screen.getByText("8 天")).toHaveClass("exhaustion-days-risk");
    expect(screen.getByText("未触发")).not.toHaveClass("exhaustion-days-risk");
    expect(screen.getByText("90 天后 1090 B")).toBeInTheDocument();
    expect(screen.getByText("日增长最快 VM")).toBeInTheDocument();
    expect(screen.getByText("月增长最快 VM")).toBeInTheDocument();
    expect(screen.getByText("本日新建 VM")).toBeInTheDocument();
    expect(screen.getByText("本月新建 VM")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Month VM"));
    expect(onSelectVm).toHaveBeenCalledWith("vm-month", "Month VM");
  });

  it("marks day and month growth vm rows as alerts using the export report threshold", async () => {
    apiMock.report.mockResolvedValue({
      clusters: [],
      fastest_growing_vms: [],
      day_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-alert-day", vm: "Alert Day VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 120 * 1024 ** 3,
          growth_ratio: 0.25
        },
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-normal-day", vm: "Normal Day VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 99 * 1024 ** 3,
          growth_ratio: 0.25
        }
      ],
      month_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-alert-month", vm: "Alert Month VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 160 * 1024 ** 3,
          growth_ratio: 0.3
        }
      ],
      day_new_vms: [],
      month_new_vms: [],
      cluster_growth_rate: { per_day: 0, per_month: 0, per_quarter: 0 },
      window_days: 30,
      chart_days: 365,
      growth_rate_window_days: 7,
      forecast_days: 90
    });

    render(
      <ReportsPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 3, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSelectVm={vi.fn()}
        addTask={vi.fn()}
        updateTask={vi.fn()}
      />
    );

    const alertDay = await screen.findByRole("button", { name: "Alert Day VM 128849018880 B/天" });
    const normalDay = screen.getByRole("button", { name: "Normal Day VM 106300440576 B/天" });
    const alertMonth = screen.getByRole("button", { name: "Alert Month VM 171798691840 B/月" });

    expect(alertDay).toHaveClass("growth-alert-row");
    expect(alertMonth).toHaveClass("growth-alert-row");
    expect(normalDay).not.toHaveClass("growth-alert-row");
  });

  it("exports word and excel through one bundle task", async () => {
    const addTask = vi.fn();
    const updateTask = vi.fn();
    apiMock.report.mockResolvedValue({
      clusters: [],
      fastest_growing_vms: [],
      day_fastest_growing_vms: [],
      month_fastest_growing_vms: [],
      day_new_vms: [],
      month_new_vms: [],
      cluster_growth_rate: { per_day: 0, per_month: 0, per_quarter: 0 },
      window_days: 30,
      chart_days: 365,
      growth_rate_window_days: 7,
      forecast_days: 90
    });
    apiMock.exportReportBundle.mockResolvedValue({
      task_id: "report-bundle-1",
      status: "success",
      files: [
        { label: "Word", filename: "storage-forecast-all-20260606-120000-30d.docx", url: "/api/admin/exports/reports/word.docx", path: "/data/exports/reports/word.docx" },
        { label: "Excel", filename: "storage-forecast-all-20260606-120000-30d.xlsx", url: "/api/admin/exports/reports/excel.xlsx", path: "/data/exports/reports/excel.xlsx" }
      ],
      links: [
        { label: "Word", filename: "storage-forecast-all-20260606-120000-30d.docx", url: "/api/admin/exports/reports/word.docx", path: "/data/exports/reports/word.docx" },
        { label: "Excel", filename: "storage-forecast-all-20260606-120000-30d.xlsx", url: "/api/admin/exports/reports/excel.xlsx", path: "/data/exports/reports/excel.xlsx" }
      ],
      message: "Word 和 Excel 报表已生成"
    });
    apiMock.downloadSavedExport.mockResolvedValue({ blob: new Blob(["ok"]), filename: "report.docx" });

    render(
      <ReportsPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 0, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSelectVm={vi.fn()}
        addTask={addTask}
        updateTask={updateTask}
      />
    );

    fireEvent.click(await screen.findByRole("button", { name: "导出" }));
    const exportButtons = screen.getAllByRole("button", { name: "导出" });
    fireEvent.click(exportButtons[exportButtons.length - 1]);

    await waitFor(() => expect(apiMock.exportReportBundle).toHaveBeenCalledTimes(1));
    expect(apiMock.exportReportBundle).toHaveBeenCalledWith(undefined, 30, expect.stringMatching(/^report-export-/));
    expect(apiMock.exportReport).not.toHaveBeenCalled();
    expect(addTask).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "export",
        title: "导出预测报表",
        status: "running",
        severity: "info",
        unhandled: true,
        progress: 10
      })
    );
    await waitFor(() =>
      expect(updateTask).toHaveBeenLastCalledWith(
        expect.any(String),
        expect.objectContaining({
          status: "succeeded",
          severity: "info",
          unhandled: true,
          progress: 100,
          links: expect.arrayContaining([
            expect.objectContaining({ label: "Word" }),
            expect.objectContaining({ label: "Excel" })
          ])
        })
      )
    );
  });

  it("keeps the export dialog closable while the bundle task is running", async () => {
    apiMock.report.mockResolvedValue({
      clusters: [],
      fastest_growing_vms: [],
      day_fastest_growing_vms: [],
      month_fastest_growing_vms: [],
      day_new_vms: [],
      month_new_vms: [],
      cluster_growth_rate: { per_day: 0, per_month: 0, per_quarter: 0 },
      window_days: 30,
      chart_days: 365,
      growth_rate_window_days: 7,
      forecast_days: 90
    });
    apiMock.exportReportBundle.mockImplementation(
      () =>
        new Promise(() => {
          // Keep the request pending so the dialog is still in its exporting state.
        })
    );

    render(
      <ReportsPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 0, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
          top_vms: [],
          clusters: [],
          towers: []
        }}
        scope={{ type: "all" }}
        onSelectVm={vi.fn()}
        addTask={vi.fn()}
        updateTask={vi.fn()}
      />
    );

    fireEvent.click(await screen.findByRole("button", { name: "导出" }));
    const exportButtons = screen.getAllByRole("button", { name: "导出" });
    fireEvent.click(exportButtons[exportButtons.length - 1]);

    await waitFor(() => expect(screen.getAllByText("导出中").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "导出报表" })).not.toBeInTheDocument();
    });
  });
});
