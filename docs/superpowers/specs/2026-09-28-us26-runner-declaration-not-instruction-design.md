# 设计：US-26 —— 平台包对 runner 只有「声明」没有「指令」

状态：设计（2026-09-28，用户指令「改写」）。**未实施。** 关联 plan：`docs/superpowers/plans/2026-09-28-us26-us27-us28-fix-plan.md` 第 1 节；问题记录 `docs/upgrade-strategy-issues.md` US-26。

## 1. 背景与定性

**现象**：`.12` 现场用组件包把 runner 升到 v0.3.2（`upgrade-9fdaff9a349bc257` succeeded，三方版本一致，存活 90s+），随后用 r6 平台包做 v0.5.3 → v0.5.3 同版本重装（`upgrade-26856095c44869d1` succeeded）→ 结束后 runner **变回 v0.3.1**（容器 tag / 镜像内 `/app/RUNNER_VERSION` / health 三处一致），无任何提示。

**口径（用户 2026-09-28 明确）**：这不是「谁优先」的问题。默认先平台后 runner；**只有平台确需更高 runner（`minimum_runner_version` 高于现场 runner）时才先升 runner**。当前 v0.5.2 → v0.5.3 用已发布 v0.3.1 即可，**runner 不需要动**。所以缺陷是「**够用却动了**」。

**来源追溯（不是有人乱塞）**：runner 条目由 `49-3`（提交 `556a85f feat: literalize source compose image refs`，2026-09-20）引入。该次改造要求三个源码 compose 的镜像引用**全字面量、禁止 `.env` 模板变量**，并加了门禁：

```python
expected_runner = f"{prefix}/smartx-hci-capacity-insight-upgrade-runner:{runner_version}"
if expected_runner not in text:
    raise SystemExit(f"{name} missing literal runner tag: {expected_runner}")
```

为了让「包内 compose 渲染的 runner tag」与「包内声明的 runner 版本」对账，构建时把 runner 也写进 manifest images（`build_upgrade_package.py:1010-1019`，`archive: None` 表示**不带镜像文件、只声明身份**）。

**真正的根因**：`compiler.py:229` 无差别地扫 images 找 runner：

```python
runner_image = next((str(image.get("image")) for image in images
                     if image.get("service") == "upgrade-runner"), "")
```

它**分不清「声明」与「部署指令」**。于是一条只用于对账的身份声明被执行层当成部署指令，最终经 `runner.handoff_target_runtime`（`actions.py:1360`）的 `docker compose up -d --no-deps --force-recreate upgrade-runner` 把现场更高版本降级。

**旁证：tag 多事实源**（三处不一致）：

| 文件 | tag | 写入者 |
| --- | --- | --- |
| `project/docker-compose.yml` | v0.3.1 | 平台包 |
| `compose-runtime/docker-compose.runner-upgrade.yml` | v0.3.1 | 平台包（handoff 写） |
| `compose-runtime/docker-compose.runner-bootstrap.yml` | v0.3.2 | 组件升级 |

**同源证据：设计意图本来就对**。`compiler.py:53` 已有正确示范：

```python
apply_services = [service for service in services if service != "upgrade-runner"]
```

`compose.apply` 明确**不把 runner 列入重建服务**。所以「apply 不该动 runner」的意图存在，**只是 handoff 那条路漏了**。

## 2. 口径（本设计不推翻 49-3）

1. **平台包对 runner 只有「声明」没有「指令」**：manifest 保留 runner 条目用于版本对账，但**不得成为重建 runner 的依据**。
2. **现场 runner 已满足要求（≥ `minimum_runner_version`）时，平台升级零改动**：不重建、不改 tag、不动 compose 文件。
3. **现场 runner 低于要求时，预检查本来就该拒绝**（现有行为正确）；万一放行，handoff 属于兜底路径，必须**显式记录**而非静默降级。
4. **不推翻 `49-3` 的字面量门禁**：三个源码 compose 仍需字面量 runner tag 且与包内基线一致。

## 3. 改动设计

### 3.1 manifest 条目加语义标记（`scripts/build_upgrade_package.py:1010-1019`）

```python
if _version_tuple(version) >= _version_tuple("v0.5.2"):
    manifest_images.append({
        "service": UPGRADE_RUNNER_SERVICE,
        "image": release_image("smartx-hci-capacity-insight-upgrade-runner",
                               _expected_web_api_runner_baseline(version)),
        "archive": None,
        "deploy": False,          # 新增：仅声明身份，不作为部署指令
        "role": "baseline_declaration",
    })
```

- `deploy: False` 是**向后兼容的加法**：旧 runner/web-api 不认识该键会忽略，不会因缺键报错。
- 同步修正 `build_upgrade_package.py:1164` 的包说明措辞（当前写「本包不包含 upgrade-runner」，需补一句「manifest 声明但不携带 runner 镜像」），消除自相矛盾。

### 3.2 编译计划区分声明与部署（`backend/app/v2/upgrade/compiler.py`）

```python
deployable = [i for i in images if i.get("deploy") is not False]
runner_deploy_image = next(
    (str(i.get("image")) for i in deployable if i.get("service") == "upgrade-runner"), ""
)
```

