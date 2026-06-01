import ReactECharts from "echarts-for-react";
import { useMemo } from "react";
import { formatBytes } from "../services/api";
import type { ForecastPayload } from "../types";

type ClusterReport = ForecastPayload["clusters"][number];
type RangeDays = 7 | 30 | 90 | 365 | 720;

interface ClusterCapacityChartProps {
  clusters: ClusterReport[];
  title: string;
  height?: number;
  rangeDays: RangeDays;
  onRangeDaysChange: (days: RangeDays) => void;
}

interface ChartModel {
  title: string;
  points: Array<[string, number]>;
  total: number | null;
  warning: number | null;
  slopePerDay: number;
  status: "healthy" | "warning" | "risk" | "unknown";
}

const dayMs = 86_400_000;

const CHART_RANGE_OPTIONS: Array<{ value: RangeDays; label: string }> = [
  { value: 7, label: "7天" },
  { value: 30, label: "30天" },
  { value: 90, label: "90天" },
  { value: 365, label: "365天" },
  { value: 720, label: "720天" }
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
      slopePerDay: cluster.forecast.slope_per_day || 0,
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
    slopePerDay: clusters.reduce((sum, cluster) => sum + Math.max(0, cluster.forecast.slope_per_day || 0), 0),
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

function axisInterval(rangeDays: RangeDays): number {
  if (rangeDays <= 7) return 0;
  if (rangeDays <= 30) return 4;
  if (rangeDays <= 90) return 14;
  if (rangeDays <= 365) return 29;
  return 59;
}

function formatAxisLabel(value: string, rangeDays: RangeDays): string {
  if (rangeDays <= 90) return value.slice(5);
  const date = new Date(`${value}T00:00:00Z`);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function predictedHistory(points: Array<[string, number]>, slopePerDay: number): Array<[string, number | null]> {
  if (points.length < 2 || !Number.isFinite(slopePerDay)) return points.map(([label]) => [label, null]);
  const [latestLabel, latestValue] = points[points.length - 1];
  const latestTime = dateValue(latestLabel);
  return points.map(([label]) => {
    const daysBefore = Math.max(0, (latestTime - dateValue(label)) / dayMs);
    return [label, Math.max(0, latestValue - slopePerDay * daysBefore)];
  });
}

function futurePoints(points: Array<[string, number]>, slopePerDay: number): Array<[string, number]> {
  if (!points.length || !Number.isFinite(slopePerDay)) return [];
  const [latestLabel, latestValue] = points[points.length - 1];
  const latestTime = dateValue(latestLabel);
  return [0, 15, 30, 45, 60].map((days) => {
    return [dateLabel(latestTime + days * dayMs), Math.max(0, latestValue + slopePerDay * days)];
  });
}

function dateValue(label: string): number {
  return Date.parse(`${label}T00:00:00Z`);
}

function dateLabel(value: number): string {
  return new Date(value).toISOString().slice(0, 10);
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

export function ClusterCapacityChart({ clusters, title, height = 360, rangeDays, onRangeDaysChange }: ClusterCapacityChartProps) {
  const model = useMemo(() => aggregateClusters(clusters, title), [clusters, title]);
  const actualPoints = model.points;
  const historyPoints = predictedHistory(actualPoints, model.slopePerDay);
  const projectedPoints = futurePoints(actualPoints, model.slopePerDay);
  const labels = [...actualPoints.map(([label]) => label), ...projectedPoints.slice(1).map(([label]) => label)];
  const actualByLabel = new Map(actualPoints);
  const historyByLabel = new Map(historyPoints);
  const futureByLabel = new Map(projectedPoints);
  const max = yAxisMax([
    ...actualPoints.map(([, value]) => value),
    ...historyPoints.map(([, value]) => value),
    ...projectedPoints.map(([, value]) => value),
    model.total,
    model.warning
  ]);

  const option = {
    color: ["#0f9fbf", "#8792a2", "#29354d", "#f59e0b", "#ef4444"],
    grid: { left: 76, right: 30, top: 52, bottom: 46 },
    legend: {
      top: 4,
      right: 0,
      itemWidth: 18,
      itemHeight: 8,
      textStyle: { color: "#5b6472", fontSize: 12 }
    },
    tooltip: {
      trigger: "axis",
      formatter(params: Array<{ axisValue: string; seriesName: string; value: number | null }>) {
        const rows = params
          .filter((item) => typeof item.value === "number")
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
      axisLabel: { color: "#718096", hideOverlap: true, interval: axisInterval(rangeDays), formatter: (value: string) => formatAxisLabel(value, rangeDays) }
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
      }
    ]
  };

  if (!actualPoints.length) {
    return (
      <div className="cluster-chart-shell">
        <ClusterChartToolbar title={model.title} status={model.status} rangeDays={rangeDays} onRangeDaysChange={onRangeDaysChange} />
        <div className="empty-chart">暂无集群趋势数据</div>
      </div>
    );
  }

  return (
    <div className="cluster-chart-shell">
      <ClusterChartToolbar title={model.title} status={model.status} rangeDays={rangeDays} onRangeDaysChange={onRangeDaysChange} />
      <ReactECharts option={option} style={{ height }} notMerge />
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
