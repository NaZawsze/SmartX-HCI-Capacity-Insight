# VM 页千台规模加固 与 报表图表窗口去 720 天档 设计

- 日期：2026-09-19
- 分支：dev2
- 关联任务：task_plan.md Phase 49 第 18、19 项（两项独立小任务合并设计：同批实施，各自单独成文粒度过细；影响面、测试计划、回滚按 A/B 节分开写清）
- 关联发现：findings.md「Prometheus 400d retention 与报表 720 天图表窗口口径冲突」、pending-tasks #19

---

## A 节：报表图表窗口移除 720 天档

### A.1 背景与口径

Prometheus retention 为 400d（`docker-compose*.yml` `--storage.tsdb.retention.time=400d`），报表图表数据全部来自 Prometheus range 查询（`reports/service.py` `_cluster_series`）。`_normalize_chart_days` 目前允许 `{7, 30, 90, 365, 720}`，部署超 400 天后 720 天窗口前段必为空，属于会随运行时长必然显现的口径缺陷。

用户决策（2026-09-19）：**去掉 720 档，图表窗口封顶 365**；同时要求仔细核实导出相关程序是否受影响。

### A.2 影响面核查结论（已逐文件读码核实）

| 位置 | "720" 语义 | 是否受影响 |
| --- | --- | --- |
| `backend/app/v2/reports/service.py:532` `_normalize_chart_days` 集合 | 图表窗口档位 | **受影响，本次移除** |
| `backend/tests/test_v2_reports_api.py:48,53` | 测试传 `chart_days=720` 并断言 720 | **受影响，改为断言回退 365** |
| `frontend/src/components/ClusterCapacityChart.tsx:7,33` | `RangeDays` 类型 + 窗口选项「720天」 | **受影响，本次移除** |
| `frontend/src/pages/ReportsPage.tsx:344` | `ChartRangeDays` 类型 | **受影响，本次移除** |
| `frontend/src/pages/ReportsPage.test.tsx:25,30,31` | 测试 mock 的选项数组/类型 | **受影响，同步移除** |
| `docs/v2-api-contracts.md:233`、`docs/functional-modules.md:189` | 文档口径 | **受影响，同步更新** |
| 导出链路（`api/reports.py` word/excel/bundle、`reports/export/*`） | 三个导出端点只收 `period_days`（7/14/30/90/180/365），调 `latest_report` 不传 `chart_days`，内部默认 365；export 代码与 `test_v2_report_exports.py` 中的"720"均为 unix 时间戳（1764547200 等） | **不受影响** |
| `backend/app/{core,v2}/config.py` token_ttl 720 | Token 有效期分钟数 | 无关 |
| `frontend/src/styles/global.css` 720 | px 断言/宽度 | 无关 |

### A.3 变更内容

1. `backend/app/v2/reports/service.py`：`_normalize_chart_days` 集合删 720 → `{7, 30, 90, 365}`，其余值回退 365（行为不变）。
2. `backend/tests/test_v2_reports_api.py`：原 `chart_days=720` 用例改为「传 720 断言响应 `chart_days == 365`」，固化向后兼容回退行为（旧链接/脚本传 720 不报错）。
3. `frontend/src/components/ClusterCapacityChart.tsx`：`RangeDays` 类型删 720；`CHART_RANGE_OPTIONS` 删「720天」项；`axisInterval` 末尾 `return 59` 分支在 365 封顶后不可达，一并删除。
4. `frontend/src/pages/ReportsPage.tsx`：`ChartRangeDays` 类型删 720（本页无独立选项数组，选项在 ClusterCapacityChart）。
5. `frontend/src/pages/ReportsPage.test.tsx`：mock 选项数组与类型同步删 720。
6. 文档：`docs/v2-api-contracts.md` `chart_days=7|30|90|365`；`docs/functional-modules.md` 「7/30/90/365 天统计窗口」；api.md 如有 chart_days 档位描述同步。

### A.4 测试计划

- 本地：后端 reports 相关 pytest（`test_v2_reports_api.py` 等）；前端 `tsc --noEmit` + vitest 全量。
- .3：全量后端测试回基线 + 真实报表页/导出冒烟（导出产物应与现状一致）。

### A.5 回滚

单提交，`git revert` 即可；无数据迁移、无 compose/部署变更，随下次打包生效。

---

## B 节：VM 页千台规模加固

### B.1 背景与规模推演

当前测试现场约 590 VM / 8.96 万卷，页面可用；用户明确目标为**几千台规模仍要可用**（"万一后面有几千台"）。按 5000 VM × ~150 卷/台 ≈ 76 万卷推演，现状缺陷：

1. `/api/vm-volumes` 无分页，一次性返回全部卷（按 VM 分组）→ 响应体数百 MB。
2. 前端 VmsPage 把全部卷 flatten 后全量渲染（`sortedAllVolumes.map`）→ 数十万 DOM 行，页面假死。
3. VM 列表全量渲染（`filtered.map`）→ 数千 DOM 节点勉强可用，但"使用率"排序/标签对每个 VM 过滤全量卷数组，O(VM 数 × 卷数) 比较在千台规模退化明显。
4. `vm_volumes`/`vm_latest` 除复合主键（自带前缀索引，单 VM 查询可用）外无二级索引；全量聚合/排序为全表扫描。

### B.2 目标与非目标

