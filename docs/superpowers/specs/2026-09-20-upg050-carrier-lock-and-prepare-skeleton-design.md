# UPG-050 挂载点载体加锁方案 + runner prepare 骨架目录问题记录

日期：2026-09-20
状态：设计完成，**待用户确认后实施**（实施前未对任何机器做加锁操作）
关联：findings.md「UPG-050 定案」（2026-09-19）、docs/upgrade-issues.md UPG-050（已关闭）、docs/pending-tasks.md #20、task_plan 49-23

---

## 第一部分：UPG-050 加锁（有实施方案，待批准）

### 1. 遇到的问题

**根因回顾（2026-09-19 定案）**：容器创建时 dockerd 会穿过 `/data`（app bind）自动补建嵌套挂载点目录，宿主机侧为 `/data/smartx-storage-forecast/app/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}`（及 `app/smartx-storage-forecast/project`）。这些目录被容器内真实 bind 遮蔽、永远为空、与真实数据目录同名——**挂载附着在它们的 inode 上**。宿主机对它们执行 `rm`（挂载失去附着点消失）或 `mv`（挂载随目录被搬移）即拆掉全机所有容器的对应挂载，且 `docker inspect` 仍显示挂载配置（不可信），表现为"静默衰减"。历次事故均为清理操作自伤——其中实际肇事的是一次 AI 会话的磁盘清理，当时"这些目录是承重结构"这一知识尚不存在。

**现有防线及其边界**：

| 防线 | 状态 | 性质 |
| --- | --- | --- |
| 规则红线（AGENTS.md 第 9 节、troubleshooting.md §2） | 已落地 | **软约束**：依赖 AI/运维读了并遵守 |
| 检测（health `checks.directories`，升级健康门禁拦截） | 已落地 | 事后秒级报警，不静默 |
| 恢复（`scripts/bind-mount-recover.sh recover`，一键全量重建） | 已落地 | 数据零丢失，双机演练通过 |
| 代码防线（runner `APP_RUNTIME_ENTRIES` 跳过清单；空间清理只删真实目录内容） | 已核实 | 产品流程永不触发 |

**剩余风险**：正常流程（升级、清理、采集、备份）已证明永不触发；唯一剩余触发途径是"宿主机上有人/AI 对这组目录执行 rm/mv"。软约束防不住"没读到规矩的正常操作"——本次事故正是这种类型。产品代码改造（改挂载拓扑使载体目录消失）被评估为 disproportionate：要动 SQLite 路径、迁移、升级最敏感一圈代码，为一个已四道防线封死的问题不成比例，**不做**。

### 2. 解决方案：chattr +i 物理锁

**目标**：把剩余触发途径从"软约束依赖自觉"变为"物理上删不掉"——rm/mv 当场报 `Operation not permitted`，与操作者是否读过文档无关。

**锁定范围（6 个宿主机路径）**：

```text
/data/smartx-storage-forecast/app/upgrades
/data/smartx-storage-forecast/app/backups
/data/smartx-storage-forecast/app/exports
/data/smartx-storage-forecast/app/compose-runtime
/data/smartx-storage-forecast/app/smartx-storage-forecast            （父，防整体 mv 搬移）
/data/smartx-storage-forecast/app/smartx-storage-forecast/project    （web-api/runner 的 project 挂载附着点）
```

**刻意不锁的范围（重要）**：

- `app/` 本身**不锁**：SQLite WAL 模式需要在 `app/` 内创建 `smartx.db-wal`/`smartx.db-shm`，+i 会阻断文件创建，直接弄挂数据库。
- 真实数据目录（`/data/smartx-storage-forecast/{upgrades,backups,exports,compose-runtime,app,prometheus}`）**全部不锁**：它们是运行数据本体，平台日常写入（升级任务目录、备份、报表）必须畅通。载体目录被容器内挂载遮蔽、无任何合法写入方，锁它不影响任何数据路径。

**锁的语义**（ext4/xfs 原生支持）：目录不可删除、不可改名/搬移、其内不可创建新条目。六个路径全部已存在，合法流程不需要在它们内部创建任何东西。

**兼容性论证（已核实，读码 + 历史实证）**：

1. `filesystem_prepare` 的 mkdir 循环（`upgrade_runner/actions.py:1000-1010`）全部为 `mkdir(parents=True, exist_ok=True)`，目标是容器内挂载路径——挂载健康时写入穿透到真实目录，不触碰宿主机侧载体 inode；目录已存在时 `exist_ok=True` 为无操作。锁不挡升级。
2. dockerd 容器创建：在已存在的载体目录上建立挂载，不修改目录内容；容器销毁：umount 不 rmdir（两机多轮 recreate 后载体目录仍在——实证）。锁不挡重建。
3. 容器内全部业务写路径经挂载穿透到真实目录（容器看到的 `/data/upgrades` 就是真实 upgrades），锁定载体对容器内进程完全不可见。

#### 脚本接口设计（定稿，实施按此执行）

**锁定路径常量**（与上文 6 路径一致，脚本内数组）：

```bash
APP_ROOT="/data/smartx-storage-forecast/app"
LOCK_PATHS=(
  "$APP_ROOT/upgrades"
  "$APP_ROOT/backups"
  "$APP_ROOT/exports"
  "$APP_ROOT/compose-runtime"
  "$APP_ROOT/smartx-storage-forecast"
  "$APP_ROOT/smartx-storage-forecast/project"
)
```

**辅助函数**：

