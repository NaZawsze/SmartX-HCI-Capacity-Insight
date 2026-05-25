import { CalendarClock, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { ClusterCapacityChart } from "../components/ClusterCapacityChart";
import { api, formatBytes } from "../services/api";
import type { DashboardScope, DashboardSummary, ForecastPayload, GrowthVmReport } from "../types";

interface ReportsPageProps {
  summary?: DashboardSummary | null;
  scope: DashboardScope;
  refreshKey?: number;
  onSelectVm: (vmId: string, vmName?: string) => void;
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

export function ReportsPage({ summary, scope, refreshKey = 0, onSelectVm }: ReportsPageProps) {
  const [report, setReport] = useState<ForecastPayload | null>(null);
  const [selectedCluster, setSelectedCluster] = useState(scopedClusterValue(scope));
  const [dayGrowthSort, setDayGrowthSort] = useState<GrowthSortMode>("amount");
  const [monthGrowthSort, setMonthGrowthSort] = useState<GrowthSortMode>("amount");
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
    api.report(reportScope).then(setReport).catch(() => setReport(null));
  }, [refreshKey, reportScope]);

  const dayTopVms = sortGrowthReports(report?.day_fastest_growing_vms || report?.fastest_growing_vms || [], dayGrowthSort).slice(0, 50);
  const monthTopVms = sortGrowthReports(report?.month_fastest_growing_vms || [], monthGrowthSort).slice(0, 50);
  const clusterGrowthRate = totalClusterGrowthRate(report);
  const selectedClusterLabel = selectedCluster === "all" ? "全部集群" : clusterOptions.find((item) => item.value === selectedCluster)?.label || "集群";

  return (
    <div className="report-layout">
      <div className="report-top-row">
        <Card
          title="集群预测报表"
          subtitle={`基于最近 ${report?.window_days || 30} 天数据，预测 ${report?.forecast_days || 60} 天后容量`}
          className="report-forecast-card"
          action={
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
          }
        >
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
                    <span>60 天后 {formatForecast(item.forecast.forecast_60d)}</span>
                    <strong>{item.forecast.exhaustion_days ? `${Math.round(item.forecast.exhaustion_days)} 天` : "未触发"}</strong>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">暂无报表数据</div>
            )}
          </div>
        </Card>

        <Card title="预测窗口">
          <div className="forecast-window">
            <CalendarClock size={44} />
            <strong>{report?.window_days || 30} 天</strong>
            <span>趋势样本窗口</span>
          </div>
        </Card>

        <Card title="容量增长速率">
          <div className="forecast-window growth-window">
            <TrendingUp size={44} />
            <strong>{formatBytes(clusterGrowthRate)}/天</strong>
            <span>{formatBytes(monthlyGrowth(clusterGrowthRate))}/月</span>
          </div>
        </Card>
      </div>

      <Card title="集群容量趋势" subtitle="实际容量、预测趋势与容量阈值" className="cluster-chart-card">
        <ClusterCapacityChart clusters={report?.clusters || []} title={selectedClusterLabel} />
      </Card>

      <div className="report-vm-row">
        <Card title="日 Top 增长 VM" action={<GrowthSortTabs value={dayGrowthSort} onChange={setDayGrowthSort} />}>
          <div className="list-table growth-scroll">
            {dayTopVms.map((item) => (
              <button
                className="table-row clickable"
                key={item.labels.vm_id}
                type="button"
                onClick={() => onSelectVm(item.labels.vm_id, item.labels.vm || item.labels.vm_id)}
              >
                <span>{item.labels.vm || item.labels.vm_id}</span>
                <strong>{formatGrowthValue(item, dayGrowthSort, "天")}</strong>
              </button>
            ))}
            {!dayTopVms.length && <div className="empty-state">暂无增长数据</div>}
          </div>
        </Card>

        <Card title="月 Top 增长 VM" action={<GrowthSortTabs value={monthGrowthSort} onChange={setMonthGrowthSort} />}>
          <div className="list-table growth-scroll">
            {monthTopVms.map((item) => (
              <button
                className="table-row clickable"
                key={item.labels.vm_id}
                type="button"
                onClick={() => onSelectVm(item.labels.vm_id, item.labels.vm || item.labels.vm_id)}
              >
                <span>{item.labels.vm || item.labels.vm_id}</span>
                <strong>{formatGrowthValue(item, monthGrowthSort, "月")}</strong>
              </button>
            ))}
            {!monthTopVms.length && <div className="empty-state">暂无增长数据</div>}
          </div>
        </Card>
      </div>
    </div>
  );
}

type GrowthSortMode = "amount" | "ratio";

function totalClusterGrowthRate(report: ForecastPayload | null): number {
  if (report?.cluster_growth_rate_per_day != null) return report.cluster_growth_rate_per_day;
  if (!report?.clusters?.length) return 0;
  return report.clusters.reduce((total, item) => total + Math.max(0, item.forecast.slope_per_day || 0), 0);
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

function sortGrowthReports(items: GrowthVmReport[], mode: GrowthSortMode): GrowthVmReport[] {
  return [...items].sort((left, right) => growthSortValue(right, mode) - growthSortValue(left, mode));
}

function growthSortValue(item: GrowthVmReport, mode: GrowthSortMode): number {
  if (mode === "ratio") return item.growth_ratio ?? 0;
  return item.growth_amount ?? item.forecast.slope_per_day ?? 0;
}

function formatGrowthValue(item: GrowthVmReport, mode: GrowthSortMode, unit: string): string {
  if (mode === "ratio") return formatPercent(item.growth_ratio);
  return `${formatBytes(item.growth_amount ?? (unit === "月" ? monthlyGrowth(item.forecast.slope_per_day) : item.forecast.slope_per_day))}/${unit}`;
}

function formatPercent(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(value >= 1 ? 0 : 1)}%`;
}
