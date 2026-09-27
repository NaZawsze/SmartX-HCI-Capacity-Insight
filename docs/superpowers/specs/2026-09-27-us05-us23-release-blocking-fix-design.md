# 设计：US-05 / US-23 发布阻塞项修复（post-cleanup 顺序敏感 + 升级并发无互斥）

状态：设计（2026-09-27，用户指令「你写修复设计文档吧」）。实施前须用户批准；实施后须重打 v0.5.3 候选包并跑 MVP 审计格。

## 1. 背景

### US-05：post-cleanup 健康断言"版本相等"→ 升级顺序敏感
- **代码**：`backend/app/upgrade_runner/actions.py:1884-1886`（`_require_cleanup_health`）
  ```python
  expected_runner = str(required.get("runner_version") or "")
  if expected_runner and str(payload.get("runner_version")) != expected_runner:
      raise RuntimeError(f"清理前 runner 版本不匹配：{payload.get('runner_version')}")
  ```
- **打包侧**：`scripts/build_upgrade_package.py:551` 的 `required_health` 写入 `"runner_version": <基线>`（当前 = 已发布 `v0.3.1`）。
- **后果**：现场若**先**把 runner 升到 `v0.3.2` 再升平台 → 平台升级成功、**post-cleanup 失败**（「清理前 runner 版本不匹配」）→ 旧环境不清理、残留累积。第四轮只验了"先平台"顺序（`upgrade-666284beec04cc87`），另一条顺序未验且必然失败。

### US-23：并发升级无「单飞」守卫
- **代码**：`backend/app/v2/upgrade/service/execution.py:42`（`start()`）只校验**本任务** `precheck_passed`，不检查是否已有其它升级在执行；runner 侧 `run_pending_once` 按 mtime **串行**消费所有 pending 任务。
- **后果**：两个包先后上传并预检通过 → 两次 `start` 都放行 → 第二个任务执行时**环境已被第一个改变**（版本/项目/目录/镜像），而其执行计划按旧状态编译 → 在错误状态上执行（失败或"成功地做错事"）。
- **讽刺证据**：删除任务倒有保护（`intake.py:81`「升级任务正在执行…不能删除」），唯独 `start` 漏了。
- **入口**：平台升级 `POST /api/admin/upgrade/start/{tid}`（`api/admin/upgrade.py:46`）与组件升级 `POST /api/admin/component-upgrade/start/{tid}`（`:179`）**都走同一个 `upgrade.start()`** → 一处守卫覆盖两个入口。

### 关联
- 问题清单：`docs/upgrade-strategy-issues.md` US-05 / US-23（P0）
- 审计矩阵：`docs/upgrade-audit-matrix.md` MVP 格 M3-08 / M3-10（先 runner 后平台）、「重复 start」干扰列
- 顺序背景：US-04（老 web-api 无条件 stop，**本设计不修**，见 §4）

## 2. 修复口径

### 2.1 US-05：`required_health` 不再声明 `runner_version`（只改打包脚本，一行）

`scripts/build_upgrade_package.py:551`：

```python
# 修复前
"required_health": {
    "version": target_version,
    "runner_version": _expected_web_api_runner_baseline(target_version),
    "checks": ["directories", "database", "prometheus"],
},
# 修复后
"required_health": {
    "version": target_version,
    "checks": ["directories", "database", "prometheus"],
},
```

- **原理**：`_require_cleanup_health` 的 `if expected_runner` 在字段缺失/为空时**自动跳过**该校验（`actions.py:1884`），**无需改 runner、无需 bump 版本**。
- **为什么删而不是改成 `v0.3.2` 或列表**：合法终态有两种（`v0.3.1` 直升 / `v0.3.2` 先升后平台），任何单一期望值都会拒绝另一种顺序；等值断言与"顺序无关"天然冲突。
- **失去的检查与补偿**：
  | 失去 | 补偿 |
  |---|---|
  | 升级后 runner 版本 == 期望 | ① post-cleanup 仍校验**平台版本**（`version`，升级后必然 = target，无顺序问题）+ 三项 health；② 预检查 `runner_actions` 闸门校验"计划动作 runner 全部支持"（v0.5.3 源端）；③ 8 项验收仍核对 runner 容器镜像 tag |
- **保留 `version` 等值**：平台版本在升级后必然等于 target，不受顺序影响，不删。

### 2.2 US-23：`start()` 增加「单飞」守卫（web-api 侧，一个函数）

`backend/app/v2/upgrade/service/execution.py` 新增模块级/类方法守卫，并在 `start()`（`:42`）状态检查**之后**调用：

```python
_ACTIVE_UPGRADE_STATUSES = {
    "pending", "running", "runner_restarting", "recovery_required",
    "rollback_pending", "rollback_running",
}

def _ensure_no_active_upgrade(self, exclude_task_id: str) -> None:
    """49-52：单飞守卫——已有升级（平台/组件/post-cleanup）在执行或待恢复时，禁止开始新升级。

    两个入口（平台 /api/admin/upgrade/start 与组件 /api/admin/component-upgrade/start）
    都经过 start()，故一处守卫全覆盖。直接改 task.json 绕过 API 不属于产品流程，不设防。
    """
    for task_file in sorted(self.settings.upgrades_dir.glob("*/task.json")):
        task_id = task_file.parent.name
        if task_id == exclude_task_id:
            continue
        try:
            task = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(task.get("status") or "") in _ACTIVE_UPGRADE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"升级任务 {task_id} 正在执行或需要恢复，不能开始新升级。",
            )
```

