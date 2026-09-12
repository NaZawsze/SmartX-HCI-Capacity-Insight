# P1 基础设施批次设计（SQLite 治理 / 阈值与时区统一 / compose tag 固化）

更新时间：2026-09-12
状态：已定稿，待实施
关联：task_plan.md Phase 49-9/49-3；docs/pending-tasks.md P1 第 2/3/5 项

## 1. 范围

本批次覆盖 P1 三项基础设施任务（产品功能项 Phase 31/预计耗尽算法/Tower UI 剩余项另行立项）：

1. SQLite 治理：WAL + busy_timeout + 时间列索引。
2. 容量阈值统一下发 + 日界时区统一。
3. 源码 compose 镜像 tag 固化（Phase 49-3）。

## 2. SQLite 治理

现状：`V2Database.connect()` 只有 `PRAGMA foreign_keys = ON`；web-api 与 collector-worker 双进程并发读写同一 SQLite 文件，无 WAL、无 busy_timeout，写入冲突时报 `database is locked`；全库零索引。

变更（`backend/app/v2/database.py`）：

- `initialize()` 追加 `PRAGMA journal_mode=WAL`（持久属性，一次设置）。
- `connect()` 每连接追加 `PRAGMA busy_timeout = 5000`（毫秒），写锁冲突时等待而非立即报错。
- `initialize()` 建索引（`CREATE INDEX IF NOT EXISTS`，幂等）：
  - `idx_tasks_updated_at ON tasks(updated_at)`——任务中心列表按 `updated_at DESC` 排序。
  - `idx_collection_runs_started_at ON collection_runs(started_at)`——数据质量/缺采按 `started_at` 过滤。
  - `idx_collection_runs_finished_at ON collection_runs(finished_at)`——最近记录按 `COALESCE(finished_at, started_at)` 排序。
- `vm_latest`/`vm_volumes` 复合主键已覆盖 `(tower_id, cluster_id, ...)` 前缀查询，不额外建索引。

验证：单测断言 `journal_mode=wal`、`busy_timeout` 生效、`sqlite_master` 含三个索引；既有测试回归。

## 3. 容量阈值统一下发

现状：75%/80% 阈值在后端 `dashboard/service.py` 2 处、前端 `DashboardPage.tsx` 3 处（`capacityRisk` 回退、`clusterCapacityTone`、`riskClusterRows` 过滤）各自硬编码，调整阈值必然漂移。

变更：

- 后端：模块常量 `CAPACITY_WARNING_RATIO = 0.75` / `CAPACITY_DANGER_RATIO = 0.80`；`_capacity_risk` 与 `_risk_clusters` 引用常量；payload 增加：
  ```json
  "thresholds": {"warning_ratio": 0.75, "danger_ratio": 0.80}
  ```
- 前端：`DashboardPage` 新增 `RiskThresholds` 读取 `summary.capacity_risk.thresholds`，`capacityRisk`/`clusterCapacityTone`/`riskClusterRows` 改读该值；payload 缺失时回退同值常量（兼容旧后端）。`types.ts` 增加字段。
- `VmsPage` 的 VM 使用率红线语义不同（VM 卷维度），本次不动。

验证：单测断言 thresholds 字段存在且值正确；前端现有 tone 行为测试回归（阈值缺省时行为不变）。

## 4. 日界时区统一

现状：`dashboard/service.py::_day_bounds` 用 `datetime.fromtimestamp(now_ts)`（服务器本地时区）算"当天零点"，项目其他处统一 UTC/`settings.timezone`；容器 TZ 与配置时区不一致时，"本日新建 VM / 日增长"的日界偏移。

变更：`_day_bounds(now_ts, tz_name)` 用 `ZoneInfo(tz_name)` 计算零点（`ZoneInfoNotFoundError`/缺参时回退 UTC），调用点传入 `self.settings.timezone`。

验证：单测固定时间戳断言 Asia/Shanghai 与 UTC 的日界差异。

## 5. compose 镜像 tag 固化（Phase 49-3）

现状：三个 compose 的 image tag 为 `${SMARTX_IMAGE_TAG:-v0.5.2}`，现场 `.env` 的旧 tag 会静默切换镜像版本，违反版本治理"发布包内的 Compose 应写入明确、可审计的镜像身份"。

变更：

- `docker-compose.yml` / `docker-compose.offline.yml` / `docker-compose.release.yml` 中 `${SMARTX_IMAGE_TAG:-v0.5.2}` → `v0.5.2`、`${SMARTX_RUNNER_IMAGE_TAG:-v0.3.1}` → `v0.3.1`（跟随 VERSION 治理，发版时随版本提交同步修改）。
- `SMARTX_IMAGE_PREFIX` 插值保留（镜像仓库地址切换属合法部署参数）。
- `docs/deployment.md` 移除 `SMARTX_IMAGE_TAG/RUNNER_IMAGE_TAG` 作为部署变量的说明；`.env.example` 无此二项（确认即可）。
- 风险：本地开发如需临时切 tag，用 `docker tag` 而非 .env；升级包内 compose 原本就是固定 tag，不受影响。

验证：`test_deployment_config` 回归（该测试不校验 tag，需人工确认三文件不再含 `${SMARTX_IMAGE_TAG`）；grep 门禁加入验证脚本。

## 6. 测试与验收

- 后端新增 `backend/tests/test_v2_p1_infra.py`：WAL/busy_timeout/索引存在、`_day_bounds` 时区、`capacity_risk.thresholds` 字段。
- 前端：DashboardPage 现有测试回归（阈值缺省行为不变）。
- `10.20.11.3`：全量后端回归、前端目标测试、三镜像重建、recreate、健康检查；`grep '\${SMARTX_IMAGE_TAG' docker-compose*.yml` 应为空。
- 完成后勾选 pending-tasks.md P1 第 2/3/5 项与 task_plan.md Phase 49-3/49-9 对应项。
