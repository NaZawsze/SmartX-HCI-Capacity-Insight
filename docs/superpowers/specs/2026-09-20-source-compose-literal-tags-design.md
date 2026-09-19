# 源码 compose 镜像 tag 字面量化设计（Phase 49-3 收尾）

日期：2026-09-20
状态：**已实施并验证（2026-09-20，提交 556a85f）**
关联：task_plan.md Phase 49 第 3 项（compose 镜像 tag 仍可被 .env 覆盖 [待实施]）与第 15 项（包侧字面量渲染，已完成）、CHANGELOG v0.5.3 已知问题「源码 compose 模板默认 tag 可被现场 .env 覆盖」、docs/superpowers/specs/2026-09-13-compose-literal-tags-design.md（前置设计）

## 1. 背景与问题

三个源码 compose 文件当前使用变量模板（v0.5.3 口径，行号已核实）：

- `docker-compose.yml:8,40,64,79` 与 `docker-compose.offline.yml:5,36,59,72`：
  `image: ${SMARTX_IMAGE_PREFIX:-nazawsze}/smartx-hci-capacity-insight-{web-api|collector-worker|frontend}:${SMARTX_IMAGE_TAG:-v0.5.3}`；
  runner 行为 `${SMARTX_IMAGE_PREFIX:-nazawsze}/smartx-hci-capacity-insight-upgrade-runner:${SMARTX_RUNNER_IMAGE_TAG:-v0.3.1}`。
- `docker-compose.release.yml:5,35,57,69`：同构，prefix 默认值为 `docker.io/nazawsze`。

**风险场景**：源码部署路径（开发机/测试机直接对仓库 compose 执行 `docker compose up`）若现场 `.env` 残留旧值（如 `SMARTX_IMAGE_TAG=v0.5.2`），compose 会静默使用旧镜像，无任何报错——版本漂移且难以察觉。builder 自身已把该场景列为警告（`scripts/build_upgrade_package.py:147-152` 打印「.env defines SMARTX_IMAGE_TAG; 源码部署时该值会覆盖 compose 占位符默认值，可能导致版本漂移」），但警告只在构建时打印，拦不住绕过构建直接 `compose up` 的路径。

**已安全、本设计不动的部分**（读码核实）：

- 升级包路径：`_render_packaged_compose_tags`（build_upgrade_package.py:858-873）打包时把 `${PREFIX}/repo:${TAG}` 模板整体渲染为完全字面量；`_assert_project_files_match_version`（:888-926）禁止包内 compose（≥v0.5.2）出现 `SMARTX_IMAGE_TAG`/`SMARTX_RUNNER_IMAGE_TAG` 字符串并强制 `:{version}` 存在。
- 升级执行路径：runner 升级时从目标 `.env` 剥离 tag 键（`backend/app/upgrade_runner/actions.py:364` `IMAGE_TAG_ENV_KEYS`、:420-434 `_sanitize_env_text`），有专项测试覆盖（test_upgrade_runner_engine.py:1602-1687）。
- `docker-compose.upgrade.yml`：仓库内已是字面量（`nazawsze/...:v0.5.3`），是本设计要对齐的先例。

历史口径：49-15（2026-09-13）核实包管线已渲染字面量后决定「包构建时渲染、源码模板保留占位符」；本设计收尾其遗留的源码侧风险。

## 2. 方案：源码 compose 全字面量化（prefix + tag 一起）

把三个源码 compose 的全部平台镜像行改为字面量（值与当前 VERSION/RUNNER_VERSION 一致）：

```text
docker-compose.yml / docker-compose.offline.yml:
  image: nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3
  image: nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.3
  image: nazawsze/smartx-hci-capacity-insight-frontend:v0.5.3
  image: nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1
docker-compose.release.yml:
  image: docker.io/nazawsze/smartx-hci-capacity-insight-{web-api|collector-worker|frontend}:v0.5.3
  image: docker.io/nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1
```

**prefix 一并字面量化的理由**：`_render_packaged_compose_tags` 的正则要求 prefix+tag 模板成对出现才渲染；若只字面量化 tag，包内 compose 会残留 `${SMARTX_IMAGE_PREFIX:-…}` 模板（正则不匹配，且现有 forbidden 断言不覆盖 prefix），重新打开「包内镜像引用可被现场 .env 改写」的口子。全字面量化后该渲染函数退化为纯防御层，包内 compose 与源码 compose 同为字面量。

