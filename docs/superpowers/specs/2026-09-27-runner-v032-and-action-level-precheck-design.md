# 49-50 设计：runner v0.3.2 交付 + 升级预检查「动作级」校验

状态：设计（实施随任务项 49-50）。**涉及 runner，2026-09-27 用户批准「都做」**（AGENTS §6：动 runner 必须用户同意 + 同步 bump 版本号）。

## 1. 背景

- `dab2e0f Release v0.5.2`（2026-08-12）给 runner 加了 `post_upgrade.schedule_collection`（`actions.py +2053 行`）却**没 bump `RUNNER_VERSION`**（仍是 06-29 的 `v0.3.1`），也没重打包、没推 `runner-v*` tag → 同一个 `v0.3.1` 三副面孔（仓库 26 动作 / 发行资产 25 动作 / DockerHub 09-27 前连 v0.3.1 都没有）。
- 交付物实际落后仓库一批修复：UPG-049 legacy 扫描守卫（09-19）、Prometheus legacy 守卫（09-19）、迁移「比较后决策」门禁、`schedule_collection` 动作本身。
- 预检查只做**能力级**校验（`_check_runner_protocol` → manifest 静态 `required_capabilities` vs 心跳 `capabilities`），而旧 runner 也声明 `task.recovery.v1` → 放行，失败落在 cutover 之后。

## 2. 口径

### 2.1 版本 bump（同一次提交完成）

| 文件 | 改动 |
| --- | --- |
| `RUNNER_VERSION`（根） | `v0.3.1` → `v0.3.2` |
| `backend/app/core/config.py` `DEFAULT_RUNNER_VERSION` | → `v0.3.2` |
| `backend/app/v2/config.py` `DEFAULT_RUNNER_VERSION` | → `v0.3.2` |
| `backend/app/upgrade_runner/main.py`（默认值两处） | → `v0.3.2` |
| `docker-compose.yml` / `docker-compose.offline.yml` / `docker-compose.release.yml` 的 `upgrade-runner.image` tag | → `v0.3.2` |

不动的：`frontend/src/components/service/shared.tsx` 的「需要 Runner v0.3.1+」提示（语义是**最低**能力要求，未变）；历史测试夹具里的 `v0.3.1`（与默认值无关）。

### 2.2 组件包与镜像

1. `scripts/build_runner_component_package.py --version v0.3.2`（默认读 `RUNNER_VERSION`）→ SHA 记 `docs/upgrade-package-ledger.md` + `docs/releases/CHANGELOG.md`。
2. 推 git tag **`runner-v0.3.2`** → `.github/workflows/upgrade-runner-image.yml` 构建并推 DockerHub `v0.3.2` + `runner-sha-<sha>` → **tags API 必须 200**（不允许再 404）。
3. 三处同源核对：仓库 `RUNNER_VERSION`+动作表 ｜ 组件包 ｜ DockerHub tag。

### 2.3 预检查动作级校验（防复发闸门）

1. `backend/app/upgrade_protocol/constants.py` 新增：
   - `RELEASED_V031_ACTIONS`：发行资产 `d10e15cf…` 的 25 个动作（注释注明来源 SHA 与 `actions.py` md5 `573dd04b3618d2066b0326c2fd183c8d`）；
   - `RUNNER_ACTION_SUPPORT = {"v0.3.1": RELEASED_V031_ACTIONS, "v0.3.2": frozenset(当前 runner 注册表)}`。
2. `backend/app/v2/upgrade/service/precheck.py` 新增 `_check_runner_actions(manifest)`，挂进 `precheck()` 的 checks：
   - `plan = compile_execution_plan(manifest)`（纯函数，无副作用；runner-only 包跳过）；
   - `version = self._active_runner_version()`（心跳/容器/镜像 tag）；
   - 查表：精确命中 → 用之；**高于**已知最高版本 → 用当前代码集；低于最低或未知 → 视为不支持；
   - `missing = plan_actions - supported` → 非空即 `ok: False`，消息：`当前 upgrade-runner {version} 不支持升级计划动作：{…}。请先在升级中心执行「组件升级」到 v0.3.2 后重试。`，`detail` 带 `runner_version`/`plan_actions`/`supported_count`。
3. **不做**：不改 runner 心跳/`upgrade_runner_state` 表结构（动作级真值以后如需再评估）；不动 `ACTION_CAPABILITIES` 与动作实现。

## 3. 边界（不做）

- 不修改已发布 `d10e15cf…` 资产与 `v0.5.2` 平台包。
- 不把 v0.3.2 设为 v0.5.3 升级的前置条件（A 已保证老现场直升）；v0.3.2 随 v0.5.3 发布一起交付，现场可选先升 runner 拿到 7~9 月的修复。
- 预检查动作级校验只在**源端 ≥ v0.5.3** 时生效（预检查代码跑在源端），不覆盖 `v0.5.2 → v0.5.3` 这一次（那次由 A 解决）。

## 4. 测试计划

- `backend/tests/test_v2_upgrade.py`（或就近新增）：
  - runner `v0.3.1` + 计划含 `post_upgrade.schedule_collection` → `runner_actions` 检查 `ok=False`，消息含「请先…组件升级到 v0.3.2」；
  - runner `v0.3.1` + 计划只有 25 动作内动作 → `ok=True`；
  - runner 版本未知/低于 `v0.3.1` → `ok=False`（提示至少 v0.3.2）；
  - runner `v0.3.2` + 当前计划 → `ok=True`。
- 新增一致性单测：`RUNNER_ACTION_SUPPORT["v0.3.2"] == 当前 upgrade_runner 注册表动作集`（防止改 runner 忘更新表）。
- `backend/build_tests/test_v2_package_builders.py`：compose 三处 runner tag = `v0.3.2`；组件包 builder 产物 `manifest.version == v0.3.2`。
- 远端验收：`.12` 用 v0.3.2 组件包升级 runner → `v0.5.2 → v0.5.3` 成功；`precheck` 对旧 runner（`d10e15cf`）在**需要新动作**的场景能拒绝（可用临时构造的 manifest 触发）。

## 5. 回滚

- 代码：还原 bump 与 `_check_runner_actions` 提交即可。
- 已推送的 git tag / DockerHub tag：**不自动删除**，需用户另行批准后处理（记 ledger）。

## 6. 与方案 A 的关系

A 解决「这次能不能升」，B 解决「以后不再出现同版本不同能力」；A 不动 runner，B 不作为 A 的前置。
