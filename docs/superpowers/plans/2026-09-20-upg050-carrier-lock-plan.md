# UPG-050 载体目录物理锁实施计划（task_plan 49-23）

日期：2026-09-20
状态：**待用户批准设计后执行**（批准前不改脚本、不动任何机器）
设计文档：[docs/superpowers/specs/2026-09-20-upg050-carrier-lock-and-prepare-skeleton-design.md](../specs/2026-09-20-upg050-carrier-lock-and-prepare-skeleton-design.md)（第一部分，含脚本接口定稿）
关联：findings.md「UPG-050 定案」、docs/upgrade-issues.md UPG-050（已关闭）、docs/pending-tasks.md #22、docs/troubleshooting.md §2

## 前置条件

- [x] 用户批准设计文档（2026-09-20「开始实施」）。
- [x] .12 基线复查：`bind-mount-recover.sh check` 20/20 挂载 + health ok（2026-09-20 00:15 已确认通过，执行日复查一次）。

## 步骤 1：脚本改造（本地，单提交）

- [x] `scripts/bind-mount-recover.sh` 增加常量 `LOCK_PATHS`（6 路径）与辅助函数 `attr_has_i` / `fs_supports_chattr` / `warn_upg050`（接口按设计文档"脚本接口设计"节）。
- [x] 新增 `lock` 子命令：fs 前置检查 → 逐路径 mkdir 兜底 + `chattr +i`，幂等，逐路径输出，失败 exit 1。
- [x] 新增 `unlock` 子命令：逐路径 `chattr -i`，幂等，失败 exit 1。
- [x] `check` 末尾追加 6 路径锁定状态报告（仅提示，不改变退出码语义）。
- [x] `recover` 改造：入口自动解锁 → 现有全量重建+三轮验证不变 → 通过后自动复锁；验证失败保持解锁并大声提示；复锁失败非零退出。
- [x] `*` 分支用法文案更新为 `{check|recover|lock|unlock}`。
- [x] `bash -n` 语法检查通过。
- [x] 提交 dev2（仅脚本 + 本计划勾选，单提交）。

## 步骤 2：.12 部署与六步验证协议

传输方式：`git archive` 打包本地确切提交内容 → scp → 解压覆盖 `.12:/data/smartx-storage-forecast/project/scripts/`（.12 不是 git 检出，不依赖推送）。

- [ ] ① 基线复查：`check` 20/20 + health ok。
- [ ] ② `lock` 后 `lsattr -d` 逐路径确认 `+i`（含 `smartx-storage-forecast` 父目录与 `project` 子目录）；`app/` 本身与真实数据目录确认**未**带锁。
- [ ] ③ 实弹演练：`rm -rf app/upgrades` 与 `mv app/backups /tmp/` 必须报 `Operation not permitted`；随后 `check` 仍 20/20（挂载无损）。
- [ ] ④ 全量重建：`docker compose stop` + `up -d --force-recreate`（一次性、不带服务参数）成功；`check` 20/20 + health ok——验证 dockerd 可在锁定目录上正常建立挂载。
- [ ] ⑤ 写穿透：容器内写 `/data/upgrades/` 探针文件 → 宿主真实目录 `/data/smartx-storage-forecast/upgrades/` 可见 → 清理探针。
- [ ] ⑥ recover 闭环：锁定状态下真跑一次 `recover`（.12 无业务，30-60 秒中断可接受），确认自动解锁 → 重建 → 验证通过 → 自动复锁全链路；终态 `lsattr` 仍 +i、`check` 全绿。
- [ ] 结论：.12 保持锁定；记录 lsattr 终态与全部命令输出。

## 步骤 3：文档与收尾（单提交）

- [ ] AGENTS.md（本地文件，不入库）第 9 节补锁记录：锁定范围、unlock 口径、recover 自动解锁/复锁行为。
- [ ] docs/troubleshooting.md §2 补锁状态检查（`check` 末尾报告 / `lsattr -d`）与 unlock 操作口径。
- [ ] docs/pending-tasks.md #22、task_plan.md 49-23 状态更新。
- [ ] progress.md 追加全部证据（命令 + 输出摘录）。
- [ ] `git diff --check` + `git status --short --branch` + 提交。

## 步骤 4：.3 与生产机（逐台，单独确认）

- [ ] .3 加锁：仅在用户明确确认后执行 `lock` + lsattr 确认（.3 是主力测试机，需避开升级/打包窗口）。
- [ ] 10.20.0.6（canary/生产等价）：只读边界，未经用户批准具体命令不得执行任何加锁操作。

## 回滚

- 任一步骤失败：`unlock` 全部路径恢复加锁前状态；脚本改动 `git revert`；.12 终态 = 无锁 + 原脚本。
- 验证协议第 ④ 步失败（dockerd 对锁定目录有未预期行为）：unlock → 方案降级为"仅文档规则"，失败证据写 findings.md，任务终止不硬推。
- 实弹演练（第 ③ 步）本身被锁拒绝即预期行为，不构成回滚条件。

## 风险控制

- 恢复脚本与锁的耦合是本方案唯一新风险点：recover 自动解锁/复锁逻辑在第 ⑥ 步真实演练闭环后才允许在 .3 推广。
- 所有远程操作遵守 AGENTS.md 第 5 节；.12 数据操作前已有回归备份 `/root/regression-backup-20260920.tar.gz`（2026-09-20 建档，0600），锁操作不触碰其内容。
