# 删除升级包误删历史记录 + `.env` 变更连带重建（2026-10-04）

## 1. 背景与触发

r15 候选（`a10bad3`，平台包 `fe534709…`）在 `.3`/`.12`/`.14` 三机验收通过后，收尾阶段
调用了产品接口 `DELETE /api/admin/upgrade/package/{task_id}` 删除两台机器上的测试包。
随后发现**主升级任务记录从历史中消失**，`GET /api/admin/upgrade/status/{task_id}` 返回
404「升级任务不存在」。追查根因，确认两个独立问题。

### 1.1 问题一：`delete_package` 删除整条升级记录

`backend/app/v2/upgrade/service/intake.py::delete_package` 实现为：

```python
shutil.rmtree(task_dir, ignore_errors=True)   # 第 146 行
```

`task_dir` 是整个升级任务目录，其中 `task.json` 是升级历史的**唯一数据来源**：

| 依赖方 | 代码位置 | 目录被删后的行为 |
| --- | --- | --- |
| 升级历史列表 | `execution.py:71` `glob("*/task.json")` | 该条从历史消失 |
| 升级状态查询 | `_read_task_file`（`taskfile.py:238-241`） | 404「升级任务不存在」 |
| 人工回滚 | `execution.py:447` `_read_task_file(task_dir)` | 404（**但见 1.3**） |
| 清理流程的"最近 N 次"竞争 | `cleanup/service.py:144` | 该任务不再参与保留竞争 |

**与 r14 已定口径自相矛盾。** `cleanup/service.py::_purge_upgrade_payload`（r14 提交
`70c6fa0`）已按用户口径「宁留记录不留包」改成只删体积产物、保留 `task.json`：

```python
# cleanup/service.py:177-205
# 保留：task.json（历史记录）、post-upgrade-*.json（采集/清理标记）
# 删除：package/（解包副本）、*.tar.gz / *.sha256（上传的包本体）
```

同一个问题（释放磁盘空间）有两条路径，一条保留记录、一条删除记录，且**删除记录的那条
藏在 UI 按钮后面、没有任何告知**。组件包删除
（`api/admin/upgrade.py:213-218`）复用同一个 `delete_package`，同样受影响。

### 1.2 问题二：改 `.env` 会连带重建 `depends_on` 上的服务

在 `.14` 上为验证磁盘告警真机触发，将 `.env` 的告警阈值改为 30% 后执行
`docker compose --project-name smartx-hci-capacity-insight -f docker-compose.offline.yml up -d collector-worker`
（**只指定一个服务**），结果 `prometheus` 容器被连带重建：

```
Container smartx-hci-capacity-insight-collector-worker-1 Recreated
Container smartx-hci-capacity-insight-prometheus-1 Starting   ← 容器 ID 由 f260269773da7 变为 45db5a1273dc
```

两个条件叠加导致：

1. `collector-worker` 使用 `env_file: [.env]`，Compose 的 `config-hash` 把 `.env` 内容
   计入 → 改 `.env` 即改哈希；
2. `collector-worker` 有 `depends_on: [prometheus]` → `up -d collector-worker` 会把
   prometheus 一并纳入操作范围。

`web-api`/`frontend`/`upgrade-runner` 未被重建，因为它们不在 collector-worker 的依赖链上。

### 1.3 一处需要纠正的先前判断

追查中曾判定「删包 = 永久失去回滚能力」。**该结论夸大，已撤回**：
`execution.py:445-446` 注释明确「US-29：人工回滚已下线（2026-08-28 用户决定）……UI 已隐藏入口。
**失败自动回滚路径（execute_task 异常分支）不受影响**」。自动回滚发生在任务执行期间，
此时任务目录处于活跃态、被 `delete_package` 的状态守卫拒绝，不可能被删。

**故问题一的真实影响只有一条：升级历史记录被静默删除，事后无法追溯升级过程。**
严重性为中等（不可恢复、但可通过严格的操作文档规避），而非数据灾难。

## 2. 目标与非目标

### 目标

- **G1**：`delete_package` 只删体积产物、保留 `task.json`，与 r14 口径一致；
  两条路径（`delete_package` 与 `cleanup_artifacts`）共用**同一份实现**，杜绝再次分叉。
- **G2**：删包后 UI 能正确反映"包已删除、记录仍在"，不出现"按钮还在、点了没反应"。
- **G3**：组件包删除路径与平台包一致（共用实现即自动满足，需测试钉住）。
- **G4**：`.env` 变更导致的连带重建，在执行前**可见**（事前告警），而非事后才发现。

