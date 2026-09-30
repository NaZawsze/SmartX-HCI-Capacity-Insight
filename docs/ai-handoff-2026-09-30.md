# AI 交接文档 · 2026-09-30 收尾交接

> **这份文档回答三个问题**：这一轮做完了什么、没做完什么、下一位接手者第一步该做什么。
> 通用执行纪律见 [ai-handoff-guide.md](ai-handoff-guide.md)（本文只写本轮增量与当前状态，重复处不重复抄）。
> 全部结论都有实测证据，证据位置写在各项后面。

更新时间：2026-09-30
分支：`dev2`（本地领先 origin，**推送需用户明确要求，本轮未推**）
最后提交：`73c7dbe`

---

## 1. 三分钟速览

| 维度 | 状态 |
| --- | --- |
| 平台版本 | v0.5.3 候选（已发布 v0.5.2） |
| runner | 已发布 v0.3.1；仓库开发线 v0.3.2（**用户决定暂不交付**） |
| `.3` 运行实例 | 5/5 容器 Up，health `v0.5.3` / runner `v0.3.2`，数据完好 |
| 本轮主线 | ① 目录层级纠错 + 立 AGENTS 新规 ② US-37 compose 守卫（代码完成，待真机收尾） |
| **唯一未完成的收尾项** | **US-37 的 T4/T5/T6，需在 `.14` 用真实 Docker compose 验证** |
| 后端全量测试 | `.3` 726 tests → 1 failure（**既有环境限制，已对照证明非本次回归**） |

---

## 2. 本轮已完成（可直接接手）

### 2.1 目录层级纠错（用户连续 7 次叫停后定规）

用户最后要求："用用户视角去处理文档和文件以及脚本的存放位置，这个也写进 AGENTS"。

| 改动 | 落点 | 提交 |
| --- | --- | --- |
| `cli/` → `ops/` | 6 文件 `git mv` + 全部引用；`CLI_*` → `OPS_*` | `a457132` |
| 交付手册移出脚本目录 | `ops/DELIVERY-GUIDE.md` → **`docs/delivery-handover-guide.md`** | `a5573fd` |
| 根 README 引用手册 | 根 `README.md` + `README.zh-CN.md`：Repository Layout 补三目录，Documentation 拆两组 | `d050769` |
| **立规** | **AGENTS §11.1「用户视角放置规则」+ §12「交付类改动的验证纪律」** | `9da006d` |

**AGENTS §11.1 核心判据**（下一位必须遵守）：任何新文件/目录先问「**用户从哪一层进来找它？**」。
放置层级必须与「用户第一次看到它的地方」一致。三条硬性要求：入口在最上层（中英双份根 README）/
目录语义单一且用行业惯例命名 / 动手前先勘察既有结构。含 6 条自检清单 + 4 条反面教材。

> **给下一位的提醒**：这一轮 7 次纠错里，我犯的错都是"从我刚建的东西往外看"，
> 而不是"从用户从哪进来往外看"。比如只在 `ops/README.md` 建索引（子目录面向已知位置的人），
> 而根 README 才面向还不知道这东西存在的人。**新增文件前先过 §11.1 自检清单。**

### 2.2 US-37：compose 变体守卫（代码完成）

**问题**（2026-09-30 `.3` 事故，用户发现）：同一 compose project 名下混用不同 compose 变体起服务
→ Docker `config-hash` 判定「配置变了」→ recreate → 旧容器 SIGKILL → `exit 137`、服务中断。
根因**不是**迁移包、**不是** OOM（详见 `docs/upgrade-strategy-issues.md` US-37）。

三层防护已落地：