**版本演进机制（已核实，无需新增代码）**：`temporary_image_version_metadata`（build_upgrade_package.py:199-239）在每次构建/打包期间临时改写源码 compose——`_replace_compose_version_tags`（:175-196）同时覆盖模板形态（`SMARTX_IMAGE_TAG:-[^}]+`）与字面量形态（`smartx-hci-capacity-insight-<repo>:v[0-9A-Za-z._-]+`）的改写；`build_package` 全程包裹在该上下文内（:941），bridge（<v0.5.2）构建路径同样被覆盖。因此字面量化后构建任意目标版本（含 v0.5.1u2 桥接包）时，源码文件会被临时改写为目标版本再打包，构建后还原，机制不变。

### 唯一代码改动点：check_versions 门禁适配

`check_versions`（build_upgrade_package.py:129-158）目前断言源码 offline/release 含 `SMARTX_IMAGE_TAG:-{version}` 模板——字面量化后必然失败，需同步适配：

- 断言三个源码 compose（offline/release/**docker-compose.yml**，后者此前未纳入）含字面量 `nazawsze/smartx-hci-capacity-insight-web-api:{version}`（collector-worker/frontend 同构）；release.yml 按 `docker.io/nazawsze/...` 前缀断言。
- 断言 runner 字面量 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:{runner_version}`。
- 新增强化禁令：三个源码 compose 禁止出现 `SMARTX_IMAGE_TAG`、`SMARTX_RUNNER_IMAGE_TAG`、`SMARTX_IMAGE_PREFIX` 字符串（比原「不得默认 latest」更强；`:latest` 禁令保留）。
- 原「upgrade-runner 不得使用 SMARTX_IMAGE_TAG」检查（:145-146）在新禁令下冗余，保留或合并均可。
- `.env` 警告（:147-152）前提失效（这些键对字面量 compose 不再生效）：删除该警告，由新禁令承担防回退职责（任何人重新引入模板会让 check_versions 直接失败，fail-fast）。

其余机制逐一核实为兼容、无需改动：

- `LEGACY_PROJECT_FILE_VALUES` 的两条 tag 替换（:97-98）在字面量源码上成为空操作；bridge 构建正确性由 temporary 改写 + `_assert_project_files_match_version` 的 <v0.5.2 分支（要求 `:{version}`+`:v0.3.0`、禁止模板字符串）保证。
- `docker_build` 的 `env SMARTX_IMAGE_TAG={version}`（:260-261）变为冗余但无害：保留（build_tests:452 断言该命令形态，保留避免无谓测试 churn）。
- `_assert_project_files_match_version` ≥v0.5.2 分支无需改动；字面量化后该门禁从「校验渲染产物」升级为「校验源码本体」。
- `prom/prometheus:v2.55.1` 本就字面量，不动。

### 有意接受的行为变化（权衡）

- 开发者不能再靠 `.env SMARTX_IMAGE_TAG=xxx` 让源码 compose 跑任意 tag；定制构建需 `docker build -t` 或临时改文件。理由：AGENTS.md 第 8 节「发布包中的 Compose 应写入明确、可审计的镜像身份；不能靠现场 .env 随意切换到另一个版本来完成验证」——把同一纪律延伸到源码 compose；版本漂移风险的权重高于构建便利。
- 版本号晋升（如下次 v0.5.4）时 compose 内 tag 从「改模板默认值」变为「改字面量」，工作量相同；check_versions 强制 VERSION 与 compose 字面量一致（与原模板断言的防呆等价）。

## 3. 影响面与测试计划

测试影响（已逐一核实）：

- `backend/tests/test_deployment_config.py:109-120` 已是双形态断言（模板或字面量皆通过），字面量化后自然走字面量分支；实施时顺手收紧为「仅字面量 + 禁模板字符串」，与新门禁对齐。
- `backend/build_tests/test_v2_package_builders.py:238-243,372-377` 断言包内 compose 无模板字符串且含字面量 tag——mock 文件系统驱动，不受源码形态影响，保持通过。
- `backend/tests/test_upgrade_runner_engine.py:1602-1687` 为 .env 剥离行为测试，无关。

验证步骤：

1. 本地：改三个 compose + `check_versions` 适配 + test_deployment_config 收紧；运行 backend 定向测试（deployment + build_tests）。
2. .3：`git archive` 同步代码后执行 `python3 scripts/build_upgrade_package.py --check-version`（check_versions 新断言的真机验证，不构建不产包）；backend 全量回归。
3. **明确不做**：不重打交付包。e940e07c 是已冻结的验证产物，不受源码后续改动影响，仍是 49-22 恢复时的待用包；下次真实打包（49-22 恢复或下一版本）自然纳入本变更并再次走全门禁。

## 4. 回滚

单提交 revert 即恢复模板形态；未构建新包、未动任何机器状态，无数据风险。check_versions 新断令保证：任何遗漏的模板回潮会在下一次构建/校验时立即失败（fail-fast），不会静默。
