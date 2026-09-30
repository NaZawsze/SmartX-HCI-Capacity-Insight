# 实施流水三件套拆分 · 交接执行文档（progress / task_plan / findings）

**状态**：待执行。
**性质**：合并设计与计划的交接文档（理由：纯文档搬运、无代码改动，单文档便于直接交接给外部 AI 执行）。
**执行者前置**：开始前先读根目录 [AGENTS.md](../../../AGENTS.md) §2/§3/§11 与 [docs/doc-map.md](../../doc-map.md) §1，并按 AGENTS §3 在 task_plan.md 建立任务项（Step 0）。

## 1. 背景与目标

根目录三个工作文件是**内部实施流水**（不进交付包、客户看不到），但已严重超载，违反 AGENTS.md 自己的规则「task_plan.md、findings.md、progress.md 只保留当前阶段和稳定结论，不堆叠所有中间日志」：

| 文件 | 大小（2026-09-30 实测） | 结构 |
| --- | --- | --- |
| progress.md | 733 KB | 207 个 `## ` 二级标题，每节 = 一轮带日期的执行记录（2026-05 起逐日追加至今） |
| task_plan.md | 195 KB | 13 个 `## ` 节；体积集中在「专项升级链路历史任务归档（已完成）」「UPG 修复链路摘要（全部完成）」「Phase 与任务设计文档对照」「Phase 49」 |
| findings.md | 101 KB | 61 个 `## ` 节；稳定结论与历史归档混排 |

**目标**：主文件回到「只留当前阶段」，历史流水逐字归档到 `docs/archive/`。**不丢任何内容、不改写任何历史记录。**

既有先例：`docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md` 当年就是从 task_plan/findings 迁出 Phase 32~48 的归档；本次沿用同一模式。

## 2. 目标结构

```text
progress.md                          ← 保留 2026-09-01 起的全部记录 + 顶部「历史归档索引」表
docs/archive/progress-2026-05.md     ← 按月逐字切出（05/06/07/08，按实际最早月份调整）
docs/archive/progress-2026-06.md
docs/archive/progress-2026-07.md
docs/archive/progress-2026-08.md

task_plan.md                         ← 保留：目标/当前环境/当前未提交变更/Phase 与任务设计文档对照/
                                        阶段计划/注意事项/Phase 49 全部现状
docs/archive/task-plan-chain-archive.md ← 逐字迁出 4 个整节：「专项升级链路历史任务归档（已完成）」
                                        「UPG 修复链路摘要（全部完成）」「当前执行项 - UPG-036/037/038/039」
                                        「当前执行项 - UPG-031/fix20」（迁出前逐节确认确实已完成，
                                        以 doc-map §8 与 CHANGELOG 为准；有未完成项则该节不动并报告）

findings.md                          ← 保留全部稳定结论：项目概览/服务与职责/数据路径/网络/UPG-050、
                                        UPG-036/037 等仍被引用的坑点结论
docs/archive/findings-chain-archive.md  ← 逐字迁出「专项升级链路发现归档」及其他标题含「归档/历史」
                                        且内容确已收官的节
```

本任务产生的 `docs/archive/` 与后续可能的 docs/ 分域任务兼容：分域时整目录平移即可。

## 3. 硬性红线（违反任何一条即返工）

