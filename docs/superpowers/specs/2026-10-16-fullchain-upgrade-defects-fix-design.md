# 全链路升级缺陷修复设计（2026-10-15/16 实测 4 个问题）

> 来源：v0.5.4 候选（r37）在 `.12`/`.14` 的**全链路重测**（v0.5.1u2 → v0.5.2 → v0.5.3 → 组件 v0.3.2 → r37，
> web 接口与 CLI 两条路径、每跳验数据完整性）。全部证据见 `progress.md` 2026-10-15 续节与
> `findings.md` 2026-10-15/16 各条。

## 0. 结论摘要（先看这张表）

| # | 问题 | 严重度 | 影响面 | 修复归属 |
| --- | --- | --- | --- | --- |
| 1 | 老布局转型把 `project/.env` 变成**空目录** → 后续升级 `restart` 退出码 14 | 🔴 阻断 | **所有 v0.5.1u2 老布局升 v0.5.4 的现场**（两台机一致复现） | v0.5.4 热修（防御+自愈+预检查）＋ v0.5.5 结构性（转型后校验） |
| 2 | **v0.5.2 平台**上做组件升级 → runner 被 SIGKILL + handoff 死循环 → 后续升级全被拒 | 🔴 阻断/救援死路 | 误按「先组件后平台」的 v0.5.2 现场（README 已警告但无硬拦截） | v0.5.4（`upgrade.sh` 硬拦截 + 组件 manifest 声明最低平台版本） |
| 3 | `runner_protocol` 心跳预检查**时序敏感**（同脚本同时刻两台机结果不同） | 🟠 体验/CI | 平台升级重启 runner 后的窗口期 | v0.5.4（窗口放宽 + 文案带心跳时间） |
| 4 | 平台升级中的 runner **cutover 失败 → 心跳循环静默死亡**（容器 Up、心跳停） | 🟠 现场不可自助定位 | 竞态，偶发 | v0.5.4（runner 恢复心跳 + healthcheck）＋ v0.5.5（区分文案） |

---

## 1. 问题 1：v0.5.2 的 compose 在老布局环境里把**新布局 `.env` 建成空目录**（阻断后续升级）

> **2026-10-16 更正（受控实验）**：原描述「v0.5.1u2→v0.5.3 转型时产生」不够精确。判定实验
> （`.14`，全程无回退/无重跑）证明：**在 v0.5.1u2 → v0.5.2 这一跳就产生**（该跳成功完成，
> 老布局 `.env` 全程完好、新布局路径出现空目录）。精确机制见 §1.2 的「相对 vs 绝对」不一致。
> 实验记录见 `findings.md` 2026-10-16 判定实验节。

### 1.1 现象（实测，两台机一致）

v0.5.1u2（老布局 `/opt/smartx-storage-forecast`）升到 v0.5.3（单根目录 `/data/smartx-storage-forecast/project`）后：

```
$ file /data/smartx-storage-forecast/project/.env
/data/smartx-storage-forecast/project/.env: directory          # 空目录，mode drw-------

$ cd /data/smartx-storage-forecast/project && docker compose -f docker-compose.release.yml config
failed to read /data/smartx-storage-forecast/project/.env: ... is a directory
```

⇒ 下一次平台升级（v0.5.3 → r37）的 `restart` 步骤 `docker compose ... up -d` **退出码 14**，
升级 failed（失败安全生效：自动回滚、数据无损）。容器内 `/run/smartx-runtime.env` 同样是目录
（`docker cp` 也会被它绊倒：`openat run/smartx-runtime.env: is a directory`）。

### 1.2 根因（源码级）

1. **compose 同时声明两条对 `.env` 的依赖**（v0.5.2/v0.5.3/HEAD 一致，`docker-compose.release.yml`）：

   ```yaml
   services:
     web-api:
       command: ["sh", "-c", "chmod 600 /run/smartx-runtime.env && exec uvicorn ..."]
       env_file: [.env]                                                  # 读工程目录的 .env
       volumes:
         - /data/smartx-storage-forecast/project/.env:/run/smartx-runtime.env   # bind 同一文件
   ```

