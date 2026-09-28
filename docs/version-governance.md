# 版本治理说明

本文档记录平台版本、upgrade-runner 组件版本、Docker 镜像 tag 和升级包的维护规则。

## 版本模型

- 平台版本由根目录 `VERSION` 定义，当前为 `v0.5.3`（开发候选）。**已正式发布的平台版本为 `v0.5.2`**；`v0.5.3` 的发布动作（推送、打 tag、创建 release、对外交付）待用户明确指令。
- 当前开发口径固定为 `v0.5.3`：源码版本、README、文档、升级包和常规镜像 tag 必须一致；候选的验收状态以 `docs/releases/CHANGELOG.md` v0.5.3 节为准（未发布）。
- 临时测试升级包可以使用不同目标版本验证升级链路，但只作为测试包元数据；不能反向修改 `VERSION`、README 或正式发布口径。
- 平台服务包括 `web-api`、`collector-worker`、`frontend`。
- `upgrade-runner` 是独立升级执行组件，版本由根目录 `RUNNER_VERSION` 定义，当前为 `v0.3.2`（2026-09-27 bump：把 08-12 之后累积的 runner 修复按规矩交付；已发布线 `v0.3.1` 见 Release 资产 `d10e15cf…`）。
- **`v0.3.2` 本次不交付（用户 2026-09-28 决定）**：**与下一个版本一起发**，本次不补 `runner-v0.3.2` tag / 镜像 / 组件包资产。因此：①源码三个 compose 里的 `upgrade-runner:v0.3.2` 属**开发线状态**，**发布会话只发平台包**（平台包内渲染的 runner 基线始终是**已发布 `v0.3.1`**，已实测）；②发布材料（CHANGELOG/release notes/OVA 说明）**不得把 v0.3.2 写成本次交付物**；③若本次做 OVA/全新部署，其 compose 必须落在已发布 `v0.3.1`（源码 compose 的 v0.3.2 不能进交付物，否则拉不到镜像）；④US-24 的 runner 修复与 v0.3.2 的实际交付一并归到下一版（届时按规矩 bump `v0.3.3`）。
- 后端镜像会同时内置 `/app/VERSION` 和 `/app/RUNNER_VERSION`，运行时优先读取镜像内版本文件，环境变量只作为兜底覆盖。
- 平台升级包不包含 `upgrade-runner`，也不重启 `upgrade-runner`。
- `upgrade-runner` 只能通过组件升级包更新。
- **升级顺序铁律（必须遵循，2026-09-27）**：**先升平台、再做 runner 组件升级**；runner 组件升级永远不是平台升级的前置条件。目标布局源端（v0.5.2）的 web-api 在执行 runner 组件升级时会无条件 stop `upgrade-runner`，把刚启动的新 runner 停掉（同 project 守卫只在 v0.5.3 起的镜像里）；唯一例外是源端仍为旧 project（如 v0.5.1u2）。**v0.5.2 → v0.5.3 可一步直升**（`source_compatibility` 覆盖 v0.5.0~v0.5.3，平台包 runner 基线固定为已发布 `v0.3.1`）。完整规则、源端矩阵与症状速查见 [docs/deployment.md](deployment.md) §10.1 与 AGENTS.md §7「升级顺序与源端矩阵」。

## Runner 能力与版本治理（2026-09-27 用户令）

