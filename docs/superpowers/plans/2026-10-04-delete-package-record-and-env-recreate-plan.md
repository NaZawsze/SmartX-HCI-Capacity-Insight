# 实施计划：删除升级包误删历史记录 + `.env` 变更连带重建

设计：`docs/superpowers/specs/2026-10-04-delete-package-record-and-env-recreate-design.md`

## 提交划分

| # | 提交 | 内容 | 可独立回退 |
| --- | --- | --- | --- |
| 1 | `fix(upgrade):` | 删包只删体积产物 + `has_package` + 前端按钮 | 是 |
| 2 | `docs:` | 文档同步（CHANGELOG/ledger/pending/progress/task_plan） | 是 |
| 3 | `feat(guard):` | `.env` sha 事前告警（改 US-37 已交付物，独立提交） | 是 |
| 4 | `docs:` | 守卫告警的部署文档 | 是 |

## 步骤

### 阶段 A：功能修复（提交 1）

- [ ] A1 `fs.py` 新增模块级 `UPGRADE_RECORD_FILES` + `purge_upgrade_payload(task_dir) -> int`
      - 逻辑从 `cleanup/service.py::_purge_upgrade_payload` 原样迁移，行为不变
      - 保留「`task_dir` 非目录 → 整删」的旧分支
- [ ] A2 `CleanupService._purge_upgrade_payload` 改为转发到 A1 的函数（保留方法名）
- [ ] A3 `IntakeMixin.delete_package` 改调 A1，返回值补 `deleted_count` / `space_reclaimed` / `kept_record`
      - 活跃状态守卫原样保留
- [ ] A4 `_public_task()` 增补 `has_package`
- [ ] A5 前端 `PlatformUpgradeSection.tsx` 删包按钮按 `has_package` 显示
- [ ] A6 补后端用例 1–6（见设计 §6）
- [ ] A7 补前端用例 7
- [ ] A8 `.3` 定向测试 → 全量回归 + `tsc` + `vitest`
- [ ] A9 `.3` 真容器验证：真实 HTTP 删包 → 历史仍在 + `has_package=false`
- [ ] A10 提交 1

### 阶段 B：文档（提交 2）

- [ ] B1 `CHANGELOG.md` v0.5.3「修复」节追加两条
- [ ] B2 `pending-tasks.md` 更新 #81（缺口已关闭）、新增 `.env` 连带重建条目
- [ ] B3 `progress.md` 记录全过程（含本轮三次自身错误）
- [ ] B4 `task_plan.md` 新增 Phase 66 条目 + 更新「Phase 与任务设计文档对照」
- [ ] B5 `docs/doc-map.md` 登记新设计文档
- [ ] B6 提交 2

### 阶段 C：守卫（提交 3、4）

- [ ] C1 阅读现有 `compose-guard.sh` 标记机制，确认接入点
- [ ] C2 新增 `SMARTX_ENV_FILE_SHA256` 标记读写
- [ ] C3 从 compose 文件解析 `depends_on`，生成受影响服务清单
- [ ] C4 `.env` 变更时 EXIT=2 + 告警（含刷新命令提示）
- [ ] C5 标记缺失时首写并放行（不阻断既有安装）
- [ ] C6 补守卫测试
- [ ] C7 `.14` 真机验证三态（未变放行 / 变更拦截 / 刷新后放行）
- [ ] C8 提交 3
- [ ] C9 `deployment.md` 写清 `.env` 变更影响面与刷新命令
- [ ] C10 提交 4

### 阶段 D：r16 验收

- [ ] D1 构建 r16 平台包 + runner 组件包
- [ ] D2 门禁：版本、包身份、runner 一致性 12 PASS、敏感文件
- [ ] D3 包内代码 md5 核对
- [ ] D4 `.12` 预检查 9/9 → 升级 → post-cleanup → 数据不变、runner 未降级
- [ ] D5 `.14` 同上
- [ ] D6 真机验证删包后记录保留（`.14`）
- [ ] D7 `ledger` 登记 r16

## 验收标准

- 后端全量 ≤ 1 个既有失败（`test_start_can_submit_task_for_runner_and_runner_executes_it`），
  无新增失败、无新增 error
- 前端 `tsc` EXIT=0；`vitest` 全过
- `delete_package` 后 `history()` 仍可查到该任务且 `has_package=false`
- 两条清理路径（`delete_package` / `cleanup_artifacts`）保留清单一致
- 守卫三态在 `.14` 真机符合预期
- `.12` 数据逐位不变、runner 未降级


---

## 追加：#80 / #79 / #78 三项（2026-10-04 夜，用户「继续修啊」）

Phase 66 收尾后继续修 pending 列表里可自主推进的三项。#82（runner 锁崩溃）
需 bump `RUNNER_VERSION` 并经用户同意，未纳入。

| 项 | 提交 | 要点 |
| --- | --- | --- |
| #80 损坏文件返回 400 | `955f2fa` | `_read_manifest` 只捕 `JSONDecodeError`，漏 `UnicodeDecodeError` → 穿透成 500。同类修 `_read_task_file`（在调用点包一层，不动 runner 镜像内的 `TaskStore`） |
| #79 回收站页面过滤 | `1fc764b` | 统计侧全量不变；仅 VM 列表与卷列表（grouped + 分页**含 count 查询**）过滤。详情与单 VM 卷列表有意不过滤以保深链可用 |
| #78 报表/迁移/导入自动保留 | `46b6943` | 新增 `exports_retention.py`，TTL + 保留数，`MIN_KEEP=3` 硬下限；接入 `main.py` lifespan |

### 三项共同的验证套路（已固化为习惯）

每个修复都做三件事，否则测试等于没写：

1. **变异测试**：把修复撤回，确认测试失败（#80 撤回后 5 例中 2 例 error；
   #79 撤回后 5 例中 3 例失败；#78 `MIN_KEEP` 3→0 时失败）
2. **核对 `.3` 上跑的确实是新版**：曾因 r16 构建重新解压覆盖了同步目录，
   导致 #80 的测试在旧代码上跑、误判「修复无效」
3. **全量回归**：#78 就是在全量里抓出我漏掉的外层变量声明
   （`nonlocal` 无绑定 → `create_app()` SyntaxError → 4 个 API 用例 error）

### 自身错误汇总（本轮共 7 处）

1. #79 首次插入 `NOT EXISTS` 落错函数（`_latest_vms_from_database`）
2. #79 测试构造 `VmService` 参数顺序错误、读错分页字段名（`items` → `volumes`）
3. #79 验证时 `.3` 上代码陈旧（见上）
4. #80 测试数据 `[:-2]` 并非切在字符中间（UTF-8 仍合法），改为自验证式
5. #78 守护间隔用 `or` 吞掉「0 = 关闭」的语义
6. #78 测试断言把保留/删除的 mtime 方向写反
7. **#78 `nonlocal` 漏外层声明 → `create_app()` SyntaxError**（最严重，靠全量抓出）

### 最终状态

`.3` 全量 **811 tests / 1 既有失败 / skipped=7**（793 + 新增 18）。
三项均已变异测试验证有效性。r17 尚未构建。