| 层 | 状态 | 落点 |
| --- | --- | --- |
| 标记（单一事实源） | ✅ | `install.sh` 把 `SMARTX_COMPOSE_FILE_ACTIVE` 写入 `.env`（0600、容器内 `/run/smartx-runtime.env` 可读） |
| 守卫（操作前拦截） | ✅ | `delivery/compose-guard.sh` 自包含；compose 操作前比对，不一致默认 **exit 2** + 三条路径；`--force-compose-switch` 走**完整 down 再 up** |
| 交付态接线 | ✅ | `install/`+`upgrade/` 各一份（`SCRIPT_SOURCES`）；`install.sh` 装进 `PROJECT_DIR`（0755） |
| 诊断文档 | ✅ | `troubleshooting.md` §10、`delivery/README.md` §9.1、`development-verification-process.md` §4.5 |
| **`.14` 真机验证** | ⏳ **未做** | T4/T5/T6，见 §4 |

**实施期修正了设计的一个真缺陷**（值得记住）：
原设计写「`install.sh` 把自己的 `$COMPOSE_FILE` 写进 `.env`」，但这会写出**假标记**——
`install.sh` 遇已有 `.env` 会**直接 `exit 0`**，而事故现场恰是已有 `.env` 的实例，标记永远补不上；
且写入值是硬编码常量。**用猜测源补事实源 = US-26/US-32 同类错误。**
现改为从**容器 compose 标签**（`com.docker.compose.project.config_files`）取地面真相。

### 2.3 修两处「文档写了但跑不通」

- `troubleshooting.md` §1 快速分诊里**本身就是事故诱导源**的那条硬编码命令
  （`docker compose -f docker-compose.offline.yml ps`——照抄最正统文件名就会用错变体）→ 改为先过守卫。
- §10/§9.1 指引客户执行 `.../project/compose-guard.sh`，但守卫原本只从**交付目录** source，
  交付目录会被挪走/删除 → 已让 `install.sh` 装进 `PROJECT_DIR`，并加测试锁住。

---

## 3. 本轮踩的坑与修正（下一位别重犯）

| 坑 | 现象 | 修正 |
| --- | --- | --- |
| **测试靠「PATH 里恰好没有某命令」模拟缺依赖** | 在装了 docker 的标准 Linux（`.3`）上失效，只在 macOS 碰巧通过 | PATH 前放 `exit 127` 的同名桩。修了 2 处（`test_ops_toolkit` 2 例 + 我自己新写的 `test_us37` 1 例） |
| **验证环境搭错** | 只挂 `backend/` 到容器 → 104 个失败（测试按 `ROOT=parents[2]` 找仓库根 `delivery/`、`ops/`） | 挂**整个仓库**到 `/verify`，用同 web-api 镜像起一次性容器（`docker run`，无 compose，不碰在跑实例） |
| **全量测试基线** | `ai-handoff-guide.md` 写的 386 tests 已过时 | 现为 **726 tests**（含本轮新增），基线在 §6 |
| **`cli/` → `ops/` 残留** | 历史文档（`progress.md` 等）保留旧名 | 按 AGENTS §11.1「历史文档不篡改，只在新文档加注记」——**这是正确的，不要去"修"历史记录** |

> `test_v2_upgrade...test_start_can_submit_task_for_runner_and_runner_executes_it`
> 这一个失败是**既有环境限制，非本轮回归**——在动手前的 `9da006d` 上同环境跑同一测试，
> 结果完全相同（`'failed' != 'success'`）。**下一位不要去"修"它。**

---

## 4. ⏳ 未完成（下一位的活，按优先级）

### P0 · US-37 收尾：T4/T5/T6 真机验证（`.14`）

**为什么必须在 `.14`**：T4/T5/T6 需要真实 Docker compose 变更容器。
`.3` 当前跑着真实实例（health 正常），按 `development-verification-process.md` §4.5
与本次事故教训，**不要在 `.3` 上做 compose 实验**。

前置：先 `git archive` 同步本轮代码到 `.14`，并用 `ops/package.sh` 重新打包
（AGENTS §12：动过交付物代码必须重新打包再验证）。