- **能力基准以远端仓库为准**：runner 的代码与能力（动作表 `upgrade_runner/actions.py`、能力映射 `upgrade_protocol/constants.py`、组件包 manifest 能力集）以 `origin/dev2` / `origin/main` 为唯一基准。本地工作区、现场测试机、任何 AI 会话都**不得私自修改 runner 能力或代码**，也不得私自重建/替换 runner 镜像或组件包后仍沿用原版本号。
- **确需修改必须先经用户同意**：没有用户明确同意，不动 runner 一行代码；同意之后才改，改完立刻同步版本号与台账。
- **改能力必须改版本号**：能力变更必须同时提升根目录 `RUNNER_VERSION`、镜像内 `/app/RUNNER_VERSION`、镜像 tag、组件包文件名与 manifest `version`/`min_version`，并在 `docs/releases/CHANGELOG.md` 记录能力差异。**禁止"同版本号、不同能力"**——`min_runner_version`、动作能力预检查、现场排障都依赖"同版本号 = 同能力"这个前提，一旦破坏，升级会在最坏时机（平台已切换后）失败。
- **打包口径**：runner 组件包只能用 `scripts/build_runner_component_package.py` 从远端仓库对应提交构建；产物必须登记 `docs/upgrade-package-ledger.md`（SHA、构建提交、相对上一版的能力变化）。
- **验收基线**：升级链路回归与任何 v0.5.x 升级验收，runner 基线必须取 `docs/releases/CHANGELOG.md`「当前正式升级包」记录的**已发布** runner 包，禁止用开发期本地重建镜像充当基线（否则验收环境 ≠ 交付环境）。
- **违规处置**：发现 `RUNNER_VERSION` 未变而能力集已变，先停手并报告用户，由用户决定「补版本号」还是「把能力改回去」。

## Docker 镜像 tag

平台服务镜像使用平台版本：

```text
nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3
nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.3
nazawsze/smartx-hci-capacity-insight-frontend:v0.5.3
```

runner 组件镜像使用 runner 组件版本：

```text
nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1
```

`docker-compose.yml`、`docker-compose.offline.yml` 和 `docker-compose.release.yml` 使用两个独立变量：

```text
SMARTX_IMAGE_TAG          # 平台服务 tag，例如 v0.5.3
SMARTX_RUNNER_IMAGE_TAG   # upgrade-runner tag，例如 v0.3.1
```

默认开发 compose 也使用正式镜像名和版本 tag。允许本地重建镜像，但运行镜像名仍应是
`nazawsze/smartx-hci-capacity-insight-<service>:<version>`，不能回退到
`smartx-storage-forecast-<service>:local`。这样升级包 manifest、compose runtime 和线上容器状态才能保持同一套镜像口径。

## GitHub Actions

- `.github/workflows/docker-images.yml` 只构建平台三件套。
- `.github/workflows/upgrade-runner-image.yml` 只构建 `upgrade-runner`。
- runner 镜像只通过手动 workflow 或 `runner-v*` tag 构建，例如推送 `runner-v0.3.1` 后，DockerHub 镜像 tag 为 `v0.3.1`。
- 不允许 runner 跟随平台 `v*` tag 自动构建。
- **改了 runner 就必须推 `runner-v<新版本>` tag**：workflow 产出 `type=raw`（版本 tag）和 `type=sha`（`runner-sha-*` 副标签）两个 tag；**`runner-sha-*` 不是版本依据**（2026-09-27 事故：`runner-sha-31a1209` 与 `v0.3.0` 同 digest，只是 06-12 那次 0.3.0 构建的副标签，被误当成"最新"）。
- **发布前必须核对 DockerHub 上版本 tag 存在**（`hub.docker.com/v2/repositories/.../tags/<version>` 返回 200，404 = 没交付）：2026-09-27 实测该仓库只有 `latest`(06-05)、`runner-sha-31a1209`(06-12)、`v0.3.0`(06-12)，**`v0.3.1` 404 —— 从来没推过 `runner-v0.3.1` tag**。

## 升级包规则

平台升级包由 `scripts/build_upgrade_package.py` 生成，包含：

```text
manifest.json
checksums.sha256
release-notes.md
images/web-api.tar
images/collector-worker.tar
images/frontend.tar
project/**
migrations/run_migrations.py  # 可选，仅 migration_steps 非空时包含
```

`v0.5.2` 起的平台升级包只面向 v2 同架构后续升级，不声明兼容 v1 或 `v0.4.x` 原地升级。v1/v0.4.x 现场数据兼容通过“新装 v2 + 数据迁移包导入”完成，迁移包兼容 SQLite 业务数据、Prometheus 历史指标和旧 VM 卷 payload。

**v0.5.1u2 + runner v0.3.1 可直接升级到最新版本（v0.5.3）**：v0.5.3 升级包的 `source_compatibility` 覆盖 v0.5.0/v0.5.1/v0.5.1u1/v0.5.1u2/v0.5.2/v0.5.3，且 manifest 含 `environment_transitions`/`directory_transition`/`legacy_cleanup`，可从 v0.5.1u2 的旧 project/network 一步切换到目标布局。已验证（2026-09-15，见 progress.md）。后续新版本应保持该直升能力。