2. **转型动作刻意不复制 `.env`**（`backend/app/upgrade_runner/actions.py::filesystem_prepare`）：

   ```python
   project_skip_names = {".env"} if package_project.is_dir() else APP_RUNTIME_ENTRIES | {".env"}
   _docker_copy_missing(..., mode="project", skip_names=project_skip_names)
   ```

   即新布局的 `project/.env` 必须由 **env 迁移动作**（`env_file_migration` → `_write_env_file`）创建。

3. **Docker 的固有行为**：`docker compose up -d` 遇到 **bind 源不存在**时，会**自动把宿主路径建成空目录**。
   转型过程中若出现「compose 已 `up -d` 而 `project/.env` 尚未被 env 迁移写成文件」的窗口，
   Docker 就把 `project/.env` 建成空目录；容器里的 `chmod 600 /run/smartx-runtime.env` 又把这个
   **目录**的权限改成 `drw-------`——与实测的宿主/容器两侧形态完全吻合。

4. 一旦成为目录：`_write_env_file` 的 `path.write_text()` 会抛 `IsADirectoryError`（env 迁移无法自愈），
   而 `docker compose` 读 `env_file` 直接失败 ⇒ **此后该环境的任何 compose 操作都不可用**。

### 1.2.1 潜伏期：**产生**在 v0.5.2 跳，**发作**在布局转型之后

实验 + 全链实测合起来给出完整时间线：

| 时点 | 现象 | 说明 |
| --- | --- | --- |
| 老布局跑 v0.5.2 的 `up -d` | 新布局路径 `.env` 被 Docker 建为**空目录** | 此时**无任何症状**（老布局 `.env` 仍是文件，compose 用的是工程目录里那份） |
| v0.5.2 → v0.5.3 升级 | **仍能成功**（实测两台机 web 路径均通过） | 该跳的 compose 操作仍以老工程目录为 cwd，读的是 `/opt/.../.env`（文件） |
| v0.5.3 转型完成 | 平台记录的工程目录切到 `/data/smartx-storage-forecast/project` | 从此刻起 compose 的 cwd = 被污染目录 |
| **v0.5.3 → v0.5.4（r37）** | `restart` 步骤 `docker compose up -d` **退出码 14**、升级失败回滚 | `failed to read …/.env: is a directory` —— **这就是「发作」点** |

⇒ 现场观感是「升级到某一版之后突然再也升不动」，而不是「升级当下就报错」——**潜伏期**让问题更难定位。
修复必须同时覆盖「不再产生」（A0 改 compose）与「发作时能自愈/说清楚」（A/B/C）。

### 1.3 修复方案（分四层，前两层可进 v0.5.4）

**A0. 首选：修 compose 的路径不一致（治本）** — `docker-compose*.yml` 里两处 `.env` 引用
**一处相对一处绝对**（`env_file: [.env]` vs `- /data/smartx-storage-forecast/project/.env:/run/smartx-runtime.env`）。
把 bind 源改成**相对路径**（`- ./.env:/run/smartx-runtime.env`，与 `env_file` 同源），或直接去掉该 bind
（应用 env 已由 `env_file` 注入；若 `/run/smartx-runtime.env` 确被 runner 沙箱使用，则改为相对挂载）。
这样「bind 源 = compose 读的那份 env」，不会再出现「A 处读到文件、B 处建出目录」的分叉。

**A. 迁移动作自愈（最小、最关键）** — `backend/app/upgrade_runner/actions.py::_write_env_file`：

```python
def _write_env_file(path: Path, text: str) -> None:
    if path.is_dir() and not path.is_symlink():      # ← 新增：Docker bind 自动建出的空目录
        shutil.rmtree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
```