- `attr_has_i <path>`：`lsattr -d "$path"` 输出第一段属性串含 `i` 即视为已锁；`lsattr` 报错（路径消失等）视为未锁并向调用方上抛错误。
- `fs_supports_chattr`：`stat -f -c %T "$APP_ROOT"` 结果必须为 ext4/xfs 族；其他文件系统（不支持 chattr +i 语义）报错退出，提示该机不加锁并记录。
- `warn_upg050`：现有 `*` 分支的两行 UPG-050 警示提升为公共函数，`lock`/`unlock`/`check`/`recover` 入口统一输出，保证任何调用者都能看到"载体目录是承重结构"。

**子命令语义**：

| 子命令 | 行为 | 退出码 |
| --- | --- | --- |
| `lock` | 前置 `fs_supports_chattr`；逐路径：缺失则 `mkdir -p` 兜底（正常流程目录必已存在）→ `chattr +i`；已锁跳过（幂等）；逐路径输出 `[locked]`/`[already]` | 任一路径失败 → 1 |
| `unlock` | 逐路径 `chattr -i`；未锁跳过（幂等）；逐路径输出 `[unlocked]`/`[not-locked]` | 任一路径失败 → 1 |
| `check` | 现有挂载+健康体检**不变**；末尾追加 6 路径锁定状态报告（仅提示，不改变退出码语义） | 现有语义 |
| `recover` | 改造：入口检测 6 路径带锁 → 自动 `unlock` → 现有全量重建+三轮验证逻辑不变 → 验证通过后自动 `lock` 复锁；**验证失败保持解锁状态并大声提示**（带锁掩盖失败比无锁更危险，宁可留下解锁现场） | 现有语义 |

**实现约束**：

- 保持 POSIX-bash 现状（`#!/usr/bin/env bash` + `set -u`），不引入新依赖；`chattr`/`lsattr` 来自 e2fsprogs，两台测试机均已具备（验证协议第 0 步复核）。
- `recover` 的自动复锁失败时必须以非零退出并逐路径报错，不得静默留下半锁状态。
- 不改动 `SERVICE_MOUNTS` 观测点清单与 `container_of`/`mount_present` 现有逻辑。

**验证协议（在 .12 演练机执行，约 15 分钟）**：

1. 基线：`check` 20/20 挂载 + health ok（2026-09-20 00:15 已确认通过）；
2. `lock` 后 `lsattr` 逐路径确认 +i；
3. 实弹演练：`rm -rf app/upgrades` 必须报错、`mv app/backups /tmp/…` 必须报错，随后 `check` 仍 20/20（挂载无损）；
4. 全量重建：`docker compose stop` + `up -d --force-recreate`（一次性，不带服务参数）成功，`check` 20/20 + health ok——验证 dockerd 可在锁定目录上正常建立挂载；
5. 写穿透：容器内写 `/data/upgrades/…` 测试文件确认落在真实目录且可清理；
6. 结论为保持锁定；回滚方式 = `unlock` 子命令（或 `chattr -i`），零残留。

**风险与对策**：

| 风险 | 对策 |
| --- | --- |
| dockerd 对锁定目录有未预期行为（唯一实证未知项） | 验证步骤 4 实测；失败即 unlock 回滚，方案降级为"仅文档规则"并记录 |
| 合法运维（重装/迁移/清理）忘了解锁 | recover 自动解锁复锁；手册写明 unlock 口径；被锁目录报错信息本身即提醒 |
| 文件系统不支持 chattr | 验证步骤 0 检查 `stat -f -c %T`（ext4/xfs 均支持）；不支持则该机不加锁、记录原因 |
| 锁给人"绝对安全"错觉，放松对 `app/`、数据库的纪律 | 文档明确锁的边界：防误删载体目录，不防删库（删库靠备份与权限纪律） |

**实施范围**：.12 验证通过后保持锁定；.3 与生产机（10.20.0.6）**逐台待用户确认**，不默认跟锁。

### 3. 验收标准

- [ ] .12：`check` 20/20 绿；实弹 rm/mv 被拒且挂载无损；全量重建成功后仍 20/20；写穿透正常；锁定状态保持。
- [ ] `recover` 在锁定状态下完整可用（自动解锁→重建→复锁）。
- [ ] AGENTS.md 第 9 节、troubleshooting.md §2 补锁记录与 unlock 口径；progress.md 留档全部证据。

---

## 第二部分：runner prepare 骨架目录问题（仅记录，不实施）

### 1. 遇到的问题

UPG-050 排查期间发现：升级执行期 runner 的 `filesystem_prepare` mkdir 循环会在 `app/` 下生成**空骨架目录**（畸变路径、无数据复制、不阻塞升级，findings.md 619）。

**影响评估**：纯宿主机侧目录噪音。挂载健康时 mkdir 经真实挂载穿透到真实目录，无宿主机可见副作用；只有在挂载已衰减（UPG-050 场景）时才会在 app/ 下留下可见空目录。它不损坏数据、不阻塞升级，但历史上加重了"app/ 下这些目录看起来像垃圾"的误判诱因——与本次事故的成因环境有牵连。

### 2. 解决方案（用户决策：2026-09-20，仅记录，不排期修复）

- **决策**：仅记录。已登记 `docs/pending-tasks.md` #20（提交 a70d6d9），不安排修复、不纳入下次打包。
- **理由**：危害仅为衰减场景下的视觉噪音；修复需动 runner 代码并重打包，会使已通过全部门禁的交付包 e940e07c 作废重打，不成比例。
- **若未来主动治理的方向**：`filesystem_prepare` mkdir 目标过滤与挂载点同源（载体）候选，仅允许经真实挂载路径建目录；随下一次大版本打包顺带实施，单独回归。
- **运营侧缓解（已覆盖）**：载体目录锁（第一部分）落地后，即使衰减发生，app/ 下的畸变生成物也会大幅减少（衰减本身更难发生）。

---

## 执行边界

本文档批准前：不改脚本、不动任何机器。批准后按第一部分验证协议执行，单任务单提交，progress.md 记录全部证据。
