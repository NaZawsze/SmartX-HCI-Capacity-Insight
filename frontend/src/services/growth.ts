/** 增长最快 VM 列表的展示规则：两页（概览/报表）必须共用（49-45）。 */

/** 两页最多展示的条数（报表页原为 slice(0, 50)）。 */
export const TOP_GROWTH_VM_LIMIT = 50;

/**
 * 样本跨度过滤：样本跨度过短的增长不可信。
 * 日列表要求 >= 1 天，月列表要求 >= 30 天；`sample_span_days` 缺失时放行（兼容旧数据）。
 */
export function hasSampleSpan(item: { sample_span_days?: number | null }, minDays: number): boolean {
  return item.sample_span_days == null || item.sample_span_days >= minDays;
}
