# US-37 设计：compose 变体多事实源的根治（标记 + 守卫 + 工具隔离）

- 日期：2026-09-30
- 关联：`docs/upgrade-strategy-issues.md` US-37；`docs/pending-tasks.md`
- 事故记录：`progress.md` 2026-09-30 `.3` 服务中断事故
- 状态：设计定稿，待实施

## 1. 要解决的问题

`.3` 上 web-api 被 SIGKILL（`exit 137`、`OOMKilled=false`），服务中断。根因不是 OOM、不是迁移包，
而是**同一个 compose project 名下混用不同 compose 文件起服务**，Docker 判定「配置变了」→ recreate。

### 1.1 结构性根因

仓库有 **4 个 compose 变体**，共享同一个 project 名 `smartx-hci-capacity-insight`：

| 文件 | 用途 | web-api 定义方式 |
| --- | --- | --- |
| `docker-compose.yml` | 开发/源码目录 | `build: {context: ., dockerfile: backend/Dockerfile}` |
| `docker-compose.offline.yml` | 离线交付 | `image:` + `pull_policy: never` + 注入 `SMARTX_COMPOSE_FILE` + 多一个 `project:...:ro` 挂载 |
| `docker-compose.release.yml` | 交付包内 | 又一版 |
| `docker-compose.upgrade.yml` | 升级运行时 | 又一版 |

实测三个服务在 `docker-compose.yml` 与 `docker-compose.offline.yml` 里的定义**全部不同**，
所以 `com.docker.compose.config-hash` 必然不同。

**而系统没有任何地方记录「这个实例是用哪个 compose 起的」**（实测确认）：

- `.env.example` 无 compose 文件字段；
- `install.sh` 硬编码 `COMPOSE_FILE="docker-compose.offline.yml"`（第 41 行），
  却把**两个 compose 都装进** `$PROJECT_DIR`（第 322 行的循环）；
- `upgrade.sh` 完全不碰 compose；
- `.env` 与 `project/` 里**没有任何标记**。

**结果**：现场同时存在两份可用的 compose，任何人（包括自动化脚本）都可能用错那一份，
而系统既不会拦、也提供不了任何提示。这与 US-26（compose tag 多事实源）同源：
**同一实体有两个可写的真相来源，且没有单一事实源仲裁。**

### 1.2 为什么不能只靠"注意"解决

事故的直接触发是开发者在运行中的机器上跑测试。但**下一���可能是**：
客户运维照着文档敲 `docker compose -f docker-compose.yml up -d`（主 compose 名字最"正统"），
就会把用 offline compose 装好的实例 recreate 掉——**这是文档可读性诱导的误操作，不是蠢人犯错**。

因此需要**产品层的防护**，而不是纪律要求。

## 2. 方案：三层防护

### 2.1 第一层：留下单一事实源（标记）

**安装时把「用了哪个 compose」写进 `.env`**，作为此后所有操作的权威来源。

- 变量名：`SMARTX_COMPOSE_FILE_ACTIVE`（用 `_ACTIVE` 后缀强调"这是当前生效的那份"，
  与 offline compose 往容器注入的 `SMARTX_COMPOSE_FILE` 区分开，避免混淆）。
- 值：相对文件名，如 `docker-compose.offline.yml`。
- 写入时机：`install.sh` 启动服务**之前**，与 `.env` 一起落盘。
- 权限：`.env` 已是 0600，该变量随之受保护。

**为什么放 `.env` 而不是别的文件**：
- `.env` 已经是所有环境口径的既有落点（含 `SMARTX_DB_PATH` 等），不新增概念；
- `.env` 既作为 `env_file:` 注入容器、又被挂载到 `/run/smartx-runtime.env`
  （实测确认），**诊断时无需登录宿主即可读到**；
- 升级/备份流程已把 `.env` 当成成对资产处理（AGENTS §9「Tower 凭据加密所需的配套 .env 必须与数据库成对迁移」）。

#### 2.1.1 实施期修正：标记必须取自地面真相，不能取自「脚本认为的 compose」

设计初稿写的是「`install.sh` 把自己用的 `$COMPOSE_FILE` 写进 `.env`」。实施前核对发现**这条会写出假标记**：

1. `install.sh` 的幂等检查在第 231-236 行：`.env` 存在且未加 `--force-env` 时**直接 `exit 0`**。
   而事故现场的 `.3` 恰恰是**已有 `.env`** 的实例——标记永远补不上，
   守卫对最需要保护的旧环境反而一直走 T1 放行分支。
2. 即使把写入挪到退出之前，写入值也是**脚本的硬编码常量** `docker-compose.offline.yml`（第 41 行），
   而现场实际可能用的是别的变体。**写死的值不是观测值**——这正是 US-26/US-32
   「多事实源」同类错误的翻版：用另一个猜测源去补事实源。

**修正为：从运行中容器的 compose 标签取地面真相。**

