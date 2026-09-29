# 发版构建手册：从源码到可交付物

面向"要为新版本产出升级包 / 离线交付目录的人"。**一条命令**跑完整链条：

```bash
bash scripts/build_release_delivery.sh --runner-baseline v0.3.1
```

> 编排器：`scripts/build_release_delivery.sh`
> **不要手工串下面这些脚本**——顺序和门禁都在编排器里固化了，手工串容易漏门禁。

---

## 1. 前置条件

| 项目 | 要求 |
| --- | --- |
| 执行机 | 构建机（本项目惯例：`10.20.11.3`），需能 `docker build` |
| 工具 | `docker`（含 Compose V2 插件）、`python3`、`sha256sum` |
| 源码 | 干净的工作树，且**已提交**——打包用的是工作树内容，未提交改动不会进包 |

`.3` 上的标准做法是 `git archive HEAD` 传输（`.3` 项目目录不是 git 检出）：

```bash
# 本地
git add -A && git commit -m "..."
git archive HEAD | gzip > /tmp/v053-$(git rev-parse --short HEAD).tar.gz
scp /tmp/v053-*.tar.gz user1@<构建机>:/home/user1/
# 构建机
cd /data/smartx-storage-forecast/project && tar -xzf /home/user1/v053-*.tar.gz
```

**先提交再 archive**——踩过的坑：回退改动没提交就 archive，打出来的仍是旧树（见 progress.md 第 4 批）。

---

## 2. 一条命令

```bash
cd /data/smartx-storage-forecast/project
bash scripts/build_release_delivery.sh --runner-baseline v0.3.1
```

它按顺序执行 6 步，**任一门禁 FAIL 立即中止**，不会产出"看起来完整"的交付物：

| 步骤 | 动作 | 门禁 |
| --- | --- | --- |
| 0 | 版本元数据一致性 | `build_upgrade_package.py --check-version` |
| 1 | 构建平台升级包 | — |
| 2 | 平台包身份门禁 | `verify_upgrade_package_identity.py`（manifest / 版本文件 / 镜像 tag / SHA256） |
| 3 | 构建 runner 组件包 | — |
| 4 | runner 交付一致性门禁 | `verify_runner_delivery_consistency.py`（仓库 ↔ 包 ↔ 包内镜像源码树指纹） |
| 5 | 组装离线交付目录 | 内含**禁含文件扫描**（`.env` / SQLite / 凭据 / backups / exports） |
| 6 | 产物 SHA 清单 | — |

产物：

```text
<output-root>/
├── smartx-capacity-insight-upgrade-<version>.tar.gz
├── smartx-upgrade-runner-<runner-version>.tar.gz
├── SHA256SUMS-<时间戳>                    ← 登记到 docs/upgrade-package-ledger.md
└── smartx-capacity-insight-<version>-offline/   ← 完整离线交付目录
    ├── README.md
    ├── install/   （镜像 + install.sh）
    └── upgrade/   （升级包 + upgrade.sh）
```

---

## 3. 常用参数

| 参数 | 说明 |
| --- | --- |
| `--runner-baseline <tag>` | **组装交付目录时必填**，如 `v0.3.1`。指交付物里**安装用** compose 的 runner 基线 |
| `--skip-delivery` | 只出升级包，不组装交付目录（此时不需要 `--runner-baseline`） |
| `--output-root <目录>` | 产物根目录，默认 `/data/upgrade-packages` |
| `--platform-package <包>` | 复用已有平台包，跳过步骤 1–2 |
| `--runner-package <包>` | 复用已有 runner 包，跳过步骤 3–4 |
| `--reuse-images` | 复用已构建镜像，不重新 `docker build`（必须已构建过） |
| `--check-dockerhub` | 额外校验 DockerHub tag。**发版前必加**（平时 tag 还没推，会 SKIP） |
| `--runner-version <tag>` | runner 包版本，默认取仓库 `RUNNER_VERSION` |
| `--prometheus-image <img>` | prometheus 镜像，默认 `prom/prometheus:v2.55.1` |
| `--prometheus-archive <tar>` | 已备好的 prometheus 归档；给了则不 `docker save`，构建**字节级可复现** |
| `--readme <路径>` | 交付 README 源文件，默认 `delivery/README.md` |

