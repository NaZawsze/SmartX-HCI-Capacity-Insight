export type DailyGridPoint = [string, number | null];

/**
 * 把稀疏的日粒度实际数据补齐为"连续日序列"，缺失日填 null。
 *
 * 图表横轴是类目轴，只有数据日期时相邻类目会被直接连线，导致采集断档期
 * （如连续两周没采到数据）画出一条假的平滑斜线。补成连续日 + null 后，
 * ECharts（connectNulls 默认 false）会在断档处断开实际容量曲线（49-41）。
 */
export function buildDailyGrid(points: Array<[string, number]>): DailyGridPoint[] {
  if (!points.length) return [];
  const sorted = [...points].sort(([left], [right]) => left.localeCompare(right));
  const byLabel = new Map<string, number>(sorted);
  const start = dateValue(sorted[0][0]);
  const end = dateValue(sorted[sorted.length - 1][0]);
  const grid: DailyGridPoint[] = [];
  for (let time = start; time <= end; time += dayMs) {
    const label = dateLabel(time);
    grid.push([label, byLabel.has(label) ? (byLabel.get(label) as number) : null]);
  }
  return grid;
}

const dayMs = 86_400_000;

function dateValue(label: string): number {
  return Date.parse(`${label}T00:00:00Z`);
}

function dateLabel(value: number): string {
  return new Date(value).toISOString().slice(0, 10);
}
