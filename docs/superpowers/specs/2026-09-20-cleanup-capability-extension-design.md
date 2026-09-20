# 空间清理能力扩展设计（49-24）

- 日期：2026-09-20
- 状态：已实施并验证（2026-09-20）
- 关联：docs/pending-tasks.md #21（测试机环境卫生）、#25（49-3）、task_plan.md Phase 49
- 关联代码：backend/app/v2/cleanup/service.py、backend/app/v2/api/admin/system_admin.py、frontend/src/components/service/CleanupSection.tsx、frontend/src/components/service/shared.tsx（CleanupDialog）、frontend/src/components/service/PlatformUpgradeSection.tsx

## 背景

产品已有「空间清理」（系统运维页）：运行产物清理（upgrades/exports 四目录全清）、SQLite 清理整理、SQLite 备份删除、悬空镜像清理。2026-09-20 盘点 pending-tasks #21 时确认两个能力缺口：

1. **未使用镜像清理不了**：`cleanup-images` 只扫 dangling 镜像（`service.py` 硬编码 `--filter dangling=true`），"有 tag 但未被任何容器使用"的镜像（如 .12/.3 残留的旧项目名镜像 `nazawsze/smartx-storage-forecast-*`）产品内无法清理，只能手工 `docker rmi`。
2. **运行产物清理是全清**：`cleanup-artifacts` 删除 upgrades/ 等四个目录全部子项，会连最近一次验证的升级任务目录一起删掉；且没有任何"正在执行升级"守卫，理论上可删掉在跑任务正在使用的上传包。

## 目标

- 产品内可清理"未被任何容器使用的非本产品仓库镜像"（覆盖 #21②）。
- 运行产物清理支持"保留最近 N 个升级任务目录"（缓解 #21① 的全清副作用）。
- 运行产物清理增加在跑升级任务守卫（fail-closed）。

## 口径与边界

### 镜像清理（关键安全约束）

**回滚依赖本地旧版本镜像**：`upgrade_runner/actions.py::rollback_restore` 恢复升级前备份的项目文件（compose 引用旧版本镜像 tag）并重建容器，因此删除本产品仓库的旧版本镜像会打断回滚能力。据此：

- **保护规则**：仓库地址包含 `smartx-hci-capacity-insight-`（web-api / collector-worker / frontend / upgrade-runner，任意 registry 前缀）的镜像一律不进入可清理集合，即使未被容器引用；扫描结果在 `protected_images` 中透明列出（含大小）并在 message 说明。
- **可清理集合** = 悬空镜像（dangling，现有行为不变）∪ 未被任何容器引用且非保护仓库的有 tag 镜像。
- **used 判定**：`docker ps -a --format '{{json .}}'` 收集全部容器（含停止）的 `Image` 字段（可能为 repo:tag 或镜像 ID/短 ID），与 `docker image ls --format '{{json .}}'` 的 RepoTags 和 ID 匹配；任一匹配即 used。
- **删除接口**：`POST /api/admin/system/cleanup-images` 请求体可选 `{"image_ids": [...]}`。空/缺省 = 清理全部可清理候选（向后兼容）；指定 IDs 时逐个校验：先重新扫描，ID 必须在可清理集合内，否则跳过并记录原因（fail-closed）；执行 `docker image rm`（不带 `-f`），docker 自身的容器引用守卫兜底。
- 悬空镜像不适用保护规则（无 tag，rollback compose 按 tag 引用，悬空镜像不构成回滚依赖），保持现行行为。

### 运行产物清理

- `POST /api/admin/system/cleanup-artifacts` 请求体可选 `{"keep_recent_upgrades": <int 0~100>}`，默认 0（= 现行全清，向后兼容）。
- `keep_recent_upgrades` 只作用于 upgrades 目录子项：按 mtime 降序保留最近 N 个子项（目录或散文件都算一项），其余删除；reports/migrations/imports 行为不变（全清）。
- **在跑任务守卫**：存在 `type=upgrade` 且 `status ∈ {pending, running}` 的任务时，整个 cleanup-artifacts 拒绝执行（`ok=false` + 说明消息，不删任何文件）。post_upgrade_cleanup 任务 type 也是 upgrade，一并覆盖。
- 不新增配置项/环境变量，保留数由请求传入（前端默认 0）。

### 明确不做

- Prometheus 数据、容器日志、`exports/migration-tasks/`、compose-runtime、升级前备份不在清理范围（维持现状；备份删除仍仅限 SQLite 备份白名单前缀）。
- 不提供本产品仓库旧版本镜像的产品内清理入口（保回滚）；确需释放时由运维手工 `docker rmi` 并自行确认回滚不再需要，文档记录该口径。
- 不改悬空镜像现行清理行为。

## API 变更

| 端点 | 变更 |
| --- | --- |
| `GET /api/admin/system/cleanup-images/scan` | 响应扩展：`images[].category`（`dangling`/`unused`）、`protected_images[]`（id/repo_tags/display_name/size/size_label）、`protected_count`、`protected_size_label`；`images` 仅含可清理候选（兼容：原有字段不变） |
| `POST /api/admin/system/cleanup-images` | 请求体可选 `{"image_ids": []}`；响应不变 |
| `POST /api/admin/system/cleanup-artifacts` | 请求体可选 `{"keep_recent_upgrades": 0}`；响应 logs 增加保留说明 |
| 其余端点 | 不变 |

## 前端变更

- 运行产物清理卡片：一键清理旁新增「保留最近 N 个升级任务」数字输入（默认 0，0=全部清理），警示文案补充保留口径。
- 镜像清理对话框（CleanupDialog）：列表行加复选框（默认全选可清理候选），按候选/受保护分组展示；受保护镜像只读展示并说明回滚保护原因；「开始清理」按选中 IDs 调用。

## 测试计划

1. 单测（backend/tests/test_v2_cleanup.py）：
   - keep_recent_upgrades：3 个不同 mtime 任务目录，keep=2 只删最旧；keep=0 全删（现有用例覆盖）。
   - 在跑守卫：构造 running 升级任务，cleanup-artifacts 拒绝且不删文件。
   - 镜像分类：FakeExecutor 模拟 docker image ls（dangling/普通/保护仓库）+ docker ps -a，断言 category、used 排除、protected 排除与透明列出。
   - 按 ID 删除：指定 IDs 只删对应镜像；请求保护仓库 ID 被拒绝。
   - API 层：cleanup-artifacts 带 body、cleanup-images 带 image_ids 的 200 路径。
2. 契约：api.md 同步两个端点请求体与响应扩展；.3 上 `scripts/verify_api_docs.py` 通过。
3. 前端：`npx tsc -b` + vitest 通过；.3 构建验证。
4. .3 真实验证：镜像扫描能看到分类与保护列表；对 .3 上旧项目名镜像执行真实删除（可逆：镜像可重新 load/pull）；运行产物清理 keep 参数真实执行一次（保留最近任务目录）。

## 回滚方式

单提交，纯增量扩展（默认参数下行为与现状一致），revert 单提交即回滚；不改任何存量默认行为（keep 默认 0、image_ids 缺省全清、dangling 行为不变）。
