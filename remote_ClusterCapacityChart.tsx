import ReactECharts from "echarts-for-react";
import { useMemo, useState } from "react";
import { formatBytes } from "../services/api";
import type { ForecastPayload } from "../types";

type ClusterReport = ForecastPayload["clusters"][number];
type RangeMode = "year" | "all";

interface ClusterCapacityChartProps {
  clusters: ClusterReport[];
  title: string;
  height?: number;
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

function filterRange(points: Array<[string, number]>, range: RangeMode): Array<[string, number]> {
  if (range === "all" || points.length <= 1) return points;
  const latest = dateValue(points[points.length - 1][0]);
  const start = latest - 365 * dayMs;
  return points.filter(([label]) => dateValue(label) >= start);
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

export function ClusterCapacityChart({ clusters, title, height = 360, actualTheme = "light" }: ClusterCapacityChartProps & { actualTheme?: "light" | "dark" }) {
  const [range, setRange] = useState<RangeMode>("year");
  const model = useMemo(() => aggregateClusters(clusters, title), [clusters, title]);
  const actualPoints = filterRange(model.points, range);
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
    color: actualTheme === "dark" ? ["#00e5ff", "#a0aec0", "#e2e8f0", "#ff9100", "#ff1744"] : ["#1677ff", "#7a8aa0", "#26364f", "#ff9f1c", "#ff5a5f"],
    grid: { left: 76, right: 30, top: 52, bottom: 46 },
    legend: {
      top: 4,
      right: 0,
      itemWidth: 18,
      itemHeight: 8,
      textStyle: { color: actualTheme === "dark" ? "#a0aec0" : "#7a8aa0", fontSize: 12 }
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: actualTheme === "dark" ? "rgba(15, 23, 42, 0.8)" : "rgba(255, 255, 255, 0.9)",
      borderColor: actualTheme === "dark" ? "rgba(0, 229, 255, 0.3)" : "rgba(22, 119, 255, 0.2)",
      textStyle: { color: actualTheme === "dark" ? "#e2e8f0" : "#26364f" },
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
      axisLine: { lineStyle: { color: actualTheme === "dark" ? "rgba(255, 255, 255, 0.1)" : "rgba(22, 119, 255, 0.1)" } },
      axisLabel: { color: "#a0aec0", hideOverlap: true, formatter: (value: string) => value.slice(5) }
    },
    yAxis: {
      type: "value",
      min: 0,
      max,
      axisLabel: { color: "#a0aec0", formatter: (value: number) => formatBytes(value) },
      splitLine: { lineStyle: { color: actualTheme === "dark" ? "rgba(255, 255, 255, 0.05)" : "rgba(22, 119, 255, 0.05)" } }
    },
    series: [
      {
        name: "实际容量使用",
        type: "line",
        smooth: true,
        showSymbol: actualPoints.length <= 14,
        data: labels.map((label) => actualByLabel.get(label) ?? null),
        lineStyle: { width: 3, shadowColor: actualTheme === "dark" ? "rgba(0, 229, 255, 0.5)" : "rgba(22, 119, 255, 0.3)", shadowBlur: actualTheme === "dark" ? 10 : 6 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: actualTheme === "dark" ? "rgba(0, 229, 255, 0.4)" : "rgba(22, 119, 255, 0.2)" },
              { offset: 1, color: actualTheme === "dark" ? "rgba(0, 229, 255, 0.01)" : "rgba(22, 119, 255, 0.02)" }
            ]
          }
        }
      },
      {
        name: "历史预测",
        type: "line",
        smooth: true,
        showSymbol: false,
        data: labels.map((label) => historyByLabel.get(label) ?? null),
        lineStyle: { width: 2, type: "dashed", opacity: 0.7 }
      },
      {
        name: "未来预测",
        type: "line",
        smooth: true,
        showSymbol: false,
        data: labels.map((label) => futureByLabel.get(label) ?? null),
        lineStyle: { width: 2, type: "dashed", shadowColor: "rgba(226, 232, 240, 0.5)", shadowBlur: 5 }
      },
      {
        name: "告警阈值",
        type: "line",
        showSymbol: false,
        data: horizontalLine(labels, model.warning),
        lineStyle: { width: 1.8, type: "dashed", shadowColor: "rgba(255, 145, 0, 0.5)", shadowBlur: 5 }
      },
      {
        name: "存储卷有效容量",
        type: "line",
        showSymbol: false,
        data: horizontalLine(labels, model.total),
        lineStyle: { width: 1.8, type: "dashed", shadowColor: "rgba(255, 23, 68, 0.5)", shadowBlur: 5 }
      }
    ]
  };

  if (!actualPoints.length) {
    return (
      <div className="cluster-chart-shell">
        <ClusterChartToolbar title={model.title} status={model.status} range={range} onRangeChange={setRange} />
        <div className="empty-chart">暂无集群趋势数据</div>
      </div>
    );
  }

  return (
    <div className="cluster-chart-shell">
      <ClusterChartToolbar title={model.title} status={model.status} range={range} onRangeChange={setRange} />
      <ReactECharts option={option} style={{ height }} notMerge />
    </div>
  );
}

function ClusterChartToolbar({
  title,
  status,
  range,
  onRangeChange
}: {
  title: string;
  status: ChartModel["status"];
  range: RangeMode;
  onRangeChange: (range: RangeMode) => void;
}) {
  return (
    <div className="cluster-chart-toolbar">
      <div className="cluster-chart-title">
        <strong>{title}</strong>
        <span className={`cluster-chart-status ${status}`}>{statusLabel(status)}</span>
      </div>
      <div className="sort-tabs compact-tabs chart-range-tabs" aria-label="集群趋势范围">
        <button type="button" className={range === "year" ? "active" : ""} onClick={() => onRangeChange("year")}>
          最近1年
        </button>
        <button type="button" className={range === "all" ? "active" : ""} onClick={() => onRangeChange("all")}>
          全部
        </button>
      </div>
    </div>
  );
}
