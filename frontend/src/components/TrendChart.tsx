import ReactECharts from "echarts-for-react";
import { formatBytes } from "../services/api";

interface TrendChartProps {
  points: [number, number][];
  referenceValue?: number;
  height?: number;
}

const gib = 1024 ** 3;
const tib = 1024 ** 4;

function dayLabel(timestampSeconds: number): string {
  const date = new Date(timestampSeconds * 1000);
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dailyPoints(points: [number, number][]): Array<[string, number]> {
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

function yAxisScale(values: number[], referenceValue = 0): { max: number; interval: number } {
  const highest = Math.max(referenceValue, ...values, 0);
  if (highest <= tib) {
    return { max: tib, interval: 200 * gib };
  }

  const highestGib = highest / gib;
  const intervalGib = Math.max(100, Math.ceil(highestGib / 5 / 100) * 100);
  return {
    max: intervalGib * 5 * gib,
    interval: intervalGib * gib
  };
}

function formatYAxisBytes(value: number): string {
  if (value <= 0) return "0 B";
  if (value >= 1000 * gib && value < tib) {
    return "1 TiB";
  }
  if (value >= 1000 * gib) {
    const tibValue = value / tib;
    const precision = Number.isInteger(tibValue) ? 0 : 2;
    return `${tibValue.toFixed(precision)} TiB`;
  }
  return `${Math.round(value / gib)} GiB`;
}

export function TrendChart({ points, referenceValue, height = 280 }: TrendChartProps) {
  const data = dailyPoints(points);
  const scale = yAxisScale(data.map(([, value]) => value), referenceValue);
  const option = {
    grid: { left: 78, right: 24, top: 36, bottom: 42, containLabel: false },
    tooltip: {
      trigger: "axis",
      formatter(params: Array<{ axisValue: string; value: number }>) {
        const item = params[0];
        return `${item.axisValue}<br/>${formatBytes(item.value)}`;
      }
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: data.map(([label]) => label.slice(5)),
      axisLine: { lineStyle: { color: "#d6dee9" } },
      axisLabel: { color: "#718096", hideOverlap: true }
    },
    yAxis: {
      type: "value",
      min: 0,
      max: scale.max,
      interval: scale.interval,
      axisLabel: {
        color: "#718096",
        width: 64,
        align: "right",
        margin: 10,
        overflow: "truncate",
        formatter: (value: number) => formatYAxisBytes(value)
      },
      splitLine: { lineStyle: { color: "#edf2f7" } }
    },
    series: [
      {
        type: "line",
        smooth: true,
        showSymbol: data.length <= 14,
        data: data.map(([, value]) => value),
        areaStyle: { color: "rgba(22, 119, 255, 0.12)" },
        lineStyle: { color: "#1677ff", width: 2.5 }
      }
    ]
  };

  if (!data.length) {
    return <div className="empty-chart">暂无趋势数据</div>;
  }

  return <ReactECharts option={option} style={{ height }} notMerge />;
}
