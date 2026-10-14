# 「代码有、真机零覆盖」升级路径盘点与补验证设计（pending #91）

- 日期：2026-10-14
- 来源：US-40 教训（从没跑过的路径第一次就炸）+ 用户追问 Prometheus 升级通道
- 状态：设计（待实施：盘点 + 逐条 `.14` 演练）

## 1. 背景：为什么需要这个专项

US-40 的形态值得记牢：**代码在、单测在、设计在，但该路径从未在任何真机执行过**——
第一次真机执行（`.3` 升 r34）就必然失败（沙箱脚本挂载用容器内路径），并连带产生
「既有环境必须先组件后平台」的顺序约束。同类风险仍在别处存在，**必须在客户之前自己先踩**。

本任务 = ①把这类路径**盘一遍**；②逐条在可自由操作的 `.14` 上演练并留证据；
③把「上客户前必须先演练」写成纪律。

## 2. 盘点（当前已识别 3 条，实施时补全）

| # | 路径 | 现状 | 处理 |
| --- | --- | --- | --- |
| 1 | 迁移沙箱 `script.run_sandboxed`（`run-migration`） | **已炸（US-40）→ 已修（r35）→ 已真机验（2026-10-08）** | 关闭，留档 |
| 2 | 存量站点守卫投递 + `.env` 标记回填（US-39） | 实现已在（Phase 68），**「老版本升级上来的存量站点」这条路径未真机验** | 见 §3.2 |
| 3 | **Prometheus / observability 组件升级** | 通道与工具齐备、**progress/ledger 无任何真机执行记录** | 见 §3.3 |

**盘点方法**（实施时执行，避免只靠回忆）：
- 枚举「升级计划动作表」与「组件类型表」，逐个动作/组件问：**有没有真机执行证据？**（progress/ledger grep）；
- 枚举 runner 动作实现（`upgrade_runner/actions.py`）里**带宿主/容器路径、挂载、docker 调用**的分支
  （US-40 就出在这里）；
- 枚举「只在特定条件才出现」的路径（带迁移的包、observability 组件、旧布局源、回滚三场景…）。

## 3. 逐条演练设计（全部在 `.14`，不碰 `.12`）

### 3.1 通则
- 每条约 30–60 分钟；**先记录基线**（版本、容器 ID、业务计数、`.env` sha、Prometheus 数据目录大小）；
- 走**产品流程**（Web 上传/组件升级 或 `upgrade.sh`），不做宿主手工变更；
- 结束时必须回答三问：**成功了吗？数据还在吗？能回退吗？**
- 证据落 `progress.md` 当日节 + 本文件的结果表。

### 3.2 存量站点守卫投递/标记回填（US-39）
1. `.14` 用**老交付包**（不含守卫脚本的版本，如 delivery-v053）安装 → 确认 project 目录**无**
   `compose-guard.sh`、`.env` **无** `SMARTX_COMPOSE_FILE_ACTIVE`；
2. 按 v0.5.4 顺序升级（组件 r35 → 平台 r34）；
3. 断言：project 目录**出现** `compose-guard.sh`（0755、内容与 `delivery/compose-guard.sh` 一致）、
   `.env` **出现**标记且值 = 运行中容器的 `config_files` basename；
4. 幂等：再跑一次升级 → 标记不被覆盖、脚本不重复追加；
5. 跑 `scripts/verify_site_acceptance.sh` 第 ⑤ 项应 PASS。

### 3.3 Prometheus 组件升级（当前最典型的一条）
**通道事实**（已代码核实）：打包 `scripts/build_prometheus_component_package.py`；入口 = Web
「服务管理 → 组件升级」（组件目录含 `observability/prometheus` 项）；计划 =
`image.load → compose.override → compose.apply → health.prometheus`（探 `/-/healthy`，30×2s）；
`health.prometheus` 在 v0.3.1 能力表内 ⇒ **执行不需要升 runner**；TSDB 数据在宿主
`/data/smartx-storage-forecast/prometheus` 绑定挂载（容器 `/prometheus`），换镜像不动数据。

**步骤**：
1. `.14` 记录基线：prometheus 容器 ID、`/-/healthy`、数据目录大小、`up` 等关键序列样本数；
2. 在 `.3` 打包：`python3 scripts/build_prometheus_component_package.py --version v2.55.1
   --offline-image`（**离线必须带 `--offline-image`**；不带则 manifest 无 `archive`，预检查会报
   「本地 Docker 镜像不存在」——这正是设计上的拦截，见下）；
3. Web 上传组件包 → 预检查（应含「校验组件镜像与 SHA256」「检查观测组件数据权限」两项）→ 开始升级；
4. 断言：任务 succeeded、`health.prometheus` 通过、**容器 ID 变化但数据目录大小与序列样本数不减少**、
   平台其余容器未被重建（prometheus 之外零扰动）；
5. **反例验证**：用**不带镜像**的包（不加 `--offline-image`）在镜像不存在的现场上传 → 预检查必须
   **失败**并给出「本地 Docker 镜像不存在：prom/prometheus:vX」+ 引导（不可静默通过）；
6. 回退：保留旧镜像 → 用旧 tag 重新 `compose.apply`（或按平台回滚流程），确认能回到原版本。

**跨大版本附加核查**（若升 2.x → 3.x）：查官方 migration guide 的 flag/配置弃用；
本项目只换镜像不改配置 ⇒ 若新版不兼容现有 `prometheus.yml`/启动参数，容器起不来 → 健康门拦住、
任务失败、旧镜像仍在（失败安全）。**结论写进文档**。

## 4. 边界与不做

- **只在 `.14`** 演练；`.12` 不碰（AGENTS §5）；`.3` 仅做只读诊断与打包；
- 不为造证据改宿主文件（阈值/配置）；
- 不把「未演练」的路径写进客户文档当"已支持"；演练未过的路径在文档里标注"未验证"。

## 5. 验收

1. 盘点表补全（每条：有/无真机证据 + 证据位置）；
2. ②③ 两条演练完成并留证（成功/失败都算结论，失败要转成任务）；
3. 纪律入文：`docs/development-verification-process.md` 增一节「零覆盖路径上客户前必须先在 `.14` 演练」；
4. 本文件末尾维护结果表（路径 / 日期 / 结果 / 证据位置 / 后续任务）。