调用点（`start()` 内，本任务状态检查通过后）：

```python
if task.get("status") != "precheck_passed":
    raise HTTPException(status_code=400, detail="预检查通过后才能开始升级。")
self._ensure_no_active_upgrade(task_id)   # ← 新增
```

- ** ACTIVE 集合不含 `precheck_passed`**：允许多个包同时处于"预检通过"待命（现状能力，不收紧）。
- **含 `post-cleanup-*` 任务**：post-cleanup 运行期间同样禁止新升级（它在动 compose/legacy，互斥更安全）；其任务目录就是 `post-cleanup-<tid>`，天然被扫到。
- **排除自身**：当前任务自身不算（它此刻是 `precheck_passed`，本就不在 ACTIVE 集合；显式排除是为防未来状态集合变化）。
- **不做 runner 侧重验**（执行前重验 source_compatibility）：那需要改 runner → bump 版本，收益有限（web-api 入口已拦），**不在本次范围**。

### 2.3 US-04 缓解（仅文档，不改代码）

- v0.5.2 老 web-api 的无条件 stop **改不到**（源端老镜像），本次只在**发布材料与升级中心文档**写死顺序：
  > **先升平台（v0.5.3），再做 runner 组件升级（v0.3.2）。** 在 v0.5.2 平台上先做 runner 组件升级会导致新 runner 被停止（已知问题，v0.5.3 已修复）。
- 前端在组件升级卡显示顺序提示：**列为可选后续**（见 §4），不在本次。

## 3. 实施与打包

1. 提交两处代码改动（`build_upgrade_package.py` 一处、`execution.py` 守卫）+ 新测试。
2. **重打 v0.5.3 候选包**（新 SHA，取代 `e1c0fde8…`）：`--check-version` / identity / `.sha256` / 敏感 0。
3. `.3` 门禁全量重跑：后端全量（377+新增）、构建 26、前端 tsc/vitest、api docs、release docs。
4. `.12` 端到端（MVP 对应格）：
   - **M3-08 / M3-10**（v0.5.1u2、v0.5.2 × **先 runner 后平台**）：平台升级 post-cleanup **必须成功**（US-05 验证）
   - **重复 start**：第二个任务 start 必须 400 且消息含「正在执行」（US-23 验证）
   - **平台先**顺序既有链路回归不受影响（回归 1 格）
5. 记账：ledger 新包行、CHANGELOG、AGENTS 候选 SHA、issues 文档 US-05/US-23 状态转 🟢、审计矩阵对应格打 ✅。

## 4. 边界（本次不做）

- 不改 runner 代码、不 bump `RUNNER_VERSION`（两处修复均在 web-api/打包侧）。
- 不修 US-04 根因（老 web-api 改不到）；前端顺序提示列为可选后续。
- 不做 runner 执行前重验 source_compatibility。
- 不做磁盘空间校验（US-07）、任务噪音清理（US-09）、采集链路事件驱动（US-06）——归 #47。
- 不动已发布物（`d10e15cf`、`692aca8b`、`e1c0fde8` 中间候选仅被取代不回改）。

## 5. 测试计划

### 5.1 单元测试（新增 `backend/tests/test_upgrade_single_flight.py`）
1. 存在其它任务 `running` → `start` 400，detail 含「正在执行或需要恢复」
2. 参数化：`pending` / `runner_restarting` / `recovery_required` / `rollback_pending` / `rollback_running` → 400
3. 其它任务仅 `precheck_passed` / `failed` / `succeeded` / `cancelled` / `uploaded` → **放行**
4. 排除自身：自己 `precheck_passed` 时 `start` 自身成功
5. 组件升级入口（`submit_to_runner=True` 路径）同样被拦
6. `post-cleanup-*` 任务 running 时 → 400（升级期间互斥）

### 5.2 构建测试（改 `build_tests/test_v2_package_builders.py` 断言）
- manifest `required_health` **不含** `runner_version`、仍含 `version` 与 `checks: ["directories","database","prometheus"]`
- 既有 identity / compose / manifest 断言不受影响

### 5.3 `.12` 端到端（见 §3.4，对应审计 MVP 格）
- M3-08 / M3-10 先 runner 后平台 → 主任务 + post-cleanup 双成功、8 项验收（runner=v0.3.2）
- 重复 start 干扰 → 第二次 400
- 平台先顺序回归 1 格 → 全绿

## 6. 回滚方式

- 代码：还原两个提交（打包一行 + 守卫函数及其调用），无数据迁移、无 schema 变化、无版本号变化。
- 包：候选包回退到 `e1c0fde8…`（ledger 保留两行，旧的标 SUPERSEDED）。
- `.12`：按既有基线固化（`/root/baselines/v053-r4-baseline-20260927`）重跑即可还原。

## 7. 验收标准（全部满足才算修复完成）

1. `.3`：后端全量（含新增单飞用例）OK、构建 26 OK、前端 OK、api docs / release docs OK
2. 新候选包门禁全过，manifest `required_health` 无 `runner_version`
3. `.12` M3-08 / M3-10：先 runner 后平台 → **post-cleanup succeeded**（修复前必失败的对照已有第一轮证据）
4. `.12` 重复 start → 400
5. 平台先顺序回归全绿
6. 文档同步：issues（US-05/23 → 🟢）、审计矩阵对应格 ✅、ledger/CHANGELOG/AGENTS 更新