**B. compose 前置守卫（覆盖已被污染的环境）** — 在任何 `docker compose up -d` 之前（runner 的
`compose.apply`/`restart` 动作、`install.sh`/`upgrade.sh`）加一步 `ensure_env_file()`：

```python
env_path = project_dir / ".env"
if env_path.is_dir() and not env_path.is_symlink():
    # 从「运行中实例的 env」重建（保留密钥/Tower 凭据配对），或从升级前备份恢复；
    # 两者都拿不到则**明确失败**，绝不带病继续。
```

**C. 升级预检查新增一项** — `backend/app/v2/upgrade/service/precheck.py`：新增
`env_file: project/.env 必须是常规文件（当前为目录 ⇒ 环境已被历史转型污染）`。这样现场得到的是
**可执行的失败原因**，而不是「restart 退出码 14」。

**D. 结构性（v0.5.5）**：`filesystem_prepare` 在转型末尾**断言** `project/.env` 为常规文件
（缺失则立即失败，让转型原子化），并调整计划顺序保证 env 迁移**先于**首次 `up -d`；
`env_file_migration` 的 `target` 与 compose 的 bind 源用**同一个来源**计算（杜绝再次分叉）。

### 1.4 验证（修复后必须重跑）

- **判定实验复用**：`.14` 跑 `/data/env_verdict.sh`（全清 → 装 v0.5.1u2 → 逐跳升级，每步记录 `.env` 类型）
  ⇒ 修复后要求 **step2 起新布局 `.env` 始终为 file**、`docker compose config` 始终通过。
- **反向用例**：人为把 `project/.env` 建成目录 ⇒ 预检查精确报错、`ensure_env_file` 能自愈。

- 单测：`_write_env_file` 对「目标是目录」的自愈；`ensure_env_file` 的三条分支（文件/目录可恢复/目录不可恢复）。
- 真机（`.14`）：全链重跑 v0.5.1u2 → v0.5.3 → 组件 → r37，**每跳后断言 `project/.env` 是常规文件**
  + `docker compose config` 通过 + 数据指纹一致。**新增验收格**：「转型后 `.env` 类型校验」。
- 反向用例：人为把 `project/.env` 建成目录，验证预检查给出精确文案、`ensure_env_file` 能自愈。

---

> **实施状态（2026-10-17）**：A（`upgrade.sh` 硬拦截）与 **B（组件包 `minimum_platform_version` + 预检查 `component_platform`）** 均已实施；C 为文档指引。
> 旧平台（≤ v0.5.2）在 Web 界面仍无法拦截——旧镜像不含该检查，只能靠交付 README 约束。

## 2. 问题 2：v0.5.2 平台上做组件升级会把自己卡死

### 2.1 现象（实测 `.14`）

hop2（v0.5.2→v0.5.3）预检查失败后，流程继续执行了组件跳 ⇒ 在 **v0.5.2 平台**上做 runner 自换：

- runner 容器 **`Exited (137)`**（SIGKILL），无接替者；`health.runner_version` = 「未检测到 runner」；
- `docker start` 拉起后 runner 陷入 **handoff 循环**（日志反复
  `schedule-runner-target-runtime-handoff … 本进程立即停止且不写状态`，并不断创建
  `smartx-runner-cutover-*` 容器）；
- `upgrade_runner_state.heartbeat_at` 停在旧时刻（实测滞后 18 分钟）⇒ 平台升级预检查持续报
  `runner_protocol: 未检测到 upgrade-runner 心跳` ⇒ **后续所有平台升级被拒**（救援死路）。

### 2.2 根因

- 「新旧 runner 同属当前 compose project 时跳过停止旧 runner」这条守卫是 **runner v0.3.2 自己的
  bootstrap 逻辑**（日志可见），**v0.5.2 的 web-api 没有同 project 守卫**（US-26/#82 那批工作之前），
  它编译出的旧式 runner 引导计划会无条件停掉旧 runner ⇒ 新 runner 起不来时现场即失去执行器。