### `--runner-baseline` 与 `--runner-version` 的区别（容易混）

| | 是什么 | 取值 |
| --- | --- | --- |
| `--runner-version` | 本次**构建**的 runner 包版本 | 仓库 `RUNNER_VERSION`（开发线） |
| `--runner-baseline` | 交付物里**安装**时落地的 runner 版本 | **已发布**版本（如 `v0.3.1`） |

交付物先用**已发布基线**装起来，客户之后再用 `upgrade/upgrade.sh --with-runner` 升到新版本。
所以两者**不必相同**，通常也不相同。

---

## 4. 改版本号时要同步哪些文件

编排器步骤 0 会检查，不一致会中止并提示。按平台 / runner 分别列出：

**平台版本（`VERSION`）**：
- `VERSION`
- `docs/releases/CHANGELOG.md` 新增版本节
- `docs/upgrade-package-ledger.md` 登记包与 SHA
- `backend/app/**` 里的版本默认值（`core/config.py`、`v2/config.py`）

**runner 版本（`RUNNER_VERSION`）**——**改了 runner 能力就必须 bump**（AGENTS §6/§8）：

- `RUNNER_VERSION`
- `docker-compose.yml`、`docker-compose.offline.yml`、`docker-compose.release.yml` 里的 runner image tag
- `backend/app/core/config.py`、`backend/app/v2/config.py` 的 `DEFAULT_RUNNER_VERSION`
- `backend/app/upgrade_runner/main.py` 的默认值
- 预检查提示文案、README 示例、`docs/version-governance.md` 等

> 允许的例外：`v0.3.2` **从未交付**，因此并入新修复时沿用 US-24 先例**不再 bump**；
> 一旦交付过，就必须 bump（"同版本号、不同能力"的 runner 一律视为违规）。

---

## 5. 发版前的额外动作

编排器只负责**构建与门禁**。发布动作（推 tag、建 Release、推 DockerHub）按
`docs/version-governance.md` 的"发版检查清单"执行，且**必须由用户明确要求**才做。

发版前额外要加的检查：

```bash
# 1) DockerHub tag 一致性（编排器加 --check-dockerhub 也会跑这个）
python3 scripts/verify_runner_delivery_consistency.py \
  --package <runner 包> --check-dockerhub

# 2) 对外文档脱敏
python3 scripts/verify_release_docs_safe.py

# 3) API 文档与后端路由一致
python3 scripts/verify_api_docs.py
```

---

## 6. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 步骤 0 版本门禁不过 | 按提示同步 `VERSION` / `RUNNER_VERSION` / 三个 compose 的 tag（见第 4 节） |
| 步骤 2 身份门禁不过 | 包内 manifest 与镜像/版本文件不一致，通常是改了版本号但镜像没重新构建；去掉 `--reuse-images` 重来 |
| 步骤 4 runner 门禁报"不一致模块：xxx" | 改了 runner 代码但没 bump `RUNNER_VERSION`（或反之 bump 了却没重新构建）——**同版本不同能力是违规** |
| 忘记组装交付目录 | 补 `--runner-baseline <已发布版本>`；或用 `--platform-package` / `--runner-package` 复用已有包 |
| `prometheus.tar` 每次 SHA 不同 | `docker save` 会写时间戳，**固有行为**。需要字节级可复现时，先存一份 `prometheus.tar` 再传给 `build_offline_delivery.py --prometheus-archive` |
| 磁盘不足 | 平台包约 240M、runner 包约 80M、交付目录约 1.4G；`--reuse-images` 可省掉镜像重建的临时空间 |

---

## 7. 关联

- 离线交付设计：`docs/superpowers/specs/2026-09-28-offline-one-click-install-upgrade-design.md`
- 实施计划：`docs/superpowers/plans/2026-09-28-offline-one-click-install-upgrade-plan.md`
- 版本治理：`docs/version-governance.md`
- 包台账：`docs/upgrade-package-ledger.md`
- 验证流程（验收/演练）：`docs/development-verification-process.md`
