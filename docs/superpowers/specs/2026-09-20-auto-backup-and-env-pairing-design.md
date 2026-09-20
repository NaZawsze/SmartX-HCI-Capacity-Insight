# 数据库自动备份与导出 .env 配对终态设计（49-25，#24 立项）

- 日期：2026-09-20
- 状态：已实施并验证（2026-09-20）
- 关联：docs/pending-tasks.md #24（用户 2026-09-20「我要终态」立项）、docs/backup-recovery.md
- 关联代码：backend/app/v2/auto_backup.py（新增）、backend/app/v2/migration/service.py、backend/app/v2/cleanup/service.py、backend/app/v2/config.py、backend/app/v2/main.py、backend/app/v2/api/admin/migration.py、frontend/src/components/service/MigrationSection.tsx

## 背景与目标

#24 评估结论（2026-09-20 与用户问答确定）：现有备份全部事件驱动，无周期兜底；异地保管时恢复需"导出包 + 同代 .env"配对，而当前 `.env` 只能 SSH 手工拷贝。用户决策直接做终态：

1. **自动备份能力**：同机周期备份，DB 快照 + `.env` 副本**成对保管**，产品功能可管理；
2. **导出配对终态**：导出任务自动快照同代 `.env` 并在任务中心提供配对下载；产品内提供当前 `.env` 下载入口——消掉 SSH 手工拷贝动作。

## 安全边界（不变量）

- `.env` **不打入**导出包/迁移包 tar（升级包/OVA/导出包禁止包含 `.env` 的规则不变）——包与钥匙分开，下载 `.env` 是独立的管理员显式动作（JWT 保护）。
- 自动备份的 `.env` 副本只落在同机 `backups/`（0600），属于"同机成对保管"，不产生新的传播面。

## Feature 1：自动备份

- 模块：`backend/app/v2/auto_backup.py`，镜像 `freshness.py` 的守护线程模式，在 `create_app` 启动（与新鲜度探针并列），shutdown 停止。
- 调度：`SMARTX_AUTO_BACKUP_INTERVAL_HOURS`（默认 24，**≤0 关闭**）；`SMARTX_AUTO_BACKUP_INITIAL_DELAY_SECONDS`（默认 60，给迁移留启动时间；测试调小）。
- `run_backup()` 步骤：
  1. 集目录 `backups/auto-backup-<UTC时间戳>/`；
  2. 磁盘守卫：`data_root` 可用空间 < 2×(DB+env) 大小 → 记 FAILED 任务"空间不足跳过"，不阻塞业务；
  3. `VACUUM INTO` 生成 `smartx.db` 快照（不锁在线库，与手工冷备同机制）→ `PRAGMA integrity_check` 验证，失败删除集并记 FAILED；
  4. `.env` 副本 `project.env`（0600；源文件不存在时记 warning 行但继续——纯 DB 备份仍有效）；
  5. `manifest.json`：format/created_at/app_version/DB sha256+size/env sha256/源路径；
  6. 滚动保留：目录名字典序（UTC 时间戳天然可排序）保留最新 `SMARTX_AUTO_BACKUP_KEEP`（默认 7）个集，超出删除；
  7. 任务中心 `TaskType.BACKUP`（新枚举值 `"backup"`，前端 kind 映射 `"download"`）记录成败，links 带 db/env/manifest 三个文件。
- 异常不抛出守护线程：异常 → FAILED 任务 + logger.exception。
- 清理集成：「空间清理 → SQLite 备份清理」扫描扩展——`backups/auto-backup-*` **目录**作为条目（filename=目录名，size=目录总大小）；删除选中目录时 `rmtree` **整个集**（DB+env+manifest 成对删，不会出现删了库留下孤儿钥匙）。既有 .db 文件行为不变。

## Feature 2：导出 .env 配对终态

- `V2Settings` 新增 `env_file_path` property：`SMARTX_PROJECT_PATH`（默认 `/data/smartx-storage-forecast/project`）+ `/.env`；容器内 project 目录只读挂载，天然可读，无需新挂载。
- 导出打包完成后调用 `_snapshot_env_for_bundle(bundle_path)`：把 `.env` 拷到同目录同名 `.env` 后缀文件（如 `smartx-capacity-insight-migration-<ts>-<rand>.tar.gz` → 同名 `.env`），0600；`.env` 不存在时跳过并记 warning 行。**全量迁移导出与配置迁移导出都做**。
- 任务 links 追加：`{label: "配对 .env（恢复时必须同代使用）", url: /api/admin/exports/migrations/<同名>.env}`——任务中心链接渲染是通用的，前端零改动即可下载。
- 下载通道：现有 `GET /api/admin/exports/{category}/{filename}`（category=migrations，`.name` 防穿越）天然服务 `.env` 快照，**零路由改动**。
- 独立入口：新增 `GET /api/admin/migration/env-file`（require_user），下载当前 live `.env`（filename=project.env）；404 当文件不存在。用于历史导出记录（无快照）且 `.env` 未重生成时的补配对。api.md 路由表 +1。
- 前端：MigrationSection 导出卡片加「下载当前 .env」按钮（`api.download()` blob 助手 + 本地保存）；配对提示文案加入导出说明。

## 明确不做

- Prometheus 历史不入周期备份（体积大；全量保护走迁移导出包，本身成对）。
- 远端/NFS 同步：用户未提供远端，异地层维持"迁移导出包 + 配对 .env 人工下载拿走"。
- 不改变升级前备份/导入前备份机制。

## 测试计划

1. `tests/test_v2_auto_backup.py`：run_backup 产物三件齐全、integrity_check 通过、manifest sha 正确、retention 修剪保留 N、磁盘不足跳过、`.env` 缺失时降级、interval≤0 不启动守护线程。
2. `tests/test_v2_cleanup.py`：scan 含 auto-backup 目录条目；删除目录成对移除。
3. migration 测试：导出生成同名 `.env` 快照 + task link；`/api/admin/migration/env-file` 401/200/404。
4. .3：全量测试回基线、verify_api_docs（77 条）、真实执行一次 run_backup + 导出配对下载验证。

## 回滚方式

单提交 revert；自动备份默认开启但可 `SMARTX_AUTO_BACKUP_INTERVAL_HOURS=0` 关闭；不改任何既有默认行为（清理扫描为增量扩展、导出新增文件不影响既有下载）。