Docker 会把实际使用的 compose 文件绝对路径写在容器标签里（实测 `.3` 返回
`/data/smartx-storage-forecast/project/docker-compose.yml`）：

~~~text
com.docker.compose.project.config_files   ← 实际用的 compose 文件（绝对路径）
com.docker.compose.project.working_dir
~~~

标记回填规则（`compose_guard_resolve`）：

| 情况 | 标记取值 | 理由 |
| --- | --- | --- |
| `.env` 已有标记 | 保持不变 | 已是既定事实源 |
| 无标记 + **有运行中容器** | 容器 `config_files` 标签的 basename | **地面真相**，非猜测 |
| 无标记 + 无容器 | `$COMPOSE_FILE`（本次要用的） | 无在跑服务，不存在 recreate 风险，且即将用它启动 |

本项目已有读 compose 标签的先例（`backend/app/upgrade_runner/actions.py:1694`、
`backend/app/upgrade/service/verification.py:86`），不引入新机制。

**这一条比原设计更强**：它让守卫对**事故现场那种「标记缺失但服务在跑」的历史环境**
也能立刻生效，而不是等客户重装。

### 2.2 第二层：操作前守卫（拦住误操作）

**部署位置（关键约束，实测确认）**：`scripts/build_offline_delivery.py` 的 `SCRIPT_SOURCES`
只复制**单个 .sh 文件**（`install/install.sh` 与 `upgrade/upgrade.sh`），交付目录**没有 `lib/`**。
因此守卫**不能作为外部库依赖**——否则交付物不自包含、或必须改 `SCRIPT_SOURCES` 的结构约定。

**采用形态：自包含的独立脚本 `compose-guard.sh`，随两个交付脚本一起进交付目录。**

```
offline-delivery/
├── install/
│   ├── install.sh
│   ├── compose-guard.sh        # 新增
│   ├── images/
│   └── project/
└── upgrade/
    ├── upgrade.sh
    ├── compose-guard.sh        # 新增（同一份）
    └── packages/
```

`SCRIPT_SOURCES` 增加一条 `"install/compose-guard.sh"` 与 `"upgrade/compose-guard.sh"`，
两份内容相同（各放一份，避免 `install/` 与 `upgrade/` 之间的相对路径耦合）。

守卫提供 `compose_guard_check <compose文件> <project名>`，在任何
`docker compose up/down/restart` **之前**调用：

1. 读 `.env` 的 `SMARTX_COMPOSE_FILE_ACTIVE`；
2. 与传入的 compose 文件名比对；
3. 不一致则**拒绝执行**，并明确输出：
   - 当前实例实际用的是哪个（`SMARTX_COMPOSE_FILE_ACTIVE` 的值）；
   - 你要用的是哪个；
   - 后果（会触发 recreate 并 SIGKILL 旧容器，`exit 137`）；
   - 三条可选路径（改用正确的 compose / 确实要换 compose 则显式加 `--force-compose-switch` 并说明后果 /
     先 `docker compose -p <project> down` 完整停机后再换）。

**为什么默认拒绝而不是警告**：误操作的代价是**服务中断**（本次就是），
而正确操作的成本只是改一个参数。默认拒绝是把"代价高、收益低"的一侧关掉。

**`--force-compose-switch` 的语义**：不是"跳过检查"，而是
"我确认要换 compose 变体，请**先完整 down 再 up**"——
它会先执行 `docker compose -p <project> down --remove-orphans`（用**旧** compose，即 active 那份），
再 `up` 新变体。这样**不会有 recreate 冲突**，也不会误杀。
这比"硬 replace"安全得多。

### 2.3 第三层：工具链隔离（开发/测试侧）

事故的直接成因是我在**运行中的机器**上用另一份 compose 操作同一 project。工具层要挡这个：

- `ops/package.sh` **本身不调用 compose**（实测确认，只做构建），所以它无此风险——**保持现状，不要加多余逻辑**。
- ~~新增 `ops/lib/test-env.sh` 提供 `test_project_name`~~ —— **用户否决**（2026-09-30）：
  这类薄封装脚本约束不了真正危险的场景（人在错误机器上手敲 `docker compose`），
  反而增加一层"看起来有防护"的错觉。**改为纯纪律**，写进
  `docs/development-verification-process.md`：
  **在 `.3`/`.12` 这类运行着实例的机器上做测试，必须用独立 project 名**；
  实在不能用独立 project（如验证的就是生产布局），**先完整 down/up 一次**再测，
  测完恢复原状。测试目录用完即删（本次两个目录各 3.4G，且长期滞留会持续污染现场）。

## 3. 为什么不用其他方案

| 备选 | 否决理由 |
| --- | --- |
| **删掉多余的 compose**，只留一份 | 交付需要 offline 变体（`pull_policy: never`）、升级需要 upgrade 变体，删不掉；且交付物已含多份 |
| **给每个变体不同 project 名** | 同一套环境不能同时跑在不同 project 名下（网络/卷/端口都会分叉），语义错误 |
| **只改文档，提醒用户别用错** | 本次事故就是"照着最正统的名字"用错。文档挡不住可读性诱导 |
| **让 Docker 不比较 config-hash** | `config-hash` 是 Docker Compose 核心机制，无法关闭；且失去它的保护更危险 |
| **升级/迁移时自动纠正 compose** | 属于"善后动作"，会掩盖问题；本设计选择**事前拦住** |

