// 预测带上下界计算：hw(t) = bandNow + bandPerDay × t，与后端
// ForecastResult.band_half_width_now / band_half_width_per_day 的线性近似口径一致。
// 下限截 0（容量不为负）。独立成模块以便在不引入 echarts 的情况下单测。

export interface ForecastBandPoint {
  label: string;
  value: number;
  days: number;
}

export function forecastBandSeries(
  projected: ForecastBandPoint[],
  bandNow: number,
  bandPerDay: number
): { upper: Map<string, number>; lower: Map<string, number> } {
  const upper = new Map<string, number>();
  const lower = new Map<string, number>();
  for (const point of projected) {
    const halfWidth = bandNow + bandPerDay * point.days;
    upper.set(point.label, point.value + halfWidth);
    lower.set(point.label, Math.max(0, point.value - halfWidth));
  }
  return { upper, lower };
}