### 非目标

- **N1**：不改人工回滚的上下线状态（US-29 决策保持）。
- **N2**：不重构 Compose 的 `env_file` → 逐项 `environment:`。
  这是消除问题二的根本手段，但需改动全部 5 个服务的环境变量传递，风险远大于收益；
  已评估为过度工程，见 §5.2。
- **N3**：不改动 `intake.py:124` 的 `rmtree`——那是上传失败回滚（提交 `1b0c3dd`），
  语义是"半成品目录一律不留"，与本议题无关。

## 3. 口径与设计

### 3.1 共享实现：抽为模块级函数

现状 `_purge_upgrade_payload` 是 `CleanupService` 的方法，但 `delete_package` 属于
`UpgradeService`（`IntakeMixin`）。二者无继承关系，直接复用会让 `UpgradeService` 依赖
`CleanupService`，引入不必要的耦合。

**设计**：抽为 `backend/app/v2/upgrade/service/fs.py` 的模块级函数
`purge_upgrade_payload(task_dir, record_files) -> int`。`fs.py` 已是升级服务的共享 fs
辅助模块（`_safe_extract`/`_remove_path`/`_sha256_file` 等），符合既有分层。

```python
# fs.py 新增
UPGRADE_RECORD_FILES = frozenset({"task.json"})

def purge_upgrade_payload(task_dir: Path) -> int:
    """只删升级任务目录里的体积产物，保留记录。返回删除条目数。"""
```

`CleanupService._purge_upgrade_payload` 改为薄封装转发（保留方法名以免破坏既有调用点
与测试），`IntakeMixin.delete_package` 同样调用该函数。**记录文件清单只定义一次。**

### 3.2 `delete_package` 的新语义

```
删除：package/（解包副本）、*.tar.gz、*.sha256
保留：task.json、post-upgrade-*.json、小于 64 KiB 的 *.json 标记
活跃守卫不变：status ∈ {running, pending, runner_restarting,
                       recovery_required, rollback_pending, rollback_running} → 400
返回值新增：deleted_count（释放条目数）、space_reclaimed（字节）、kept_record=True
```

保留活跃守卫是关键：**正在执行的升级不能删包**，否则会删掉 runner 正在写入的 `package/`。

### 3.3 `has_package`：让 UI 能反映真实状态

`_public_task()` 增补 `has_package: bool`，判据为任务目录下是否存在体积产物：

```python
has_package = any(
    (task_dir / "package").exists()
    or any(task_dir.glob("*.tar.gz"))
    or any(task_dir.glob("*.sha256"))
)
```

前端 `PlatformUpgradeSection.tsx` 的删包按钮改为按 `has_package` 显示：
- `has_package === true` → 显示「删除升级包」
- `has_package === false` → 不显示（记录仍在历史里，只是包已清理）

**这是必需项而非可选项**：若只改后端，记录仍在 → `started_at` 仍在 → 按钮继续显示 →
点击后无包可删，表现为"点了没反应"，比原来的明确删除更糟。

### 3.4 `.env` 变更事前告警

问题二的**根本消除手段被 N2 排除**，故采用与 US-37 同构的防护：
守卫已有 `SMARTX_COMPOSE_FILE_ACTIVE` 标记机制（`.env` 中的地面真相），
在同一位置增加 `SMARTX_ENV_FILE_SHA256` 标记。

```
执行 compose 前：
  现 .env 的 sha256 与标记一致 → 放行
  不一致 → 打印告警：变更涉及的服务清单 + 依赖关系 + 重建影响，EXIT=2 需显式放行
```

告警内容必须具体到"哪些服务会被重建"，因为本次事故的教训正是**没人预料到 prometheus
会被动**。依赖关系从 compose 文件解析 `depends_on` 得出，不硬编码。

**此改动单独成一个提交**，与功能修复解耦：它修改的是 US-37 已交付的
`delivery/compose-guard.sh`，一旦在客户机上出问题可独立回退，不牵连功能代码。

## 4. 边界与风险

