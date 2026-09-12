# P3 工程健康度批次设计（helper 收敛 / 吞错清理 / CORS 收紧）

更新时间：2026-09-12
状态：已定稿，待实施
关联：task_plan.md Phase 49-9/49-10 残留项；docs/pending-tasks.md P3 #16/#18/#19

> 三个任务均为小体量、互不依赖的工程卫生项，按 AGENTS 开发流程以合并设计方式立项（合并理由：单项均不足一份完整设计的信息量）。

## 1. 复制粘贴 helper 收敛（#16）

- `backend/app/v2/metrics/series.py` 新增规范实现：
  - `cluster_key(labels) -> (int, str)`：`(int(labels.get("tower_id") or 0), str(labels.get("cluster_id") or ""))`
  - `vm_key(labels) -> (int, str, str)`：cluster_key + `(…, str(labels.get("vm_id") or ""))`
- dashboard / vms / reports-service / data_quality 四处删除本地 `_cluster_key/_vm_key`，改 import 别名（调用点不变）。
  - data_quality 现为 try/except 防御式实现；规范实现 `or 0` 语义在 Prometheus 数字标签场景下等价，统一后其 except 分支不再触发（行为差异仅存在于非法标签值，可接受，测试回归确认）。
- **不收敛**：`reports/export.py::_cluster_key` 返回 `(str, str)`（展示用途，语义不同），保留并加注释；`services/*` 为 v1 死代码，随 #14 移除。
- `_int_or_none`：`database.py` 与 `migration/service.py` 语义完全相同（跳过 None/""，`int(float(v))`）→ 收敛到新模块 `backend/app/v2/parsing.py::int_or_none`；`collection/service.py`（不跳 ""）与 `cloudtower/client.py`（经 _number 取首个可解析值）语义不同，保留并注释。

## 2. 静默吞错清理（#18）

- `App.tsx`：新增 `tasksError` 状态；`refreshTasks` 失败时记录、成功时清除（summary 已有同机制）。
- `AppLayout` 数据状态横幅扩展：summary 失败与 tasks 失败任一存在即显示，文案区分"容量数据"与"任务列表"。
- 其余 `catch(() => undefined)`（ServicePage 版本号拉取、clearTasks/markTasksSeen 即发即忘等）为可接受设计，保留并注释 `fire-and-forget`。

## 3. v2 CORS 收紧（#19）

- 现状：`v2/main.py` `allow_origins=["*"]` + `allow_credentials=True`；实际部署前端经 nginx 同源代理 `/api/`（`API_BASE` 为空），CORS 中间件默认并无必要。
- 变更：`V2Settings` 新增 `cors_origins: tuple[str, …]`（`SMARTX_CORS_ORIGINS` 逗号分隔，默认空）；`create_app` 仅在列表非空时挂 CORS 中间件（`allow_origins=list` + `allow_credentials=True`）。
- `.env.example` / `docs/deployment.md` 已有 `SMARTX_CORS_ORIGINS=*` 说明，改为"跨域部署时才配置，同源部署留空"。

## 4. 测试与验收

- 后端：series key 新增单测；data_quality/dashboard/vms/reports 回归；CORS 单测（无配置时不出现 CORS 头、配置后带 allow 头）。
- 前端：AppLayout 横幅断言扩展（tasks 失败显示）。
- 远端 .3：回归 + 部署 + 健康检查；浏览器同源访问不受影响（无 CORS 头也能正常调用）。