- 交付 README §4.3 已明确写「v0.5.2 不能先做组件升级」，但**只有文档警告，没有硬拦截**。

### 2.3 修复方案

**A. CLI 硬拦截（v0.5.4，最有效）** — `delivery/upgrade/upgrade.sh`：

```sh
# 组件升级前
platform_version=$(curl -s $BASE/api/system/health | ... )
case "$platform_version" in
  v0.5.0|v0.5.1|v0.5.1u1|v0.5.1u2|v0.5.2)
    echo "[XX] 当前平台 $platform_version 不支持先做组件升级（会停掉 runner）。"
    echo "     请先用平台升级包升到 v0.5.3 及以上，再做组件升级（US-40 顺序）。"
    exit 1 ;;
esac
```

**B. 组件包声明最低平台版本（v0.5.4 起，面向未来）** — 组件 manifest 增
`minimum_platform_version: v0.5.3`（`scripts/build_runner_component_package.py`），
平台侧组件预检查读取并拒绝（`upgrade/service/precheck.py`）。注意：**v0.5.2 的旧平台不会读这个字段**，
所以这一条只能保护 v0.5.4+ 的平台，A 才是对老现场的兜底。

**C. 现场救援路径（v0.5.4）** — 文档 + CLI 提示：在「runner 已死/心跳停」的环境里，
先用**新版交付包**的组件升级流程重建 runner（v0.5.4 的 runner bootstrap 有同 project 守卫），
再执行平台升级；README 补「已踩坑如何恢复」小节。

### 2.4 验证

- 真机（`.14`）：v0.5.2 平台 + 组件升级 ⇒ **被 `upgrade.sh` 拒绝**且提示正确（不再是「SIGKILL 后卡死」）。
- 单测：`upgrade.sh` 的版本判定分支（shellcheck + 桩测）；组件预检查对 `minimum_platform_version` 的拒绝。

---

## 3. 问题 3：`runner_protocol` 心跳预检查时序敏感

### 3.1 现象

同一 harness、同一时刻：`.12` 的 v0.5.2→v0.5.3 预检查**通过**并全链成功；`.14` 同一跳
**连续两次失败**（间隔 90s），失败项恒为「未检测到 upgrade-runner 心跳」。

### 3.2 根因

- 判定实现在 `backend/app/v2/upgrade/service/runner_presence.py`，窗口常量
  `RUNNER_HEARTBEAT_STALE_SECONDS = 30`（`constants.py`）。
- 平台升级会**重启 runner**；重启后 runner 需要重新进入轮询周期才开始刷新实例心跳
  （实例心跳只在 `run_pending_once` 开头刷新），这段窗口内两条通道都可能不新鲜 ⇒ 判定为「不在场」。
- 判定本身没错（`.14` 那次心跳真的滞后 18 分钟，见问题 4），但**窗口偏紧 + 文案不带证据**，
  导致「瞬时窗口」与「真死」在现场看来一模一样。

### 3.3 修复方案

- **窗口放宽/可配**：`RUNNER_HEARTBEAT_STALE_SECONDS` 提到 90s（或按「上一次心跳时间 + 期望
  轮询间隔×3」动态判定），并支持 env 覆盖（现场排障用）。
- **文案带证据**：失败详情追加「最后心跳时间 / 判定窗口 / runner 容器状态」，例如
  `未检测到 upgrade-runner 心跳（最后心跳 2026-10-16T01:42:30Z，已 18m12s；窗口 90s；容器 smartx-…-upgrade-runner-1 Up）`。
- **可区分「handoff 进行中」**：检测到 cutover/handoff 痕迹时给出专门提示，而不是与「runner 不在」同文案。
- **自动化侧**：验收脚本预检查失败后重试窗口 ≥ 3 分钟（本次实测 90s 不够）。

### 3.4 验证