| 风险 | 缓解 |
| --- | --- |
| 删包后 UI 显示"无包"的记录，客户困惑 | 按钮隐藏 + 列表中标注包已清理；文档同步说明 |
| 保留 `task.json` 使 `upgrades/` 长期积累小文件 | 单条 172 KiB，且 `cleanup_artifacts` 已覆盖；实测 18 条记录共 184 KiB |
| 抽函数破坏既有测试对私有方法的引用 | 保留 `CleanupService._purge_upgrade_payload` 作为转发封装 |
| 守卫 sha 标记在客户机上缺失（旧安装） | 标记缺失时**首次写入并放行**，不阻断既有安装 |
| 守卫 sha 在 `.env` 被合法修改后未同步 | 提供显式刷新命令；告警文案中指明该命令 |
| `_purge_upgrade_payload` 对散落 `.tar.gz` 的旧行为 | 函数内保留原逻辑（`task_dir` 非目录 → 整删），行为不变 |

## 5. 备选方案与否决理由

### 5.1 问题一备选

| 方案 | 否决理由 |
| --- | --- |
| 保持现状，仅在 UI 加二次确认弹窗 | 客户仍然永久丢失历史记录；且与 r14 口径矛盾的问题留在代码里 |
| 删除后写一份"墓碑"记录到别处 | 复杂度显著上升；`history` 只扫 `*/task.json`，写别处就要改历史机制 |
| 禁用删包按钮，只保留空间清理页 | 客户失去"刚上传的包传错了想删掉"的正当能力；r14 已确立 `keep_recent` 下限为 1 的自动策略，但手动删单个包仍有价值 |

### 5.2 问题二备选

| 方案 | 否决理由 |
| --- | --- |
| 全部服务改用显式 `environment:` 列举 | 需改动 5 个服务的全部环境变量传递，漏一项即线上故障；且 `.env` 仍是密钥载体，只是形式变化。**过度工程** |
| 拆分 `.env`（密钥一份、服务配置一份） | 缓解有限：改服务配置那份仍触发重建；且动 `.env` 结构影响安装/升级脚本与 US-36 迁移 |
| 只写文档，不加防护 | 2026-09-30 `.3` 事故的教训正是"意外的 recreate 事先无人知晓"；纯文档依赖人阅读，守卫告警是机械保证 |
| 改 `restart: unless-stopped` 之类 | 与 recreate 问题无关 |

## 6. 测试计划

### 后端（`backend/tests/test_v2_upgrade.py` 新增用例）

1. `test_delete_package_keeps_task_record`：构造含 `package/` + `task.json` 的任务目录，
   调 `delete_package` → 断言 `task.json` 仍在、`package/` 已删、返回 `kept_record=True`。
2. `test_delete_package_appears_in_history_after_delete`：删包后 `history()` 仍能查到该任务，
   且 `has_package` 为 `False`。**这条直接钉住本缺陷不复发。**
3. `test_delete_package_rejects_active_task`：`running` 状态 → 400，且目录内容未变。
4. `test_component_delete_package_shares_implementation`：组件路径（同一方法）行为一致。
5. `test_purge_upgrade_payload_keeps_small_json_markers`：`<64 KiB` 的 `.json` 标记被保留。
6. `test_cleanup_and_delete_package_use_same_record_files`：两条路径的保留清单一致
   （防再次分叉）。

### 前端

7. `has_package === false` 时不渲染删包按钮（vitest）。

### 回归

8. `.3` 后端全量（基线 779 tests / 1 既有失败 / skipped=7）。
9. `.3` 前端 `tsc --noEmit` + `vitest run`（基线 11 files / 108 tests）。
10. `.3` 真容器验证：走真实 HTTP 删包 → 查历史仍在 + `has_package` 变 false。
11. 构建 r16 → `.12`/`.14` 预检查 9/9 → 升级 → post-cleanup → 数据不变。

### 守卫

12. `.env` 未变 → EXIT=0；`.env` 变更 → EXIT=2 且告警列出受影响服务；
    显式刷新后 → EXIT=0。`.14` 真机验证（该机为指定实验机）。

## 7. 回滚方式

- 功能修复（§3.1–3.3）：单提交 `fix:`，回退该提交即恢复原行为；
  `.env` 与数据库均不涉及，无数据迁移。
- 守卫改造（§3.4）：单提交 `feat(guard):`，回退该提交即恢复；
  标记为新增 `.env` 键，旧版本守卫忽略该键，无兼容问题。
- 已在 `.env` 写入 `SMARTX_ENV_FILE_SHA256` 的机器：回退后该键成为无害残留
  （旧守卫不解析它），无需清理。