1. **逐字搬运**：归档内容与原文 byte 级一致（用脚本按标题切片保证），禁止改写、重排、合并两节、顺手修错别字、改格式。
2. 每个归档文件**顶部加 3 行注记**（归档日期、来源文件、切片范围），注记之后才是原文；原文件被迁走的位置留一行指针（`> 本节已归档至 docs/archive/xxx.md（2026-09-30）`）。
3. **findings.md 的 UPG-050 等稳定结论必须留在主文件**：`scripts/bind-mount-recover.sh` 有 3 处运行时输出指向「findings.md UPG-050」，拆分后该引用必须仍能按「findings.md + UPG-050」找到对应内容。同理检查 task_plan/findings 中被 AGENTS.md、doc-map、其他活文档点名引用的小节（如 task_plan「Phase 与任务设计文档对照」被 doc-map §8 引用，必须留在主文件）。
4. **不改任何 .py/.sh 代码**，不动 .gitignore，不动 AGENTS.md，不改 docs/superpowers/ 既有文件。
5. 根 README **不要**为这些归档文件加入口：它们是内部实施记录，不是用户可发现的功能/手册；索引只维护在 doc-map（否则两处漂移）。
6. 纯本地任务：**不需要** 10.20.11.3、不需要重跑后端门禁、不需要重新打包；`git diff --check` 必须通过。
7. 单次提交完成全部拆分（便于整体回滚）；提交信息建议 `docs: 实施流水三件套拆分归档（progress/task_plan/findings）`。
8. 本任务产出的归档文件从此**只读**——后续不得再改写（历史不篡改原则同样适用于它们）。

## 4. 分步执行

- **Step 0 立项**：task_plan.md 建任务项，关联本文件；确认工作树无他人未提交改动（`git status --short`）。
- **Step 1 切片脚本**：写临时 Python 脚本（放 /tmp，用完删除）：按 `^## ` 标题切片 progress.md，按记录日期分组归月；task_plan/findings 按节名切。切片前先 `grep '^## '` 输出全部标题清单核对。
- **Step 2 一致性校验（搬运前）**：所有切片按原顺序拼接后与原文 `diff` 必须为空，再写归档文件。
- **Step 3 写归档文件 + 改主文件**：按第 2 节目标结构执行；主文件顶部加归档索引表（月/节 → 归档文件）。
- **Step 4 引用完整性检查**：`grep -rn "findings.md\|task_plan.md\|progress.md" --include="*.py" --include="*.sh" backend scripts ops delivery docs/*.md AGENTS.md | grep -v node_modules`，逐条确认所指内容拆分后仍可定位（发现指向已迁走内容的引用 → 该内容留在主文件，而不是改引用）。
- **Step 5 验收（见第 5 节）** 全过 → `git diff --check` → 单提交。
- **Step 6 收尾**：更新 docs/doc-map.md（§1 三件套描述补一句「历史流水已按月/按阶段归档至 docs/archive/」+ 新增归档文件行）；progress.md 末尾追加本轮执行记录（记录拆分本身，含大小对账数字）。

## 5. 验收标准（逐条给出证据）

- [ ] 切片拼接与原文 diff 为空（贴 diff 退出码）。
- [ ] 大小对账：`wc -c` 原三文件大小 ≈ 主文件新大小 + Σ归档文件 − 注记/指针开销（数字写进 progress.md 记录）。
- [ ] 抽查 4 个已知关键记录可找到：「`.3` 服务中断事故（2026-09-30）」「US-37 收录与设计」在 progress 系文件中；UPG-050 定案在 findings.md 主文件；「Phase 与任务设计文档对照」在 task_plan.md 主文件。
- [ ] `bind-mount-recover.sh` 三处「findings.md UPG-050」引用语义不变（人工核对内容仍在）。
- [ ] doc-map.md 已登记全部新归档文件。
- [ ] `git diff --check` 干净、单提交、除预期变更外 `git status` 无其他改动。

## 6. 回滚

单提交，直接 `git revert` 即可；无代码、无远程环境影响。

## 7. 明确不做（防止范围膨胀）

- 不拆 docs/ 下 4 个 v0.5.1/u2 历史升级大文档（另行任务）。
- 不重命名任何文件、不动 docs/superpowers/ 现有 62 个文件。
- 不把归档内容改写成摘要/精简版——要全文。
- **Tier B（task_plan Phase 49 中已完成条目的多行详情迁出）本任务不做**；若执行中认为必要，停下来先问用户，获批后作为独立提交再做。