## 4. 改动面

| 文件 | 改动 | 性质 |
| --- | --- | --- |
| `delivery/compose-guard.sh` | 新增：自包含守卫脚本（**不依赖 lib/**，因为交付目录无 lib） | 新文件 |
| `scripts/build_offline_delivery.py` | `SCRIPT_SOURCES` 增加两条，把守卫复制进 `install/` 与 `upgrade/` | 3 行 |
| `delivery/install/install.sh` | 幂等检查**之前**回填标记（取自容器标签，见 §2.1.1）；`compose up` 前调守卫；新增 `--force-compose-switch` | 回填 + 一次调用 + 新选项 |
| `delivery/upgrade/upgrade.sh` | 若有 compose 操作则调守卫（当前不碰 compose，仍加防护位） | 轻量 |
| `ops/install.sh`、`ops/upgrade.sh` | 转发前调守卫，给使用者一致性提示 | 轻量 |
| `backend/tests/test_us37_compose_guard.py` | 新增：守卫行为单测 | 新测试 |
| `docs/development-verification-process.md` | 补「运行中机器做测试」的纪律 | 文档 |
| `docs/troubleshooting.md` | 新增症状：**`exit 137` + `OOMKilled=false` = 被人为 SIGKILL，先查谁在 recreate** | 文档 |

**不改动**：`docker-compose*.yml`（4 个变体保持现状）、`scripts/build_*.py`、任何后端业务代码。

## 5. 测试计划

| # | 用例 | 环境 | 判据 |
| --- | --- | --- | --- |
| T0 | 标记回填：无标记 + 有运行容器 → 取容器 `config_files` 标签 basename；无容器 → 取 `$COMPOSE_FILE` | 本地（mock docker） | 取值正确 |
| T1 | 守卫：无 `.env` 标记且**无法回填**（无 docker/无容器）时**放行**并提示 | 本地 | 不阻断（向后兼容） |
| T2 | 守卫：标记与传入一致 → 放行 | 本地 | exit 0 |
| T3 | 守卫：标记与传入**不一致** → 拒绝，给出三条路径 | 本地 | exit 2 + 提示含 active 值 |
| T4 | 守卫：`--force-compose-switch` → 先 down 再 up | `.14` | 无 recreate 冲突，容器干净重建 |
| T5 | `install.sh` 装完后 `.env` 含 `SMARTX_COMPOSE_FILE_ACTIVE` | `.14` | 变量存在且值正确 |
| T6 | 故意用错 compose 敲 `docker compose up -d` → 被守卫拒绝，服务不中断 | `.14` | 容器 ID 不变、health 不变 |
| T7 | 诊断文档：`exit 137` + `OOMKilled=false` 的判别步骤 | — | 文档含可执行命令 |
| T8 | 全量门禁无回归 | `.3` | 后端 689+ OK |

**T6 不可省**：它直接对应本次事故的判别用例。

## 6. 风险与回滚

- **风险 1：旧环境没有标记，被守卫"放行"** → 这是**有意的向后兼容**（T1）。
  代价是旧环境仍可能踩坑；缓解：守卫在放行时打印提醒，建议重装或手工补标记。
- **风险 2：`--force-compose-switch` 被滥用** → 它的语义是"完整停机再换"，
  比 recreate 安全；但仍会造成**计划内停机**。缓解：提示语明确写"会中断服务"，
  且不提供"静默强制"选项。
- **风险 3：守卫只放在 `ops/install.sh` 里，但客户用的是交付目录的 `install.sh`** →
  **守卫必须同时放在交付态脚本里**（`delivery/install/install.sh`、`delivery/upgrade/upgrade.sh`），
  否则只保护开发者、放过客户。**这一点是本设计成败的关键**，实施时必须覆盖交付态。
- **回滚**：改动集中且不触碰 compose 与业务代码，`git revert` 即可。

## 7. 实施顺序

1. `delivery/compose-guard.sh`（含 `compose_guard_resolve` 地面真相回填）+ 单测（T0–T3）
2. `scripts/build_offline_delivery.py` `SCRIPT_SOURCES` 接线（交付态必须自包含）
3. `delivery/install/install.sh` 回填标记 + 调守卫 + `--force-compose-switch` → T4、T5、T6（`.14` 实测）
4. `delivery/upgrade/upgrade.sh` 加防护位
5. `ops/install.sh`、`ops/upgrade.sh` 提示 + 文档（T7，含删除 test-env.sh 的决定）
6. `.3` 全量门禁（T8）
7. 更新 `docs/upgrade-strategy-issues.md` US-37 状态、`progress.md`、ledger
