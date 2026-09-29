# CLI 工具链实施计划：安装 / 升级 / 打包三件套

- 日期：2026-09-30
- 设计：[`../specs/2026-09-30-cli-toolkit-design.md`](../specs/2026-09-30-cli-toolkit-design.md)
- 关联：task_plan 第 58 项、pending-tasks #58
- 状态：待执行

## 0. 前置检查（开工前必须过）

- [ ] 设计文档已定稿（Q1–Q6 全部有决策）
- [ ] `.3` 工作树已同步当前 HEAD
- [ ] 基线门禁已知通过：后端 647 tests OK、build_tests 26 OK、runner 交付门禁 12 PASS

## 1. 步骤 1：`cli/lib/common.sh` + `cli/check-deps.sh`

**产出**：`cli/lib/common.sh`（日志/颜色/错误处理/确认）、`cli/check-deps.sh`（9 项体检）

- [ ] 1.1 `common.sh`：彩色日志（`info`/`ok`/`warn`/`err`）、`die()`（统一 exit 2）、`confirm()`（交互确认，`--yes` 跳过）
- [ ] 1.2 `check-deps.sh`：按设计 §6.1 逐项实现，**每项 MISSING 必须带可执行命令**
- [ ] 1.3 退出码：0=全 OK / 2=有 MISSING
- [ ] 1.4 加 `.gitignore`（`cli/packages/` 不入库）
- [ ] 1.5 **单测**：`backend/tests/test_cli_toolkit.py`，用假 PATH / stub 命令验证缺依赖时的退出码与提示文案
- [ ] 1.6 门禁：`.3` 跑单测；`bash -n` 语法检查
- [ ] **实测 T1**（干净 VM 无 Docker）：退出码 2 且提示可执行
- [ ] **实测 T7**：全程无安装动作（`grep` 确认脚本内无 `yum install`/`apt install`）

**验收判据**：T1、T7 通过。

## 2. 步骤 2：`cli/package.sh`

**产出**：`cli/package.sh`（一键打包，12 步流程见设计 §5.1）

- [ ] 2.1 参数解析：`--branch`（默认 `main`）、`--yes`、`--output-dir`（默认 `cli/packages`）、`--skip-checks`
- [ ] 2.2 第 2 步：调 `check-deps.sh`，exit 2 直接退出（Q2：非 Linux / 缺 Docker 提前拒绝）
- [ ] 2.3 第 3–4 步：git `fetch --prune` + `checkout` + `reset --hard`，**有本地改动时交互确认**（Q1）
- [ ] 2.4 第 5 步：checkout 后**重跑** `check-deps.sh`（scripts/ 可能变了）
- [ ] 2.5 第 6 步：版本一致性预检（`VERSION` / `RUNNER_VERSION` / 三个 compose 的 runner tag）
- [ ] 2.6 第 7–8 步：构建平台包 + runner 组件包到临时目录
- [ ] 2.7 第 9 步：三个门禁（identity / runner delivery consistency / 敏感扫描），任一 FAIL 即中止
- [ ] 2.8 第 10 步：离线交付目录；**基线 runner 镜像缺失时按设计 §5.3 给三条路径，不自动联网**（Q5）
- [ ] 2.9 第 11 步：归档到 `archive/<日期>/` + 更新 `latest/`（副本非软链，Q3；历史保留 5 份）
- [ ] 2.10 第 12 步：输出产物清单 + SHA256 + 后续动作
- [ ] 2.11 **单测**：参数解析、分支默认值、缺依赖阻断、门禁失败中止（用 stub 脚本）
- [ ] 2.12 门禁：`.3` 单测 + `bash -n`
- [ ] **实测 T2**：`.3` 端到端出包（用 `--branch dev2`，避免误打发布线）
- [ ] **实测 T3**：默认分支为 `main`；`--branch dev2` 生效且输出标明分支
- [ ] **实测 T4**：有本地改动时不给 `--yes` 会中止

**验收判据**：T2、T3、T4 通过。

## 3. 步骤 3：`cli/install.sh` + `cli/upgrade.sh` 薄封装

**产出**：两个入口脚本，**只做「定位 + exec + 参数透传」，零业务逻辑**（Q4）

- [ ] 3.1 `install.sh`：定位 `../delivery/install/install.sh`，存在性检查后 `exec` 透传 `"$@"`
- [ ] 3.2 `upgrade.sh`：同上，指向 `../delivery/upgrade/upgrade.sh`
- [ ] 3.3 脚本不在仓库态（如被单独拷走）时给可读错误，不静默失败
- [ ] 3.4 **单测**：薄封装不改动 `delivery/` 任何文件（`git diff --quiet delivery/`）
- [ ] 3.5 门禁：`.3` 单测 + `bash -n`
- [ ] **实测 T5**：`.14` 干净 VM，`cli/install.sh` 与 `delivery/install/install.sh` 行为一致
- [ ] **实测 T6**：`.14` 断网 `cli/upgrade.sh` 升级 + **8 项验收全过**
- [ ] **实测 T8**：重复执行 `cli/install.sh` 幂等（不覆盖 `.env`、不重建容器）

**验收判据**：T5、T6、T8 通过；`delivery/` 零改动。

## 4. 步骤 4：`cli/README.md` + 目录收尾

- [ ] 4.1 `README.md` 按设计 §7 六节结构撰写（选哪个脚本 / 前置 / 用法 / 常见失败 / 产物位置）
- [ ] 4.2 「常见失败」从既有 findings 提炼：`.env` 权限、prometheus 目录权限（uid 65534）、
      只读挂载、单飞守卫 400、US-28 锁窗口与 `database is locked` 503
- [ ] 4.3 更新 `docs/doc-map.md`（新增 `cli/` 与设计文档索引）
- [ ] 4.4 更新 `task_plan.md` 第 58 项状态、`pending-tasks` #58
- [ ] 4.5 `progress.md` 记录实测证据（各 T 的 task id / 输出）

**验收判据**：文档索引齐、无失真引用。

## 5. 步骤 5：全量门禁与收尾

- [ ] 5.1 `.3` 后端全量（含新增 `test_cli_toolkit.py`）
- [ ] 5.2 `verify_api_docs` / `verify_release_docs_safe`（`cli/` 引入新文档，检查脱敏）
- [ ] 5.3 `verify_runner_delivery_consistency`（确认 CLI 未影响交付门禁）
- [ ] 5.4 `git diff --check` + 工作树清洁
- [ ] 5.5 分步提交（步骤 1/2/3/4 各一次，便于回滚）

## 6. 回滚

每步一个提交，`git revert <commit>` 即可。`cli/` 是纯新增目录，删除不影响任何既有链路。

## 7. 已知限制（如实记录，不隐藏）

1. **基线 runner 镜像不在仓库**：`package.sh` 无法完全自动化离线交付目录构建，
   缺镜像时给三条路径（设计 §5.3）。这是发布资产的固有属性，不是脚本缺陷。
2. **前端门禁（#54）在 `.3` 仍无法跑**：无 node、拉不到 `node:22-alpine`。
   本项零前端改动，不构成回归风险，但门禁不算完整。
3. **`cli/packages/` 不入库**：产物靠本地留存，跨机器需自行传输（`.3 → .14` 转移即此场景）。