- 单测：给定「心跳时间戳 + now」的多种组合，断言判定与文案（含最后心跳时间）。
- 真机：连续 5 轮「平台升级 → 立即预检查」应全部通过（或给出带时间的明确原因）。

---

## 4. 问题 4：cutover 失败后 runner 心跳循环静默死亡

### 4.1 现象（实测 `.14`）

hop1（v0.5.1u2→v0.5.2）后 runner 容器仍 `Up`，但 `upgrade_runner_state.heartbeat_at` **停在 01:42:30
不再更新**（检查时滞后 18 分钟）；runner 日志尾部：

```
Error response from daemon: No such container: smartx-runner-cutover-upgrade-9cc67e9ae94b4ab2
```

### 4.2 根因

runner 的 cutover/handoff 流程失败后**没有回退到「继续心跳」**（主循环停在交接点），
进程还在但不再刷新心跳。平台侧唯一症状是 `runner_protocol` 预检查失败 —— 与「runner 完全不存在」
同一文案，现场无法自助区分。

### 4.3 修复方案

- **runner 侧（v0.5.4，注意 AGENTS §6：改 runner 必须同步 bump `RUNNER_VERSION`）**：
  cutover 失败路径必须回退为「保持当前 runner 继续运行并继续心跳」，并把失败原因写入状态文件/日志。
- **容器 healthcheck（v0.5.4）**：给 upgrade-runner 容器加 `healthcheck`（检查心跳新鲜度/状态文件），
  让 `docker ps` 直接显示 `unhealthy`，而不是靠人去读 DB。
- **平台文案（v0.5.4）**：见问题 3 的「文案带证据」，把「容器在但心跳陈旧」单列一类。

### 4.4 验证

- runner 单测：模拟 cutover 失败（目标容器缺失）⇒ 断言「心跳继续刷新」+ 失败原因落盘。
- 真机：人为制造 cutover 失败（删除 cutover 容器名）⇒ 容器显示 unhealthy 且平台提示带最后心跳时间。

---

## 5. 交付与发布影响

- **v0.5.4 候选（r37）是否重打？** 问题 1 的 A/B/C 与问题 2 的 A、问题 3 的文案属于**小改动、风险低**，
  建议**并入 v0.5.4 并重打候选包（r38）**，同时按 1.4/2.4 重跑 `.12`/`.14` 验证；
  问题 4 涉及 runner 代码（需 bump `RUNNER_VERSION` 到 v0.3.3 + 组件包重出 + DockerHub tag），
  若时间不允许可放 v0.5.5。
- **v0.5.5（结构性）**：问题 1 的 D（转型后断言 + 顺序/来源归一）、问题 4 的容器 healthcheck 深化。
- **文档**：README 增「已踩坑如何恢复」（runner 死、`.env` 被污染两种）；`docs/upgrade-chain.md` 补
  「v0.5.2 源端禁止组件升级」的硬约束说明与 `upgrade.sh` 拦截行为。

## 6. 验收清单（修复后必须逐条回填证据）

| 项 | 判据 |
| --- | --- |
| 1-A/B | 人为把 `project/.env` 建成目录 ⇒ 预检查精确报错；`ensure_env_file` 能从运行实例 env 自愈；升级可继续 |
| 1-D | 全链（v0.5.1u2→…→r3x）每跳后 `project/.env` 均为常规文件、`docker compose config` 通过 |
| 2-A | v0.5.2 平台 + 组件升级 ⇒ `upgrade.sh` 拒绝且提示正确 |
| 2-B | 组件 manifest 含 `minimum_platform_version`；v0.5.4+ 平台对不满足者拒绝 |
| 3 | 连续 5 轮「平台升级→立即预检查」全通过；失败文案含最后心跳时间 |
| 4 | cutover 失败后 runner 继续心跳；容器 healthcheck 显示 unhealthy |
| 数据 | 每跳数据指纹一致（沿用本次 harness：`/data/chain_test.py`） |
