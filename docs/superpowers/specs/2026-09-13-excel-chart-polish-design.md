# Excel 图表精修设计（Phase 14 后续增强）

更新时间：2026-09-13
状态：设计完成，待实施
关联：task_plan.md Phase 14 后续增强；docs/pending-tasks.md P3 #16

## 1. 背景

Excel 客户版报表当前「容量趋势」Sheet 是纯表格（Tower/集群/当前已用容量/增长/90天预测/总容量/使用率/预计耗尽天数/风险状态），无任何图表；无打印版式设置。Word 客户版已有图表（每集群容量使用趋势折线图 + Top 10 VM 增长量条形图）。findings.md 记录"图表横坐标需要根据窗口大小调整显示间隔"。

## 2. 目标

1. 给 Excel「容量趋势」Sheet 增加**集群容量使用趋势折线图**（合并所有集群，复用 common.py 的 `_line_chart_image`，与 Word 风格统一）。
2. 补打印版式（打印区域、页面方向横向、fit-to-page）。
3. 优化 `_line_chart_image` 横坐标显示间隔（按时间跨度调整 AutoDateLocator 刻度数）。
4. 补 Excel 图表回归测试。

## 3. 方案

### 3.1 重新加回 `_merged_cluster_points`

任务 2 删除了 `_merged_cluster_points`（当时不可达）。Excel 容量趋势图需要它合并所有集群的趋势点。从 export 拆分提交恢复实现：

```python
def _merged_cluster_points(clusters: list[dict[str, Any]]) -> list[tuple[int, float]]:
    by_ts: dict[int, float] = defaultdict(float)
    for cluster in clusters:
        for ts, value in _cluster_points(cluster):
            by_ts[ts] += value
    return sorted(by_ts.items())
```

### 3.2 容量趋势 Sheet 插入图表

在 `_write_xlsx_template_capacity_trend` 表格下方插入合并趋势折线图：

- 用 `_merged_cluster_points(clusters)` 生成数据点，`_line_chart_image(points, "集群容量使用趋势", "容量 (TiB)")` 生成 PNG。
- 用 `openpyxl.drawing.image.Image` 插入到表格下方（如 A 列，表格 max_row + 2 行）。
- 图片宽度与表格匹配（约 6.6 英寸）。

### 3.3 打印版式

对容量趋势 Sheet（及主要 Sheet）设置：

- `sheet.print_area`：表格 + 图表区域。
- `sheet.page_setup.orientation = "landscape"`。
- `sheet.page_setup.fitToPage = True`、`fitToWidth = 1`、`fitToHeight = 0`。
- `sheet.sheet_properties.pageSetUpPr.fitToPage = True`。

### 3.4 横坐标间隔优化

`_line_chart_image` 当前用 `mdates.AutoDateLocator(minticks=4, maxticks=6)`。按时间跨度调整刻度数：

- 跨度 < 30 天：`minticks=4, maxticks=6`（日间隔）。
- 跨度 < 180 天：`minticks=4, maxticks=6`（周/月间隔）。
- 跨度 >= 180 天：`minticks=3, maxticks=5`（月/季度间隔，避免过密）。

### 3.5 测试

补 Excel 图表回归测试：断言容量趋势 Sheet 含图片（`sheet._images` 非空），且打印版式已设置。

## 4. 验收

- Excel 导出真实验证（.3 产物抽查：容量趋势 Sheet 有图表、打印版式生效）。
- 全量 308 测试回基线。
- 新增 Excel 图表测试通过。

## 5. 不做范围

- 不改 Word 图表逻辑（仅优化 `_line_chart_image` 横坐标，Word 共用）。
- 不新增 Excel 其他 Sheet 的图表（仅容量趋势）。