- 目标：5000 VM / 76 万卷规模下，VM 页列表、趋势、卷明细、所有虚拟卷表均可正常浏览与操作；默认口径（使用率标签、排序语义）与现状保持一致。
- 非目标：不改 `/api/vms` 契约（全量列表在 5000 VM 时约 3.5MB，LAN 可接受；>2 万台再立项服务端分页）；不引入虚拟滚动库；不新增容器/组件；不做 Prometheus/SQLite 结构变更。

### B.3 后端变更（全部为可选参数增量，无参行为不变）

1. `VmService.all_volumes` 增加可选参数 `page/page_size/sort/order`：
   - 有 `page` 时返回平铺分页对象：`{"volumes": [...每行含 tower_id/cluster_id/cluster_name/vm_id/vm_name + 卷字段], "total": N, "page": p, "page_size": s}`。
   - 无 `page` 时保持现有「按 VM 分组数组」返回，兼容现状调用与契约。
   - `sort`：`vm`（JOIN `vm_latest` 按名称排序）/ `used`（`used_bytes`）/ `occupied`；`order`：`asc|desc`，默认 `used desc`。
   - `occupied` 排序用 SQL 表达式复刻前端 `getOccupiedSize` 口径（表内无 unique_size 列）：
     `used_bytes * CASE WHEN COALESCE(replica_num,0)>0 THEN replica_num WHEN COALESCE(ec_k,0)>0 AND COALESCE(ec_m,0)>0 THEN (ec_k+ec_m)*1.0/ec_k ELSE 1 END`。
   - 已知取舍：`vm` 排序在 SQLite 为二进制/码点序，非前端 `localeCompare` 的中文拼音序；分页后排序必须服务端完成，此偏差记录为已知限制。
2. 新端点 `GET /api/vm-volumes/usage-summary`（tower_id/cluster_id 可选）：`SELECT tower_id, cluster_id, vm_id, SUM(used_bytes), SUM(size_bytes) FROM vm_volumes ... GROUP BY`（跳过 NULL/非正值行，与前端逐卷 skip 逻辑口径一致），返回 `{"usages": [{tower_id, cluster_id, vm_id, used_bytes, provisioned_bytes}]}`。5000 VM 时约数千行、数百 KB，支撑 VM 列表使用率标签与"使用率"排序，替代对全量卷明细的依赖。
3. `api/vms.py`：`/api/vm-volumes` 增加 query 参数校验（`page>=1`、`page_size` 默认 200、上限 1000）；新增 usage-summary 路由（需登录，同现有 VM 路由权限）。
4. 不新增二级索引：`vm_volumes` 复合主键已覆盖单 VM 前缀查询；分页排序与聚合在全表扫描下 76 万行约亚秒级，先不加索引，量级实测上来再调优（记录于设计，避免过早优化）。

### B.4 前端变更（VmsPage + api.ts + Pager）

1. `api.ts`：新增 `vmVolumesPage(scope, {page, pageSize, sort, order})` 与 `vmVolumesUsageSummary(scope)` 及对应类型；移除仅剩 VmsPage 使用的 `vmVolumesAll`（含 `VmVolumeSet` 类型整理）。
2. VmsPage VM 列表：客户端分页，每页 100 条，新增分页器（上一页/下一页 + 页码 + 共 N 台）；scope/搜索词/排序模式变化时回到第 1 页；外部深链选中 VM（`selectedVmId`）时按其在 `filtered` 中的下标自动跳到目标页，现有 `scrollIntoView` 行为保留。
3. VmsPage 所有虚拟卷表：数据源改为服务端分页（默认 200 行/页）；表头排序按钮改为设置 sort/order 状态并回到第 1 页重新请求；VM 列点击选中行为不变。
4. 使用率口径：新增 usage-summary Map（key: `tower-cluster-vm`），`getVmUsageRatio` 优先取摘要（`SUM(used)/SUM(provisioned)`，与原逐卷求和口径一致），摘要缺失时回退 `item.used_ratio/guest_used_ratio`；`volumesForVm` 及其对全量卷数组的过滤逻辑删除。
5. 新增轻量 `Pager` 组件与样式：遵循 frontend-style-guide（仅 `:root` 变量、6/8px 圆角、既有间距体系），不引入新依赖。
6. VmsPage.test.tsx：mock 从 `vmVolumesAll` 改为 `vmVolumesPage` + `vmVolumesUsageSummary`；现有用例（卷排序、点击卷选 VM、使用率标签）改用分页响应断言；新增「VM 列表分页渲染 ≤100 条且分页器显示总数」用例。

### B.5 测试计划

- 本地：后端 `test_v2_vms_api.py`（新增分页窗口/total/排序三态/usage-summary/无参兼容用例）；前端 tsc + vitest 全量；`scripts/verify_api_docs.py`（api.md 同步新参数与新路由后须 exit=0）。
- .3：全量后端测试回基线；容器重建后真实页面冒烟——VM 页打开、列表翻页、所有虚拟卷翻页与排序、点卷选 VM、趋势/明细正常；用 curl 验证 `/api/vm-volumes?page=1&page_size=5` 与 `/api/vm-volumes/usage-summary` 实际响应结构。

### B.6 回滚

两个独立提交（A 节一个、B 节一个），`git revert` 单独回退；B 无参行为不变，回退前端即可恢复旧交互。