| 用例 | 做什么 | 判据 |
| --- | --- | --- |
| T5 | `install.sh` 装完 | `.env` 含 `SMARTX_COMPOSE_FILE_ACTIVE`，值 = 实际用的 compose |
| **T6** | **故意用错 compose 敲 `up -d`** | **被守卫拒绝（exit 2），容器 ID 与 health 完全不变** |
| T4 | `--force-compose-switch` | 先 down 再 up，无 recreate 冲突，容器干净重建 |

**T6 不可省**——它是本次事故的直接判别用例。

### P1 · `.3` 现场残留标记回填（可选，非阻塞）

`.3` 当前实例的 `.env` 里**还没有** `SMARTX_COMPOSE_FILE_ACTIVE`（守卫是新的，实例是旧的）。
新装/重跑 `install.sh` 会自动回填。存量环境要不要主动回填，由用户决定——
回填是幂等且只增一个变量的低风险操作。

### P2 · runner v0.3.2 交付（用户已决定暂缓）

用户明确"暂时不动"：不推 DockerHub、不打 tag、不出 Release。
**这不是阻塞项，不要主动去做。** 相关未解决项（US-24/26/27/28/32）随下一次发布一起交付。

---

## 5. 下一位接手的第一步（建议顺序）

1. 读 `AGENTS.md`（尤其新增的 §11.1 放置规则、§12 验证纪律）→ `docs/ai-handoff-guide.md` → 本文。
2. 读 `docs/pending-tasks.md`（未完成合并视图）与 `task_plan.md`（当前 Phase）。
3. 若接 US-37 收尾：按 §4 的 P0 在 `.14` 跑 T4/T5/T6，把实测输出写进 `progress.md`，
   再更新 `docs/upgrade-strategy-issues.md` US-37 状态（🟡 → ✅）与 `pending-tasks.md` #59。
4. 遵守提交策略：本地提交，**推送需用户明确要求**。

---

## 6. 验证基线（下一位对不上先看这里）

- **后端全量**（`.3`，本轮实测）：**726 tests → 1 failure（既有）/ 7 skipped**。
  跑法见本轮验证方式或 `development-verification-process.md` §4.1。
- **构建测试**：`backend/build_tests/`（宿主机跑，26 tests OK）。
- **前端**：node 22，tsc + vitest 11 files / 107 tests。
- **compose 守卫单测**：`backend/tests/test_us37_compose_guard.py`（35 例，本地 + `.3` 均 OK）。
- **交付一致性硬门禁**：`scripts/verify_runner_delivery_consistency.py`（发布前必跑）。

> `ai-handoff-guide.md` §4 写的"386 tests 全绿"是 2026-09-27 的旧基线，已过时，以本文为准。

---

## 7. 相关文档索引

| 文档 | 用途 |
| --- | --- |
| [pending-tasks.md](pending-tasks.md) | 未完成工作合并视图（#59 = US-37） |
| [upgrade-strategy-issues.md](upgrade-strategy-issues.md) | US-37 完整根因与取证 |
| [superpowers/specs/2026-09-30-us37-compose-variant-guard-design.md](superpowers/specs/2026-09-30-us37-compose-variant-guard-design.md) | US-37 设计（含实施期修正） |
| [delivery-handover-guide.md](delivery-handover-guide.md) | 交付手册：打包→交客户→客户安装升级 |
| [troubleshooting.md](troubleshooting.md) | §10 = `exit 137` + `OOMKilled=false` 判别（US-37 事故） |
| [development-verification-process.md](development-verification-process.md) | §4.5 = 运行中机器做测试的硬纪律 |
| [../ops/README.md](../ops/README.md) | 三个运维入口脚本用法 |

> 根 `README.md` / `README.zh-CN.md` 面向"还不知道这些工具存在"的人，
> 新增用户可见的东西必须在那两份里能被找到（AGENTS §11.1）。