平台升级支持 v2 同架构跨版本直升。打包器读取 `backend/app/v2/upgrade/migrations/registry.json`，按 `source_version < step.version <= target_version` 选择累计 SQLite 迁移步骤。没有选中迁移步骤时，manifest 必须为 `database_migration=false`，且不包含 `migration`、`migration_steps` 或 `script.sandbox.v1`。有迁移步骤时，包内生成单文件 `migrations/run_migrations.py`，manifest 同时写入 `migration_steps[]` 和 legacy `migration.script`，以兼容 `upgrade-runner v0.3.1`。是否携带迁移只由来源版本、目标版本和迁移注册表共同决定，不能只看目标版本自身是否改 schema。同版本应用允许，例如 `v0.5.2 -> v0.5.2`，用于修复安装或重同步镜像、项目文件和 runtime override；由于迁移选择规则是左开右闭，同版本应用不会重复选择迁移步骤。

所有未来 SQLite schema 变化必须新增 migration step，不能只改 `database.initialize()`。迁移执行成功后记录到 SQLite `schema_migrations(id, version, description, script_sha256, applied_at)`；迁移脚本必须幂等，已存在 schema 或已记录 step 时跳过或补记录。普通 schema 变化可在 registry step 中声明 `sql` 字符串数组；SQLite 加列必须使用 `add_column_if_missing` 操作，避免重复执行 `ALTER TABLE ADD COLUMN` 失败。

组件升级包由 `scripts/build_runner_component_package.py` 生成，包含：

```text
manifest.json
checksums.sha256
release-notes.md
images/upgrade-runner.tar
```

Prometheus/observability 组件升级包由 `scripts/build_prometheus_component_package.py` 生成。默认生成轻量包，镜像通过 manifest 中的 `image` 引用仓库 tag，包内包含：

```text
manifest.json
checksums.sha256
release-notes.md
config/prometheus.yml
health/queries.json
```

离线环境使用 `--offline-image` 时才额外包含 `images/prometheus.tar`，并在 manifest 中声明 `archive` 和 `sha256`。Prometheus 历史指标数据不进入升级包；升级前备份留在服务器用于回滚，历史指标导出只属于完整数据迁移包。

所有新升级包使用 manifest schema 3，声明 `minimum_runner_protocol` 与 `required_capabilities`。平台版本号不再机械绑定 Runner 版本；只有能力不满足时才要求先升级 Runner。

## OVA 交付规则

OVA 是全新部署或演示环境交付制品，不属于升级中心包。升级中心包仍按本文件的 `.tar.gz` 平台包、Runner 组件包、Prometheus 观测包和组合包规则管理。

OVA 文件名、升级包 manifest 版本和文档版本必须使用同一个正式平台版本。Runner 组件包仍使用 `RUNNER_VERSION`，不跟随平台版本。

OVA 与升级包都禁止包含 `.env`、SQLite 数据库、Prometheus 历史数据、备份、导出文件、Tower 凭据、token 或客户现场数据。详细检查清单见 [OVA 交付说明](ova-delivery.md)。

## 发版检查清单

每次发版必须检查并更新：

- `VERSION`
- `RUNNER_VERSION`：**只要 runner 代码或能力有任何变化就必须同步更新**（哪怕是"顺手改"），并且必须在**改代码的同一次提交**里完成——只改代码不改版本号 = 发布阻断（2026-09-27 事故：`dab2e0f` 给 runner +2053 行新动作却没 bump，导致同一 `v0.3.1` 三套能力）。
- **runner 交付三件套必须同源且齐全**（缺一即不许发布）：
  - 仓库：`RUNNER_VERSION` 与 `backend/app/upgrade_runner/actions.py` 动作表；
  - Release 资产：`smartx-upgrade-runner-<version>.tar.gz`（解包 grep 关键动作必须与仓库一致），并把 SHA 写进 `docs/releases/CHANGELOG.md` 与 `docs/upgrade-package-ledger.md`；
  - Git tag `runner-v<version>` 已推送（触发 `.github/workflows/upgrade-runner-image.yml`），且 DockerHub 上该 tag 可拉到（`hub.docker.com` tags API 核对，不允许 404）。
