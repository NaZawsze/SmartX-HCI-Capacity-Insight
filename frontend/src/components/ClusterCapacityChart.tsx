import ReactECharts from "echarts-for-react";
import { useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { formatBytes } from "../services/api";
import { buildDailyGrid } from "../services/chartGrid";
import { forecastBandSeries } from "../services/forecastBand";
import type { ForecastPayload } from "../types";

type ClusterReport = ForecastPayload["clusters"][number];
type RangeDays = 7 | 30 | 90 | 365;

interface ClusterCapacityChartProps {
  clusters: ClusterReport[];
  title: string;
  height?: number;
  rangeDays: RangeDays;
  loading?: boolean;
  onRangeDaysChange: (days: RangeDays) => void;
}

interface ChartModel {
  title: string;
  points: Array<[string, number]>;
  total: number | null;
  warning: number | null;
  allocated: number | null;
  slopePerDay: number;
  bandNow: number;
  bandPerDay: number;
  status: "healthy" | "warning" | "risk" | "unknown";
}

const dayMs = 86_400_000;

const CHART_RANGE_OPTIONS: Array<{ value: RangeDays; label: string }> = [
  { value: 7, label: "7天" },
  { value: 30, label: "30天" },
  { value: 90, label: "90天" },
  { value: 365, label: "365天" }
];

function dayLabel(timestampSeconds: number): string {
  return dateLabel(timestampSeconds * 1000);
}

function dailyLatestPoints(points: [number, number][]): Array<[string, number]> {
  const byDay = new Map<string, [number, number]>();
  for (const [timestamp, value] of points) {
    const label = dayLabel(timestamp);
    const previous = byDay.get(label);
    if (!previous || timestamp >= previous[0]) {
      byDay.set(label, [timestamp, value]);
    }
  }
  return [...byDay.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([label, [, value]]) => [label, value]);
}

function aggregateClusters(clusters: ClusterReport[], title: string): ChartModel {
  if (clusters.length === 1) {
    const cluster = clusters[0];
    const total = finiteOrNull(cluster.total);
    const current = cluster.forecast.current || 0;
    return {
      title,
      points: dailyLatestPoints(cluster.points || []),
      total,
      warning: finiteOrNull(cluster.warning) ?? (total ? total * 0.9 : null),
      allocated: finiteOrNull(cluster.allocated),
      slopePerDay: cluster.forecast.slope_per_day || 0,
      bandNow: finiteOrZero(cluster.forecast.band_half_width_now),
      bandPerDay: finiteOrZero(cluster.forecast.band_half_width_per_day),
      status: capacityStatus(current, total)
    };
  }

  const pointsByCluster = clusters.map((cluster) => dailyLatestPoints(cluster.points || []));
  const total = sumFinite(clusters.map((cluster) => cluster.total));
  const current = sumFinite(clusters.map((cluster) => cluster.forecast.current));
  return {
    title,
    points: aggregateDailyPoints(pointsByCluster),
    total,
    warning: total ? total * 0.9 : null,
    allocated: sumFinite(clusters.map((cluster) => finiteOrNull(cluster.allocated))),
    slopePerDay: clusters.reduce((sum, cluster) => sum + Math.max(0, cluster.forecast.slope_per_day || 0), 0),
    // 多集群带宽求和（保守口径：偏宽优于偏窄）
    bandNow: sumFinite(clusters.map((cluster) => cluster.forecast.band_half_width_now)) ?? 0,
    bandPerDay: sumFinite(clusters.map((cluster) => cluster.forecast.band_half_width_per_day)) ?? 0,
    status: capacityStatus(current || 0, total)
  };
}

function aggregateDailyPoints(seriesList: Array<Array<[string, number]>>): Array<[string, number]> {
  const labels = [...new Set(seriesList.flatMap((points) => points.map(([label]) => label)))].sort();
  const latestValues = new Map<number, number>();
  const indexes = seriesList.map(() => 0);
  return labels.map((label) => {
    seriesList.forEach((points, seriesIndex) => {
      while (indexes[seriesIndex] < points.length && points[indexes[seriesIndex]][0] <= label) {
        latestValues.set(seriesIndex, points[indexes[seriesIndex]][1]);
        indexes[seriesIndex] += 1;
      }
    });
    const total = [...latestValues.values()].reduce((sum, value) => sum + value, 0);
    return [label, total];
  });
}

function finiteOrNull(value?: number | null): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function finiteOrZero(value?: number | null): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function sumFinite(values: Array<number | null | undefined>): number | null {
  const total = values.reduce<number>((sum, value) => sum + (finiteOrNull(value) || 0), 0);
  return total > 0 ? total : null;
}

function capacityStatus(current: number, total: number | null): ChartModel["status"] {
  if (!total) return "unknown";
  const ratio = current / total;
  if (ratio >= 1) return "risk";
  if (ratio >= 0.9) return "warning";
  return "healthy";
}

// 横轴标签按实际类目数自适应：数据历史短于窗口时（新部署环境常态）类目少，
// 固定按名义窗口天数给间隔会导致 hideOverlap 藏掉几乎所有日期标签。
function axisInterval(labelCount: number): number {
  if (labelCount <= 12) return 0;
  return Math.ceil(labelCount / 10) - 1;
}

function formatAxisLabel(value: string, rangeDays: RangeDays, spanDays: number): string {
  if (rangeDays <= 90 || spanDays < 180) return value.slice(5);
  const date = new Date(`${value}T00:00:00Z`);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function predictedHistory(labels: string[], points: Array<[string, number]>, slopePerDay: number): Array<[string, number | null]> {
  if (points.length < 2 || !Number.isFinite(slopePerDay)) return labels.map((label) => [label, null]);
  const [latestLabel, latestValue] = points[points.length - 1];
  const latestTime = dateValue(latestLabel);
  return labels.map((label) => {
    const daysBefore = Math.max(0, (latestTime - dateValue(label)) / dayMs);
    return [label, Math.max(0, latestValue - slopePerDay * daysBefore)];
  });
}

interface FuturePoint {
  label: string;
  value: number;
  days: number;
}

function futurePoints(points: Array<[string, number]>, slopePerDay: number): FuturePoint[] {
  if (!points.length || !Number.isFinite(slopePerDay)) return [];
  const [latestLabel, latestValue] = points[points.length - 1];
  const latestTime = dateValue(latestLabel);
  return [0, 15, 30, 45, 60].map((days) => ({
    label: dateLabel(latestTime + days * dayMs),
    value: Math.max(0, latestValue + slopePerDay * days),
    days
  }));
}

function dateValue(label: string): number {
  return Date.parse(`${label}T00:00:00Z`);
}

function dateLabel(value: number): string {
  return new Date(value).toISOString().slice(0, 10);
}

// 颜色从 :root 设计变量取值（frontend-style-guide：不引入新硬编码色值）
function cssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function horizontalLine(labels: string[], value: number | null): Array<number | null> {
  return labels.map(() => value);
}

function yAxisMax(values: Array<number | null>): number | undefined {
  const highest = Math.max(...values.filter((value): value is number => typeof value === "number" && Number.isFinite(value)), 0);
  if (!highest) return undefined;
  const tib = 1024 ** 4;
  const gib = 1024 ** 3;
  if (highest <= tib) return tib;
  const highestGib = highest / gib;
  return Math.ceil(highestGib / 500) * 500 * gib;
}

function statusLabel(status: ChartModel["status"]): string {
  if (status === "risk") return "风险";
  if (status === "warning") return "预警";
  if (status === "healthy") return "健康";
  return "未知";
}

export function ClusterCapacityChart({ clusters, title, height = 360, rangeDays, loading = false, onRangeDaysChange }: ClusterCapacityChartProps) {
  const model = useMemo(() => aggregateClusters(clusters, title), [clusters, title]);
  // 分配容量图例默认关闭（2026-09-26 用户要求），点图例打开；打开时才把 y 轴上限算进去，
  // 否则「已分配 > 总容量」会把实际容量曲线压扁。
  const [showAllocated, setShowAllocated] = useState(false);
  const hasAllocated = model.allocated != null;
  const actualPoints = model.points;
  // 实际数据补成连续日序列：断档日填 null，实际容量曲线在这些位置断开（49-41）。
  const actualGrid = useMemo(() => buildDailyGrid(actualPoints), [actualPoints]);
  const actualLabels = actualGrid.map(([label]) => label);
  const historyPoints = predictedHistory(actualLabels, actualPoints, model.slopePerDay);
  const projected = futurePoints(actualPoints, model.slopePerDay);
  const labels = [...actualLabels, ...projected.slice(1).map((point) => point.label)];
  const actualByLabel = new Map<string, number | null>(actualGrid);
  const historyByLabel = new Map(historyPoints);
  const futureByLabel = new Map(projected.map((point) => [point.label, point.value] as [string, number]));
  const hasBand = model.bandNow > 0 || model.bandPerDay > 0;
  const axisSpanDays = actualPoints.length > 1
    ? (dateValue(actualPoints[actualPoints.length - 1][0]) - dateValue(actualPoints[0][0])) / dayMs
    : 0;
  const bandUpper = new Map<string, number>();
  const bandLower = new Map<string, number>();
  if (hasBand) {
    const series = forecastBandSeries(projected, model.bandNow, model.bandPerDay);
    for (const [label, value] of series.upper) bandUpper.set(label, value);
    for (const [label, value] of series.lower) bandLower.set(label, value);
  }
  const max = yAxisMax([
    ...actualPoints.map(([, value]) => value),
    ...historyPoints.map(([, value]) => value),
    ...projected.map((point) => point.value),
    ...(hasBand ? [...bandUpper.values()] : []),
    model.total,
    model.warning,
    ...(showAllocated && model.allocated != null ? [model.allocated] : [])
  ]);

  const option = {
    color: ["#0f9fbf", "#8792a2", "#29354d", "#f59e0b", "#ef4444"],
    animation: true,
    animationDuration: 700,
    animationEasing: "cubicOut",
    animationDurationUpdate: 550,
    animationEasingUpdate: "cubicOut",
    grid: { left: 76, right: 30, top: 52, bottom: 46 },
    legend: {
      top: 4,
      right: 0,
      itemWidth: 18,
      itemHeight: 8,
      data: ["实际容量使用", "历史预测", "未来预测", "告警阈值", "存储卷有效容量", "已分配容量"],
      selected: { 已分配容量: false },
      textStyle: { color: "#5b6472", fontSize: 12 }
    },
    tooltip: {
      trigger: "axis",
      formatter(params: Array<{ axisValue: string; seriesName: string; value: number | null }>) {
        const rows = params
          .filter((item) => typeof item.value === "number" && item.seriesName !== "当日容量")
          .map((item) => `${item.seriesName}: ${formatBytes(item.value as number)}`)
          .join("<br/>");
        return `${params[0]?.axisValue || ""}<br/>${rows}`;
      }
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: labels,
      axisLine: { lineStyle: { color: "#d6dee9" } },
      axisLabel: { color: "#718096", hideOverlap: true, interval: axisInterval(labels.length), formatter: (value: string) => formatAxisLabel(value, rangeDays, axisSpanDays) }
    },
    yAxis: {
      type: "value",
      min: 0,
      max,
      axisLabel: { color: "#718096", formatter: (value: number) => formatBytes(value) },
      splitLine: { lineStyle: { color: "#edf2f7" } }
    },
    series: [
      {
        name: "实际容量使用",
        type: "line",
        smooth: true,
        showSymbol: actualPoints.length <= 14,
        data: labels.map((label) => actualByLabel.get(label) ?? null),
        lineStyle: { width: 2.6 },
        areaStyle: { color: "rgba(15, 159, 191, 0.12)" }
      },
      {
        name: "历史预测",
        type: "line",
        smooth: true,
        showSymbol: false,
        data: labels.map((label) => historyByLabel.get(label) ?? null),
        lineStyle: { width: 2, type: "dashed" }
      },
      {
        name: "未来预测",
        type: "line",
        smooth: true,
        showSymbol: false,
        data: labels.map((label) => futureByLabel.get(label) ?? null),
        lineStyle: { width: 2, type: "dashed" }
      },
      ...(hasBand
        ? [
            {
              name: "预测上限",
              type: "line",
              showSymbol: false,
              data: labels.map((label) => bandUpper.get(label) ?? null),
              lineStyle: { width: 1.4, type: "dashed", color: "#9aa7b8" },
              itemStyle: { color: "#9aa7b8" }
            },
            {
              name: "预测下限",
              type: "line",
              showSymbol: false,
              data: labels.map((label) => bandLower.get(label) ?? null),
              lineStyle: { width: 1.4, type: "dashed", color: "#9aa7b8" },
              itemStyle: { color: "#9aa7b8" }
            }
          ]
        : []),
      {
        name: "告警阈值",
        type: "line",
        showSymbol: false,
        data: horizontalLine(labels, model.warning),
        lineStyle: { width: 1.8, type: "dashed" }
      },
      {
        name: "存储卷有效容量",
        type: "line",
        showSymbol: false,
        data: horizontalLine(labels, model.total),
        lineStyle: { width: 1.8, type: "dashed" }
      },
      ...(hasAllocated
        ? [
            {
              name: "已分配容量",
              type: "line",
              showSymbol: false,
              data: horizontalLine(labels, model.allocated),
              lineStyle: { width: 2, type: "dashed", color: cssVar("--blue", "#1677ff") },
              itemStyle: { color: cssVar("--blue", "#1677ff") }
            }
          ]
        : []),
      {
        name: "当日容量",
        type: "scatter",
        symbol: "circle",
        symbolSize: 9,
        data: actualPoints.length ? [[actualPoints[actualPoints.length - 1][0], actualPoints[actualPoints.length - 1][1]]] : [],
        itemStyle: { color: "#eab308" },
        label: {
          show: true,
          position: "top",
          distance: 8,
          color: "#eab308",
          fontWeight: 700,
          formatter: () => formatBytes(actualPoints.length ? actualPoints[actualPoints.length - 1][1] : 0)
        },
        z: 6
      }
    ]
  };

  if (!actualPoints.length) {
    return (
      <div className="cluster-chart-shell">
        <ClusterChartToolbar title={model.title} status={model.status} rangeDays={rangeDays} onRangeDaysChange={onRangeDaysChange} />
        <div className="cluster-chart-body">
          <div className="empty-chart">暂无集群趋势数据</div>
          {loading && <ChartLoadingOverlay />}
        </div>
      </div>
    );
  }

  return (
    <div className="cluster-chart-shell">
      <ClusterChartToolbar title={model.title} status={model.status} rangeDays={rangeDays} onRangeDaysChange={onRangeDaysChange} />
      <div className="cluster-chart-body">
        <ReactECharts
          option={option}
          style={{ height }}
          notMerge
          onEvents={{
            legendselectchanged: (event: { selected?: Record<string, boolean> }) => {
              const next = event.selected?.["已分配容量"];
              if (typeof next === "boolean") {
                setShowAllocated(next);
              }
            }
          }}
        />
        {loading && <ChartLoadingOverlay />}
      </div>
      <div className="forecast-disclaimer">预测值可能会有偏差，以实际为准</div>
    </div>
  );
}

function ChartLoadingOverlay() {
  return (
    <div className="chart-loading-overlay" role="status" aria-live="polite">
      <LoaderCircle size={16} className="chart-loading-icon" />
      正在加载趋势数据…
    </div>
  );
}

function ClusterChartToolbar({
  title,
  status,
  rangeDays,
  onRangeDaysChange
}: {
  title: string;
  status: ChartModel["status"];
  rangeDays: RangeDays;
  onRangeDaysChange: (days: RangeDays) => void;
}) {
  return (
    <div className="cluster-chart-toolbar">
      <div className="cluster-chart-title">
        <strong>{title}</strong>
        <span className={`cluster-chart-status ${status}`}>{statusLabel(status)}</span>
      </div>
      <div className="sort-tabs compact-tabs chart-range-tabs" aria-label="集群趋势范围">
        {CHART_RANGE_OPTIONS.map((option) => (
          <button key={option.value} type="button" className={rangeDays === option.value ? "active" : ""} onClick={() => onRangeDaysChange(option.value)}>
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
