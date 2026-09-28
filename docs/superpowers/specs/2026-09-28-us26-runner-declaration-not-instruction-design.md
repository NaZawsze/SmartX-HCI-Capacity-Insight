# 设计：US-26 —— 平台包对 runner 只有「声明」没有「指令」

状态：**已实施（2026-09-28）**。实施中修正了方案（见 §3.2 方案演进）。 关联 plan：`docs/superpowers/plans/2026-09-28-us26-us27-us28-fix-plan.md` 第 1 节；问题记录 `docs/upgrade-strategy-issues.md` US-26。

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

### 3.2 编译期解析现场 runner 镜像（**实施中修正后的方案**）

**方案演进（重要）**：初版设计是「计划带 `preserve_current: true` + 动作层沿用现场镜像」。实施时发现该方案有两个致命问题，已放弃：

1. **破坏向后兼容（会打挂主路径）**：现场跑的是**已发布 runner v0.3.1**，它不认识 `preserve_current`，看到 `image: ''` 会直接 `raise ValueError("runner handoff 缺少 upgrade-runner 镜像。")` → **v0.5.2 + v0.3.1 → v0.5.3 这条最重要的现场主路径会失败**。而交付决定恰恰是「本次不交付 runner，基线 v0.3.1 可直升」。
2. **违反自己设的边界**：该方案必须改 `actions.py`（runner 代码），而本设计的目标之一正是「不动 runner」；改 runner 需用户同意 + bump 版本（AGENTS §6）。

> 这个漏洞是被交付一致性门禁抓到的：`verify_runner_delivery_consistency.py` 报 `package_image: actions.py md5 != repo`（交付的 v0.3.2 包是改动前的镜像），提示仓库 runner 代码已动。

**最终方案（编译期解析，零 runner 改动）**：

web-api 在 `start()` 编译计划前，把**现场正在运行的 runner 镜像**注入 manifest 副本的 runner 条目，编译器照常把它放进 handoff 的 `params["image"]`：

```
现场 runner v0.3.2  →  计划 image=<现场 v0.3.2>  →  旧 runner 照常执行  →  保持 v0.3.2 ✓
现场 runner v0.3.1  →  计划 image=<现场 v0.3.1>  →  旧 runner 照常执行  →  保持 v0.3.1 ✓
取不到现场镜像      →  回落包内基线（= 当前行为，不会更坏）
```

改动点：

| # | 位置 | 改法 |
| --- | --- | --- |
| 1 | `scripts/build_upgrade_package.py` | runner 条目加 `deploy: false` + `role: baseline_declaration`（语义标注，不影响编译器读取） |
| 2 | `execution.py::_resolve_field_runner_image` | `docker inspect --format {{.Config.Image}} <project>-upgrade-runner-1` 取现场镜像 |
| 3 | `execution.py::_inject_field_runner_image` | 构造 manifest **副本**注入（不改原 manifest，避免污染预检查等读方） |
| 4 | `execution.py::start()` | 编译前调用注入；`compiler.py` 无需改（照常读 `image`） |

**为什么这样才对**：
- 计划里始终是**具体镜像值**，旧 runner 不需要理解任何新概念
- 零 runner 改动、零版本门、零兼容风险
- 现场 runner 够用时保持不动；确实需要换版本时用户走组件升级（写回 compose，见 3.4）

**残余风险**：若 `docker inspect` 不可用（web-api 无 docker socket）→ 回落包内基线 = 当前行为，不会引入新故障。

### 3.3 动作层：**不需要改**（最终方案零 runner 改动）

初版设计的「动作层 `preserve_current` 兜底」已随 3.2 修正一并取消——最终方案下计划始终携带具体镜像，旧 runner 照常执行，**runner 代码零改动**。

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
