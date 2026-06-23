import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

vi.mock("../components/ClusterCapacityChart", () => ({
  ClusterCapacityChart: ({
    clusters,
    rangeDays,
    onRangeDaysChange
  }: {
    clusters: Array<{ labels?: Record<string, string> }>;
    rangeDays: number;
    onRangeDaysChange: (days: 7 | 30 | 90 | 365 | 720) => void;
  }) => (
    <div data-testid="cluster-capacity-chart">
      <span data-testid="chart-range">{rangeDays}</span>
      <span data-testid="chart-cluster-name">chart:{clusters[0]?.labels?.cluster || "empty"}</span>
      {[7, 30, 90, 365, 720].map((days) => (
        <button key={days} type="button" onClick={() => onRangeDaysChange(days as 7 | 30 | 90 | 365 | 720)}>
          {days}天
        </button>
      ))}
    </div>
  )
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function reportWithCluster(clusterName: string, chartDays: number) {
  return {
    clusters: [
      {
        labels: { tower_id: "1", cluster_id: "cluster-a", cluster: clusterName },
        forecast: { status: "ok", slope_per_day: 1, current: 100, forecast_90d: 190, exhaustion_days: null },
        points: [[1764547200, 100]],
        total: 1000,
        warning: 900
      }
    ],
    fastest_growing_vms: [],
    day_fastest_growing_vms: [],
    month_fastest_growing_vms: [],
    day_new_vms: [],
    month_new_vms: [],
    cluster_growth_rate: { per_day: 1, per_month: 30, per_quarter: 90 },
    window_days: 30,
    chart_days: chartDays,
    growth_rate_window_days: 7,
    forecast_days: 90
  };
}

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

  it("ignores stale chart range responses when switching from 30 days to 7 days quickly", async () => {
    const initial = deferred<ReturnType<typeof reportWithCluster>>();
    const thirtyDays = deferred<ReturnType<typeof reportWithCluster>>();
    const sevenDays = deferred<ReturnType<typeof reportWithCluster>>();
    apiMock.report.mockImplementation((_scope, _periodDays, chartDays) => {
      if (chartDays === 365) return initial.promise;
      if (chartDays === 30) return thirtyDays.promise;
      if (chartDays === 7) return sevenDays.promise;
      return Promise.resolve(reportWithCluster(`${chartDays}天趋势`, chartDays));
    });

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

    await waitFor(() => expect(apiMock.report).toHaveBeenCalledWith(undefined, undefined, 365));
    fireEvent.click(screen.getByRole("button", { name: "30天" }));
    await waitFor(() => expect(apiMock.report).toHaveBeenCalledWith(undefined, undefined, 30));
    fireEvent.click(screen.getByRole("button", { name: "7天" }));
    await waitFor(() => expect(apiMock.report).toHaveBeenCalledWith(undefined, undefined, 7));

    await act(async () => {
      sevenDays.resolve(reportWithCluster("7天趋势", 7));
    });
    expect(screen.getByTestId("chart-range")).toHaveTextContent("7");
    expect(screen.getByTestId("chart-cluster-name")).toHaveTextContent("chart:7天趋势");

    await act(async () => {
      thirtyDays.resolve(reportWithCluster("30天趋势", 30));
    });

    await waitFor(() => {
      expect(screen.getByTestId("chart-range")).toHaveTextContent("7");
      expect(screen.getByTestId("chart-cluster-name")).toHaveTextContent("chart:7天趋势");
    });
    expect(screen.queryByText("chart:30天趋势")).not.toBeInTheDocument();
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
      forecast_days: 90,
      data_quality: {
        status: "warning",
        actual_data_window: { start_at: "2026-05-22T00:00:00+08:00", end_at: "2026-06-16T00:00:00+08:00", days: 25 },
        sample_sufficient: false,
        missing_collection_dates: ["2026-06-03"],
        incomplete_clusters: [{ tower: "Tower A", cluster: "Cluster A", reason: "prometheus_cluster_sample_missing" }],
        messages: ["当前报表存在样本不足、缺采或部分集群样本不完整。"]
      }
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
    await waitFor(() => expect(screen.getAllByText("Cluster A").length).toBeGreaterThan(0));
    const forecastCard = screen.getByRole("heading", { name: "集群预测报表" }).closest("section");
    expect(forecastCard).toBeTruthy();
    expect(within(forecastCard as HTMLElement).queryByText("数据质量需关注")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "数据质量摘要" })).not.toBeInTheDocument();
    const qualityCard = screen.getByText("数据质量需关注").closest("section");
    expect(qualityCard).toBeTruthy();
    expect(within(qualityCard as HTMLElement).getByText("数据质量需关注")).toBeInTheDocument();
    expect((qualityCard as HTMLElement).querySelectorAll(".report-quality-window")).toHaveLength(4);
    expect(within(qualityCard as HTMLElement).getByText("实际采集窗口")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("25 天")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("2026-05-22 至")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("2026-06-16")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("缺采 1 天")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("统计窗口存在缺采日期")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("样本不足")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("需结合实际窗口理解")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("不完整集群 1 个")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("Cluster A")).toHaveAttribute("title", "Cluster A");
    expect(screen.queryByText("Tower A / Cluster A")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "历史样本窗口" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "容量增长速率" })).toBeInTheDocument();
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

  it("renders vm names from the v0.5.1 top-level growth fields", async () => {
    const onSelectVm = vi.fn();
    apiMock.report.mockResolvedValue({
      clusters: [],
      fastest_growing_vms: [],
      day_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a" },
          vm_id: "vm-day-top-level",
          vm_name: "Top Level Day VM",
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 20,
          growth_ratio: 0.2
        }
      ],
      month_fastest_growing_vms: [],
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
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 1, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
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

    const row = await screen.findByRole("button", { name: "Top Level Day VM 20 B/天" });
    fireEvent.click(row);
    expect(onSelectVm).toHaveBeenCalledWith("vm-day-top-level", "Top Level Day VM");
    expect(screen.queryByText("vm-day-top-level")).not.toBeInTheDocument();
  });

  it("keeps report page usable when data quality is absent", async () => {
    apiMock.report.mockResolvedValue(reportWithCluster("Cluster A", 365));

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

    const statusLabel = await screen.findByText("数据质量需关注");
    expect(screen.queryByRole("heading", { name: "数据质量摘要" })).not.toBeInTheDocument();
    const qualityCard = statusLabel.closest("section");
    expect(qualityCard).toBeTruthy();
    expect(within(qualityCard as HTMLElement).getByText("数据质量需关注")).toBeInTheDocument();
    expect(within(qualityCard as HTMLElement).getByText("当前报表接口未返回数据质量字段，导出时将按未知状态兼容。")).toBeInTheDocument();
    expect(screen.getByText("Cluster A")).toBeInTheDocument();
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

  it("hides insufficient day and month growth samples and marks missing monthly collection days", async () => {
    apiMock.report.mockResolvedValue({
      clusters: [],
      fastest_growing_vms: [],
      day_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-day-short", vm: "Short Day VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 20,
          growth_ratio: 0.2,
          sample_span_days: 0.5
        },
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-day-ok", vm: "Full Day VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 30,
          growth_ratio: 0.3,
          sample_span_days: 1
        }
      ],
      month_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-month-short", vm: "Short Month VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 40,
          growth_ratio: 0.4,
          sample_span_days: 29.9
        },
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-month-ok", vm: "Full Month VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 50,
          growth_ratio: 0.5,
          sample_span_days: 30
        }
      ],
      day_new_vms: [],
      month_new_vms: [],
      cluster_growth_rate: { per_day: 0, per_month: 0, per_quarter: 0 },
      window_days: 30,
      chart_days: 365,
      growth_rate_window_days: 7,
      forecast_days: 90,
      data_quality: {
        status: "warning",
        sample_sufficient: true,
        missing_collection_dates: ["2026-06-02", "2026-06-08"],
        incomplete_clusters: []
      }
    });

    render(
      <ReportsPage
        summary={{
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 4, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
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

    const dayRow = await screen.findByRole("button", { name: "Full Day VM 30 B/天" });
    const monthRow = screen.getByRole("button", { name: "Full Month VM 50 B/月" });
    expect(screen.queryByText("Short Day VM")).not.toBeInTheDocument();
    expect(screen.queryByText("Short Month VM")).not.toBeInTheDocument();
    expect(screen.getByText("缺采 2 天", { selector: ".growth-missing-badge" })).toBeInTheDocument();
    expect(dayRow.querySelector("svg")).toBeTruthy();
    expect(monthRow.querySelector("svg")).toBeTruthy();
  });

  it("shows sample insufficient empty states for day and month growth cards", async () => {
    apiMock.report.mockResolvedValue({
      clusters: [],
      fastest_growing_vms: [],
      day_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-day-short", vm: "Short Day VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 20,
          growth_ratio: 0.2,
          sample_span_days: 0.5
        }
      ],
      month_fastest_growing_vms: [
        {
          labels: { tower_id: "1", cluster_id: "cluster-a", vm_id: "vm-month-short", vm: "Short Month VM" },
          forecast: { status: "ok", slope_per_day: 0, current: 1024 },
          growth_amount: 40,
          growth_ratio: 0.4,
          sample_span_days: 29.9
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
          kpis: { tower_count: 1, cluster_count: 1, vm_count: 2, used_bytes: 0, total_bytes: 0, used_ratio: 0 },
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

    expect(await screen.findByText("日样本不足")).toBeInTheDocument();
    expect(screen.getByText("月样本不足")).toBeInTheDocument();
    expect(screen.queryByText("Short Day VM")).not.toBeInTheDocument();
    expect(screen.queryByText("Short Month VM")).not.toBeInTheDocument();
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