**关键设计决策（此处三选一，必须明确选定）**：

| 选项 | 行为 | 评价 |
| --- | --- | --- |
| **(a) 空串 + 动作跳过** | 取不到部署镜像时，handoff 动作不生成（或生成但 runner 侧识别为「仅迁移运行时、不重建」） | **本次采用**。语义最清晰：没有部署指令 = 不动 runner |
| (b) 动作层 fallback 到现场镜像 | 编译期注入 `preserve_current: true`，动作层据此跳过 `--force-recreate` | 需要 plan 携带现场状态，编译期要读运行时，可行但更绕 |
| (c) 保留包内 tag 并加前置断言 | 动作层比对现场 tag，不同则**报错而非降级** | 行为最保守，但会把「现场更高版本」这种合法状态判为失败 |

**选 (a) 的理由**：它把「平台包不能指挥 runner 版本」变成**结构性保证**——包内根本没有可执行的 runner 镜像，编译器想传递都传不了。选项 (b)(c) 都保留了「包内 tag 参与决策」的路径，未来容易回退。

### 3.3 动作层兜底（`backend/app/upgrade_runner/actions.py`）

`_write_runner_runtime_compose`（:1299）目前空镜像直接抛错：

```python
if not image:
    raise ValueError("runner handoff 缺少 upgrade-runner 镜像。")
```

改为**区分两种缺省**：

- 计划带 `image` → 现有行为（迁移运行时并按该镜像重建；仅老包路径会走到）
- 计划带 `preserve_current: true` 或缺省 image 且现场 runner 已在目标运行时 → **只迁移 compose/network 绑定，不重建容器**，返回 `{"recreated": false, "reason": "field_runner_satisfies_requirement"}`

兜底原则：**宁可不动，也不要降级。**

### 3.4 组件升级侧回写 compose（消除多事实源）

组件升级成功后，把新 tag 同步写入：

- `project/docker-compose.yml` 的 `upgrade-runner.image`
- `compose-runtime/docker-compose.runner-upgrade.yml` 的 `upgrade-runner.image`

使 tag 收敛到「project compose 为准，runtime compose 与其一致」。

> 注：这是**顺带消除 US-26 旁证**（三文件不一致），不是 US-26 根治所必需（根治靠 3.1+3.2）。若实施成本超预期，可降级为独立任务。

### 3.5 测试

| 层 | 用例 |
| --- | --- |
| 单元（compiler） | 计划里 `runner.handoff_target_runtime` / `runner.schedule_target_runtime_handoff` 的 `image` **为空**且带 `preserve_current` 标记；平台三件套的 `compose.apply` 服务列表**不含** `upgrade-runner`（已有行为，加断言固化） |
| 单元（actions） | `preserve_current` + 现场已在目标运行时 → 不执行 `docker compose up`（用 fake executor 断言命令列表为空）；`image` 为空且无 preserve → 仍报错（防真缺镜像被静默跳过） |
| 单元（build） | manifest runner 条目含 `deploy: false`；`verify_upgrade_package_identity` 仍能对账 runner 基线（**不能因新键而失败**） |
| 回归 | 现有 runner 组件升级路径不受影响（组件包自身带 `deploy: true` 语义或走独立分支） |

## 4. 边界（不做）

- **不删 manifest 的 runner 条目**：49-3 的字面量门禁依赖它对账，删了会破坏既有门禁。
- **不改升级顺序口径**：顺序已按条件式定稿，US-26 与顺序无关。
- **不引入「自动升 runner」**：runner 版本变更仍由用户显式组件升级决定。
- **不动 runner 代码**（不 bump 版本）：本次全部在 web-api/编译/打包侧。
- **不改 `minimum_runner_version` 语义**：预检查的「≥」判定已正确。

## 5. 验收标准

1. `.3` 门禁：后端全量、构建 26、`verify_upgrade_package_identity`、`verify_runner_delivery_consistency` 全过；manifest runner 条目含 `deploy: false`。
2. `.12`：**装 v0.3.2 组件包 → 同版本重装 → runner 仍为 v0.3.2**（当前行为会回落到 v0.3.1，这就是修复前后的判别格）。
3. `.12`：平台直升 v0.5.2 → v0.5.3 路径**不受影响**（handoff 仍正确迁移 compose/network 绑定，否则 project/network 会错）。
4. 回归：runner 组件升级路径（`component-upgrade`）仍 succeeded，runner 存活 90s+。

## 6. 回滚

纯代码回滚（4 处改动），无数据迁移、无 schema 变化、无版本号变化。回滚后行为回到当前（现场更高版本会被降级），不影响已发布产物。

## 7. 风险与观测

- **主要风险**：选项 (a) 若在「现场 runner 确实需要被替换」的场景下也不重建，会导致 runner 停留在旧版本。**缓解**：`minimum_runner_version` 预检查会在该场景**先拒绝**；动作层的 `recreated: false` 会记录原因，任务日志与 `verification` 接口可查。
- **观测点**：升级后 `verification` 应显示 runner 的 `recreated` 标志与原因，便于区分「没动」和「动了但失败」。
