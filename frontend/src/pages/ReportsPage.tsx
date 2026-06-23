import { ArrowUpRight, CalendarClock, Download, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../components/Card";
import { ClusterCapacityChart } from "../components/ClusterCapacityChart";
import { api, formatBytes } from "../services/api";
import type { AppTask, DashboardScope, DashboardSummary, DataQuality, ForecastPayload, GrowthVmReport } from "../types";

const VM_ALERT_RATIO = 0.2;
const VM_ALERT_BYTES = 100 * 1024 ** 3;

interface ReportsPageProps {
  summary?: DashboardSummary | null;
  scope: DashboardScope;
  refreshKey?: number;
  onSelectVm: (vmId: string, vmName?: string) => void;
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
}

function scopedClusterValue(scope: DashboardScope): string {
  if (scope.type === "cluster") return `${scope.towerId}:${scope.clusterId}`;
  if (scope.type === "tower") return `tower:${scope.towerId}`;
  return "all";
}

function scopeFromClusterValue(value: string): DashboardScope | undefined {
  if (value === "all") return undefined;
  if (value.startsWith("tower:")) {
    const towerId = Number(value.slice("tower:".length));
    return Number.isFinite(towerId) ? { type: "tower", towerId } : undefined;
  }
  const separator = value.indexOf(":");
  if (separator <= 0) return undefined;
  const towerId = Number(value.slice(0, separator));
  const clusterId = value.slice(separator + 1);
  return Number.isFinite(towerId) && clusterId ? { type: "cluster", towerId, clusterId } : undefined;
}

function formatForecast(value?: number | null): string {
  return value == null ? "数据不足" : formatBytes(value);
}

function monthlyGrowth(value?: number | null): number {
  return (value || 0) * 30;
}

function quarterlyGrowth(value?: number | null): number {
  return (value || 0) * 90;
}

export function ReportsPage({ summary, scope, refreshKey = 0, onSelectVm, addTask, updateTask }: ReportsPageProps) {
  const [report, setReport] = useState<ForecastPayload | null>(null);
  const [selectedCluster, setSelectedCluster] = useState(scopedClusterValue(scope));
  const [dayGrowthSort, setDayGrowthSort] = useState<GrowthSortMode>("amount");
  const [monthGrowthSort, setMonthGrowthSort] = useState<GrowthSortMode>("amount");
  const [exporting, setExporting] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [exportPeriodDays, setExportPeriodDays] = useState(30);
  const [chartDays, setChartDays] = useState<ChartRangeDays>(365);
  const [exportError, setExportError] = useState("");
  const reportRequestSeq = useRef(0);
  const clusterOptions = useMemo(
    () =>
      (summary?.towers || []).flatMap((tower) =>
        [
          {
            value: `tower:${tower.id}`,
            label: tower.name,
            scope: { type: "tower", towerId: tower.id } as DashboardScope
          },
          ...tower.clusters.map((cluster) => ({
            value: `${tower.id}:${cluster.cluster_id}`,
            label: `${tower.name} / ${cluster.name || cluster.cluster_id}`,
            scope: { type: "cluster", towerId: tower.id, clusterId: cluster.cluster_id } as DashboardScope
          }))
        ]
      ),
    [summary?.towers]
  );
  const reportScope = useMemo(() => scopeFromClusterValue(selectedCluster), [selectedCluster]);

  useEffect(() => {
    setSelectedCluster(scopedClusterValue(scope));
  }, [scope]);

  useEffect(() => {
    const requestSeq = reportRequestSeq.current + 1;
    reportRequestSeq.current = requestSeq;
    api
      .report(reportScope, undefined, chartDays)
      .then((payload) => {
        if (reportRequestSeq.current === requestSeq) {
          setReport(payload);
        }
      })
      .catch(() => {
        if (reportRequestSeq.current === requestSeq) {
          setReport(null);
        }
      });
  }, [chartDays, refreshKey, reportScope]);

  async function handleExportBundle() {
    setExporting(true);
    setExportError("");
    const id = `report-export-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    addTask({ id, kind: "export", title: "导出预测报表", detail: "正在生成 Word 和 Excel", status: "running", severity: "info", unhandled: true, progress: 10 });
    try {
      updateTask(id, { progress: 35, detail: "正在生成 Word/Excel" });
      const result = await api.exportReportBundle(reportScope, exportPeriodDays, id);
      const links = result.links?.length ? result.links : result.files;
      updateTask(id, { progress: 82, detail: "报表已生成，正在准备下载", links });
      await Promise.all(
        links.map(async (link) => {
          const downloaded = await api.downloadSavedExport(link.url);
          saveBlob(downloaded.blob, link.filename || downloaded.filename || fallbackExportFilename(link.label === "Excel" ? "excel" : "word", selectedCluster, exportPeriodDays));
        })
      );
      updateTask(id, {
        status: "succeeded",
        severity: "info",
        unhandled: true,
        progress: 100,
        detail: result.message || "报表已生成，可从任务下载",
        links
      });
      setExportDialogOpen(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : "导出失败，请稍后重试。";
      updateTask(id, { status: "failed", severity: "warning", unhandled: true, progress: 100, detail: message });
      setExportError(message);
    } finally {
      setExporting(false);
    }
  }

  const rawDayGrowthVms = report?.day_fastest_growing_vms || report?.fastest_growing_vms || [];
  const rawMonthGrowthVms = report?.month_fastest_growing_vms || [];
  const dayTopVms = sortGrowthReports(rawDayGrowthVms.filter((item) => hasSampleSpan(item, 1)), dayGrowthSort).slice(0, 50);
  const monthTopVms = sortGrowthReports(rawMonthGrowthVms.filter((item) => hasSampleSpan(item, 30)), monthGrowthSort).slice(0, 50);
  const dayGrowthEmptyText = rawDayGrowthVms.length && !dayTopVms.length ? "日样本不足" : "暂无增长数据";
  const monthGrowthEmptyText = rawMonthGrowthVms.length && !monthTopVms.length ? "月样本不足" : "暂无增长数据";
  const monthMissingCollectionDays = report?.data_quality?.missing_collection_dates?.length ?? 0;
  const showMonthMissingBadge = monthTopVms.length > 0 && monthMissingCollectionDays > 0;
  const dayNewVms = (report?.day_new_vms || []).slice(0, 20);
  const monthNewVms = (report?.month_new_vms || []).slice(0, 20);
  const clusterGrowthRate = clusterGrowthRates(report);
  const selectedClusterLabel = selectedCluster === "all" ? "全部集群" : clusterOptions.find((item) => item.value === selectedCluster)?.label || "集群";
  const dataQuality = report?.data_quality;

  return (
    <div className="report-layout">
      <div className="report-top-row">
        <Card
          title="集群预测报表"
          subtitle={`基于最近 ${report?.window_days || 30} 天数据，预测 ${report?.forecast_days || 90} 天后容量`}
          className="report-forecast-card"
          action={
            <div className="report-actions">
              <label className="report-cluster-select">
                <span>集群</span>
                <select value={selectedCluster} onChange={(event) => setSelectedCluster(event.target.value)}>
                  <option value="all">全部集群</option>
                  {clusterOptions.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <button className="secondary-button compact export-button" type="button" onClick={() => setExportDialogOpen(true)} disabled={exporting}>
                <Download size={14} />
                {exporting ? "导出中" : "导出"}
              </button>
            </div>
          }
        >
          {exportError && <div className="inline-error">{exportError}</div>}
          <div className="report-list">
            {report?.clusters?.length ? (
              report.clusters.map((item) => (
                <div className="report-row" key={item.labels.cluster_id}>
                  <div>
                    <strong>{item.labels.cluster || item.labels.cluster_id}</strong>
                    <span>{item.forecast.status === "ok" ? "趋势正常" : "数据不足"}</span>
                  </div>
                  <div className="report-numbers">
                    <span>当前 {formatBytes(item.forecast.current)}</span>
                    <span>90 天后 {formatForecast(item.forecast.forecast_90d)}</span>
                    <span>预计存储耗尽</span>
                    <strong className={isQuarterRiskExhaustion(item.forecast.exhaustion_days) ? "exhaustion-days-risk" : undefined}>
                      {formatExhaustionDays(item.forecast.exhaustion_days)}
                    </strong>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">暂无报表数据</div>
            )}
          </div>
        </Card>

        <div className="report-side-stack">
          <Card title="历史样本窗口" className="report-side-card report-kpi-card">
            <div className="forecast-window compact-forecast-window">
              <CalendarClock size={30} />
              <strong>{report?.window_days || 30} 天</strong>
              <span>用于预测报表计算</span>
            </div>
          </Card>

          <Card title="容量增长速率" subtitle={`${report?.growth_rate_window_days || 7} 天平均`} className="report-side-card report-kpi-card">
            <div className="forecast-window compact-forecast-window growth-window">
              <TrendingUp size={30} />
              <strong>{formatBytes(clusterGrowthRate.perDay)}/天</strong>
              <span>{formatBytes(clusterGrowthRate.perMonth)}/月</span>
              <span>{formatBytes(clusterGrowthRate.perQuarter)}/季度</span>
            </div>
          </Card>

          <Card className={`report-side-card report-quality-summary-card ${dataQualityClass(dataQuality?.status || "unknown")}`}>
            <DataQualitySummary quality={dataQuality} />
          </Card>
        </div>
      </div>

      <Card title="集群容量趋势" subtitle="实际容量、预测趋势与容量阈值" className="cluster-chart-card">
        <ClusterCapacityChart clusters={report?.clusters || []} title={selectedClusterLabel} rangeDays={chartDays} onRangeDaysChange={setChartDays} />
      </Card>

      {exportDialogOpen && (
        <div className="modal-backdrop" role="presentation" onClick={() => setExportDialogOpen(false)}>
          <div className="export-dialog" role="dialog" aria-modal="true" aria-labelledby="export-dialog-title" onClick={(event) => event.stopPropagation()}>
            <div className="export-dialog-head">
              <div>
                <strong id="export-dialog-title">导出报表</strong>
                <span>选择增长统计时间区间，将同时导出 Word 和 Excel。{dataQuality ? `当前${dataQualityStatusLabel(dataQuality.status)}，导出文件会包含数据质量说明。` : ""}</span>
              </div>
            </div>
            <div className="period-options" role="radiogroup" aria-label="导出时间区间">
              {EXPORT_PERIOD_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={exportPeriodDays === option.value ? "active" : ""}
                  onClick={() => setExportPeriodDays(option.value)}
                  disabled={exporting}
                >
                  {option.label}
                </button>
              ))}
            </div>
            {exportError && <div className="inline-error">{exportError}</div>}
            <div className="export-dialog-actions">
              <button className="secondary-button" type="button" onClick={() => setExportDialogOpen(false)}>
                取消
              </button>
              <button className="primary-button" type="button" onClick={handleExportBundle} disabled={exporting}>
                <Download size={15} />
                {exporting ? "导出中" : "导出"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="report-vm-row">
        <Card
          title="日增长最快 VM"
          subtitle={`${summary?.kpis.vm_count ?? 0} 台中 ${dayTopVms.length || 0} 台增长`}
          action={<GrowthSortTabs value={dayGrowthSort} onChange={setDayGrowthSort} />}
        >
          <div className="list-table growth-scroll auto-scrollbar">
            {dayTopVms.map((item) => (
              <button
                className={isAlertGrowthVm(item) ? "table-row clickable growth-alert-row" : "table-row clickable"}
                key={item.labels.vm_id}
                type="button"
                onClick={() => onSelectVm(item.labels.vm_id, item.labels.vm || item.labels.vm_id)}
              >
                <span>{item.labels.vm || item.labels.vm_id}</span>
                <strong className="growth-strong">
                  <ArrowUpRight size={14} />
                  {formatGrowthValue(item, dayGrowthSort, "天")}
                </strong>
              </button>
            ))}
            {!dayTopVms.length && <div className="empty-state">{dayGrowthEmptyText}</div>}
          </div>
        </Card>

        <Card
          title="月增长最快 VM"
          subtitle={`${summary?.kpis.vm_count ?? 0} 台中 ${monthTopVms.length || 0} 台增长`}
          action={
            <div className="growth-card-actions">
              {showMonthMissingBadge && <span className="growth-missing-badge">缺采 {monthMissingCollectionDays} 天</span>}
              <GrowthSortTabs value={monthGrowthSort} onChange={setMonthGrowthSort} />
            </div>
          }
        >
          <div className="list-table growth-scroll auto-scrollbar">
            {monthTopVms.map((item) => (
              <button
                className={isAlertGrowthVm(item) ? "table-row clickable growth-alert-row" : "table-row clickable"}
                key={item.labels.vm_id}
                type="button"
                onClick={() => onSelectVm(item.labels.vm_id, item.labels.vm || item.labels.vm_id)}
              >
                <span>{item.labels.vm || item.labels.vm_id}</span>
                <strong className="growth-strong">
                  <ArrowUpRight size={14} />
                  {formatGrowthValue(item, monthGrowthSort, "月")}
                </strong>
              </button>
            ))}
            {!monthTopVms.length && <div className="empty-state">{monthGrowthEmptyText}</div>}
          </div>
        </Card>

        <VmListCard
          title="本日新建 VM"
          subtitle={`${dayNewVms.length || 0} 台本日新建`}
          items={dayNewVms}
          emptyText="暂无本日新建 VM"
          renderValue={(item) => formatBytes(item.forecast.current)}
          onSelectVm={onSelectVm}
        />

        <VmListCard
          title="本月新建 VM"
          subtitle={`${monthNewVms.length || 0} 台本月新建`}
          items={monthNewVms}
          emptyText="暂无本月新建 VM"
          renderValue={(item) => formatBytes(item.forecast.current)}
          onSelectVm={onSelectVm}
        />
      </div>
    </div>
  );
}

type GrowthSortMode = "amount" | "ratio";
type ChartRangeDays = 7 | 30 | 90 | 365 | 720;

const EXPORT_PERIOD_OPTIONS = [
  { value: 7, label: "近 7 天" },
  { value: 14, label: "近 14 天" },
  { value: 30, label: "近 30 天" },
  { value: 90, label: "近 90 天" },
  { value: 180, label: "近 180 天" },
  { value: 365, label: "近 365 天" }
] as const;

function clusterGrowthRates(report: ForecastPayload | null): { perDay: number; perMonth: number; perQuarter: number } {
  const perDay =
    report?.cluster_growth_rate?.per_day ??
    report?.cluster_growth_rate_per_day ??
    report?.clusters?.reduce((total, item) => total + Math.max(0, item.forecast.slope_per_day || 0), 0) ??
    0;
  return {
    perDay,
    perMonth: report?.cluster_growth_rate?.per_month ?? monthlyGrowth(perDay),
    perQuarter: report?.cluster_growth_rate?.per_quarter ?? quarterlyGrowth(perDay)
  };
}

function GrowthSortTabs({ value, onChange }: { value: GrowthSortMode; onChange: (value: GrowthSortMode) => void }) {
  return (
    <div className="sort-tabs compact-tabs" aria-label="增长排序">
      <button type="button" className={value === "amount" ? "active" : ""} onClick={() => onChange("amount")}>
        增长量
      </button>
      <button type="button" className={value === "ratio" ? "active" : ""} onClick={() => onChange("ratio")}>
        增长率
      </button>
    </div>
  );
}

function DataQualitySummary({ quality }: { quality?: DataQuality }) {
  const status = quality?.status || "unknown";
  const missingCount = quality?.missing_collection_dates?.length ?? 0;
  const incompleteCount = quality?.incomplete_clusters?.length ?? 0;
  const windowInfo = dataQualityWindowInfo(quality);
  const incompleteClusters = formatIncompleteClusterNames(quality);
  return (
    <div className={`report-quality-summary ${dataQualityClass(status)}`}>
      <div className="report-quality-summary-head">
        <strong>{dataQualityStatusLabel(status)}</strong>
        <span>{dataQualityMessage(quality)}</span>
      </div>
      <div className="report-quality-summary-grid">
        <div className="report-quality-window">
          <strong>实际采集窗口</strong>
          <span>{windowInfo.daysLabel}</span>
          <small>{windowInfo.startLabel}</small>
          <small>{windowInfo.endLabel}</small>
        </div>
        <div className="report-quality-window">
          <strong>缺采 {missingCount} 天</strong>
          <small>{missingCount > 0 ? "统计窗口存在缺采日期" : "未发现缺采日期"}</small>
        </div>
        <div className="report-quality-window">
          <strong>样本{dataQualitySampleLabel(quality)}</strong>
          <small>{dataQualitySampleHint(quality)}</small>
        </div>
        <div className="report-quality-window">
          <strong>不完整集群 {incompleteCount} 个</strong>
          <div className="report-quality-clusters">
            {incompleteClusters.map((cluster, index) => (
              <small title={cluster} key={`${cluster}-${index}`}>
                {cluster}
              </small>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function dataQualityClass(status: string): string {
  if (status === "critical") return "critical";
  if (status === "warning") return "warning";
  if (status === "ok") return "ok";
  return "unknown";
}

function dataQualityStatusLabel(status?: string): string {
  if (status === "ok") return "数据质量正常";
  return "数据质量需关注";
}

function dataQualityMessage(quality?: DataQuality): string {
  if (!quality) return "当前报表接口未返回数据质量字段，导出时将按未知状态兼容。";
  if (quality.messages?.length) return quality.messages[0];
  if (quality.status === "ok") return "当前报表范围内未发现明显数据缺口。";
  if (quality.status === "critical") return "趋势和预测结果仅供排障参考，不建议直接作为容量决策依据。";
  if (quality.status === "warning") return "趋势与预测结论需结合实际采集窗口理解。";
  return "当前报表未包含完整数据质量检查结果。";
}

function dataQualityWindowInfo(quality?: DataQuality): { daysLabel: string; startLabel: string; endLabel: string } {
  const window = quality?.actual_data_window;
  if (!window?.start_at || !window?.end_at) {
    return { daysLabel: "未知", startLabel: "暂无开始时间", endLabel: "暂无结束时间" };
  }
  return {
    daysLabel: window.days ? `${window.days} 天` : "未知",
    startLabel: `${window.start_at.slice(0, 10)} 至`,
    endLabel: window.end_at.slice(0, 10)
  };
}

function dataQualitySampleLabel(quality?: DataQuality): string {
  if (typeof quality?.sample_sufficient !== "boolean") return "未知";
  return quality.sample_sufficient ? "足够" : "不足";
}

function dataQualitySampleHint(quality?: DataQuality): string {
  if (typeof quality?.sample_sufficient !== "boolean") return "未返回样本状态";
  return quality.sample_sufficient ? "满足当前统计窗口" : "需结合实际窗口理解";
}

function formatIncompleteClusterNames(quality?: DataQuality): string[] {
  const clusters = quality?.incomplete_clusters || [];
  if (!clusters.length) return ["未发现不完整集群"];
  return clusters.map((item, index) => item.cluster || item.cluster_id || `未知集群 ${index + 1}`);
}

function sortGrowthReports(items: GrowthVmReport[], mode: GrowthSortMode): GrowthVmReport[] {
  return [...items].sort((left, right) => growthSortValue(right, mode) - growthSortValue(left, mode));
}

function hasSampleSpan(item: GrowthVmReport, minDays: number): boolean {
  return item.sample_span_days == null || item.sample_span_days >= minDays;
}

function VmListCard({
  title,
  subtitle,
  items,
  emptyText,
  renderValue,
  onSelectVm
}: {
  title: string;
  subtitle?: string;
  items: GrowthVmReport[];
  emptyText: string;
  renderValue: (item: GrowthVmReport) => string;
  onSelectVm: (vmId: string, vmName?: string) => void;
}) {
  return (
    <Card title={title} subtitle={subtitle}>
      <div className="list-table growth-scroll auto-scrollbar">
        {items.map((item) => (
          <button
            className="table-row clickable"
            key={`${item.labels.tower_id || ""}-${item.labels.cluster_id || ""}-${item.labels.vm_id}`}
            type="button"
            onClick={() => onSelectVm(item.labels.vm_id, item.labels.vm || item.labels.vm_id)}
          >
            <span>{item.labels.vm || item.labels.vm_id}</span>
            <strong>{renderValue(item)}</strong>
          </button>
        ))}
        {!items.length && <div className="empty-state">{emptyText}</div>}
      </div>
    </Card>
  );
}

function growthSortValue(item: GrowthVmReport, mode: GrowthSortMode): number {
  if (mode === "ratio") return item.growth_ratio ?? 0;
  return item.growth_amount ?? item.forecast.slope_per_day ?? 0;
}

function formatGrowthValue(item: GrowthVmReport, mode: GrowthSortMode, unit: string): string {
  if (mode === "ratio") return formatPercent(item.growth_ratio);
  return `${formatBytes(item.growth_amount ?? (unit === "月" ? monthlyGrowth(item.forecast.slope_per_day) : item.forecast.slope_per_day))}/${unit}`;
}

function isAlertGrowthVm(item: GrowthVmReport): boolean {
  return (item.growth_ratio ?? 0) > VM_ALERT_RATIO && (item.growth_amount ?? 0) > VM_ALERT_BYTES;
}

function formatExhaustionDays(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "未触发";
  return `${Math.round(value)} 天`;
}

function isQuarterRiskExhaustion(value?: number | null): boolean {
  return value != null && Number.isFinite(value) && value < 90;
}

function formatPercent(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(value >= 1 ? 0 : 1)}%`;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function fallbackExportFilename(format: "word" | "excel", selectedCluster: string, periodDays: number): string {
  const date = new Date();
  const dateSlug = `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}`;
  const timeSlug = `${String(date.getHours()).padStart(2, "0")}${String(date.getMinutes()).padStart(2, "0")}${String(date.getSeconds()).padStart(2, "0")}`;
  const scopeSlug = selectedCluster === "all" ? "all" : selectedCluster.replace(/[^a-zA-Z0-9_-]+/g, "-");
  return `storage-forecast-${scopeSlug}-${dateSlug}-${timeSlug}-${periodDays}d.${format === "word" ? "docx" : "xlsx"}`;
}