- **Release 资产必须与 tag 同源、由 CI 产出**：资产只能是 `runner-v*` / 平台 tag 触发的 workflow 构建结果（记录 `head sha`），**禁止本机手工打包后直接上传 Release**（2026-09-27 实证：`v0.5.1u2` 平台资产同源，runner 资产却是 07-09 本地打包上传，源码未入库 → tag 源码 11 个动作、资产 25 个动作，无法用 tag 复现客户手上的东西）。
- **验收只认 Release 资产**：链路回归与升级验收必须用 Release 里的平台包 + runner 包跑，禁止用测试机本地重建镜像；验收记录必须写明 SHA 与来源。
- `backend/app/core/config.py` 中平台默认版本
- `backend/Dockerfile`、`backend/Dockerfile.worker`、`backend/Dockerfile.upgrade` 是否复制 `VERSION` 和 `RUNNER_VERSION`
- `docker-compose.offline.yml`
- `docker-compose.release.yml`
- `docker-compose.upgrade.yml`
- `README.md`
- `README.zh-CN.md`
- `docs/ova-delivery.md`
- `docs/releases/CHANGELOG.md`
- `scripts/build_upgrade_package.py --check-version`

## DockerHub 错误 tag 清理

如果 runner 仓库被错误打上平台 tag，可以用 DockerHub API 删除。先创建 DockerHub Access Token，然后执行：

```bash
export DOCKERHUB_USER='你的DockerHub用户名'
export DOCKERHUB_TOKEN='你的DockerHub Access Token'
export NAMESPACE='nazawsze'
export REPO='smartx-hci-capacity-insight-upgrade-runner'

TOKEN="$(
  curl -fsSL -X POST 'https://hub.docker.com/v2/users/login/' \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${DOCKERHUB_USER}\",\"password\":\"${DOCKERHUB_TOKEN}\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])'
)"

for TAG in v0.5.2 v0.4.0 v0.3.3u2 v0.3.3U1 v0.3.3 v0.3.2 v0.3.1 main latest; do
  echo "Deleting ${REPO}:${TAG}"
  curl -fsS -X DELETE \
    -H "Authorization: JWT ${TOKEN}" \
    "https://hub.docker.com/v2/namespaces/${NAMESPACE}/repositories/${REPO}/tags/${TAG}/" \
    -w " -> HTTP %{http_code}\n"
done
```

删除后检查：

```bash
curl -fsSL "https://hub.docker.com/v2/repositories/${NAMESPACE}/${REPO}/tags?page_size=100" \
| python3 -c 'import json,sys; print("\n".join(t["name"] for t in json.load(sys.stdin)["results"]))'
```

不要删除平台三件套仓库中的平台版本 tag。

## 历史 tag 版本口径说明

以下历史 git tag 的源码 `VERSION` 与 tag 名称不一致，已发布无法修改，仅作记录，避免后续误用：

| tag | 指向提交 | 提交内 `VERSION` | 提交内 `RUNNER_VERSION` | 说明 |
| --- | --- | --- | --- | --- |
| `v0.5.1u2` | `baaffcd` | `v0.5.2` | `v0.3.1` | 源码文件已按 v0.5.2 口径维护，但 tag 名为 v0.5.1u2。该 Release 发布的升级包（`d5f27716...`）才是真正的 v0.5.1u2 语义。**不要直接 checkout 该 tag 编译镜像作为 v0.5.1u2 产物**；v0.5.1u2 以 Release asset 为准。 |

规则：

- 发布新版本时，`git tag` 名称必须与提交内 `VERSION` 一致；不一致时禁止打 tag。
- 已发布的历史 tag 不做修改；如需修正语义，通过新的 tag 或 Release 说明补充。
- 升级包以 GitHub Release asset 的 SHA256 为准，不以 git tag 源码为准。


## 升级包与源码 compose 的字面量 tag 规则（2026-09-20 更新，49-3）

- **源码 compose 与升级包内 compose 均为字面量 tag**（registry+tag 全写死，与 `VERSION`/`RUNNER_VERSION` 一致）：49-3 起三个源码 compose 的镜像引用全部字面量化，现场 `.env` 无法让源码部署静默漂移到旧镜像。
- `check_versions` 门禁断言三源码 compose 字面量 tag 与 VERSION 一致，并**禁止出现** `SMARTX_IMAGE_TAG`/`SMARTX_RUNNER_IMAGE_TAG`/`SMARTX_IMAGE_PREFIX`/`SMARTX_RUNNER_IMAGE_PREFIX` 模板变量与 `:latest`（模板回潮即构建失败，fail-fast）。
- 版本晋升时同步改 `VERSION`/`RUNNER_VERSION`/compose 字面量/README/CHANGELOG（见发版检查清单）；构建期 `temporary_image_version_metadata` 会临时改写 compose 渲染目标版本，构建后还原。
- `.env` 不应定义 `SMARTX_IMAGE_TAG/RUNNER_IMAGE_TAG/APP_VERSION/RUNNER_VERSION`（对字面量 compose 无效，徒增误导）；升级链路纵深防御保留：runner 升级时从目标 .env 剥离上述四个变量（`upgrade_runner/actions.py IMAGE_TAG_ENV_KEYS`）。

## 发布节奏（2026-09-20 定）

**发版模式：攒批发版，无固定日历周期。** 满足其一即开一个发版批次：

1. 积累 3~5 个已完成并验证的功能/修复（task_plan 有验收证据）；
2. 出现必须尽快交付的缺陷修复——hotfix 不受攒批限制，单独出 patch 版本走完整门禁；
3. 用户指定时间点（如现场部署计划）。

**发版硬门禁（每批必过，不省略）**：

- 全量测试回基线（后端 unittest + 前端 tsc/vitest）+ `build_upgrade_package.py --check-version`；
- .3 全新完整构建升级包（非增量重打）+ `verify_upgrade_package_identity` + 包内 compose 字面量不变量 + 台账记录；
- 10.20.11.12 从真实旧版本基线走正规升级链路（上传→预检查→升级→post-cleanup→8 项验收），任务 ID 与证据入 progress.md；
- CHANGELOG（七段结构）/版本治理/台账同步更新。

**环境角色（2026-09-20 更新；同日用户重申 .12 纪律）**：`10.20.0.6` 确认为 frp Tower 主机，**不再是 release canary 目标**；"生产等价"验收职责由 10.20.11.12 代行（Phase 30 全新部署验收 + 多轮真实升级验收已覆盖）。如未来获得专用干净 canary 主机，恢复 release-acceptance.md 的 canary 全新部署门禁。

**10.20.11.12 纪律（用户 2026-09-20 重申）：.12 是发布机器，严格按真实环境对待**——宿主上不做任何手工运维变更（手工 `docker rmi`、手工清理目录、手工改文件等一律不做）；.12 的一切变更只能走产品自身流程（升级中心升级、产品功能如空间清理页）。测试机磁盘卫生类需求在 .12 上只能等对应能力随发版火车交付后用产品功能完成，不能因省事在宿主手工执行。

**版本号规则**：bug/治理批次走 patch（v0.5.x）；含面向用户新能力的批次升 minor（v0.6.0）；runner 保持独立版本线（`runner-v*` tag 单独构建，不随平台 tag）。

**发布动作链（仅用户明确说"发布 v X.Y.Z"后执行）**：

1. 推送 dev2 到 origin；
2. main 对齐 dev2（fast-forward）并推送；
3. 打 tag `v X.Y.Z`（tag 名必须与提交内 VERSION 一致，不一致禁止打 tag）；
4. GitHub Release 附升级包 tar.gz 与 SHA256（Release asset 是升级包权威来源）；
5. 确认 DockerHub 镜像 tag（平台三件套 vX.Y.Z；runner 按其独立版本）；
6. CHANGELOG 状态"候选，未发布"→"已发布"，version-governance 已发布版本翻转；
7. 生产升级窗口：生产环境走正常升级链路（升级前基线留档+自动备份，升级后 8 项验收）；生产环境地址与当前版本由用户提供。
