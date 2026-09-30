# 开发 / 打包 / 功能测试验证标准流程

更新时间：2026-09-15
用途：本仓库对 AI 编码代理和自动化执行器的统一开发、打包、功能测试验证流程。开始任何代码、打包或远程验证前，先读本文件、[AGENTS.md](../AGENTS.md) 和 [project-guide-for-ai.md](project-guide-for-ai.md)。

## 1. 环境与机器

| 机器 | 角色 | 登录 | 用途 |
| --- | --- | --- | --- |
| 本地工作区 | 源码/测试/文档 | — | 编辑代码、本地测试、git 提交 |
| `10.20.11.3` | 开发/主测试机 | `ssh user1@10.20.11.3`（密码见 AGENTS.md），docker 需 `su - root` | 后端全量测试、前端测试、Docker 构建、升级包构建、完整链路验证 |
| `10.20.11.12` | 升级演练机 | `ssh root@10.20.11.12`（密码 `password`） | 升级链路验证、canary 验收（需用户授权） |
| `10.20.0.6` | release canary | 默认只读 | 正式发布验收（需用户批准具体命令） |

## 2. 开发流程

1. **立项**：在 `task_plan.md` 建立任务项，写明目标与验收标准。
2. **设计**：每个任务项关联设计文档（`docs/superpowers/specs/`）。确无必要的小任务可合并设计，但必须在任务项中注明"无专项设计文档，口径记录于本文件"及理由。
3. **实施**：按设计实现，先本地定向测试；失败记录根因，禁止静默重复同一失败操作。
4. **提交**：`git diff --check` 通过后本地提交 `dev2`，单任务尽量单提交。**dev2 默认只在本地提交，推送到 origin 必须用户明确要求。**
5. **验证**：在 `10.20.11.3` 按验收标准执行远端测试、构建和功能验证。
6. **收尾**：验证通过后在任务项勾选完成并在 `progress.md` 记录证据。

## 3. 打包流程

### 3.1 构建平台镜像

在 `10.20.11.3` 上（root）：

```bash
cd /data/smartx-storage-forecast/project
docker compose build web-api collector-worker frontend
docker compose up -d web-api collector-worker frontend
```

- 构建后必须检查镜像 tag 与 `VERSION` 一致（如 `v0.5.3`）。
- 前端构建失败会输出 `error TS`，必须看完整构建输出（`build | tail` 会吞失败）。

### 3.2 构建升级包

```bash
cd /data/smartx-storage-forecast/project
python3 scripts/build_upgrade_package.py --check-version   # 版本门禁
python3 scripts/build_upgrade_package.py --output-dir /data/upgrade-packages
```

- 升级包产物：`smartx-capacity-insight-upgrade-<version>.tar.gz` + `.sha256`。
- 包门禁：manifest、内部版本文件、Compose image tag、镜像归档 SHA256、sidecar SHA256 一致；不含 `.env`、SQLite、Prometheus 数据、备份、导出、Tower 凭据。
- 记录包 SHA 到 `docs/upgrade-package-ledger.md`。

### 3.3 构建 runner 组件包

```bash
python3 scripts/build_runner_component_package.py --version v0.3.1
```

- runner 组件包只包含 runner 镜像及其 manifest，不夹带平台镜像。
- **改 runner 必须三步一起做，缺一即停**：①同一提交 bump `RUNNER_VERSION`；②重新打组件包并把 SHA 记进 ledger + CHANGELOG；③推 `runner-v<新版本>` git tag 让 workflow 出 DockerHub 镜像并核对 tag 存在（2026-09-27 事故：三步都没做，`v0.3.1` 顶着三个不同能力，v0.5.3 升级在切换后失败）。

## 4. 功能测试验证

### 4.1 后端全量测试

在 `10.20.11.3` 容器内：

```bash
docker compose exec -T web-api sh -lc "cd /data/smartx-storage-forecast/project/backend && PYTHONPATH=/data/smartx-storage-forecast/project/backend python -m unittest discover -s tests 2>&1 | tail -3"
```

- 基线：**以 `docs/ai-handoff-2026-09-30.md` §6 为准（2026-09-30：全量约 728 tests，其中 1 失败为既有环境限制、非回归；对照证据见该文档）**。历史时点：2026-09-27 为 386 全绿（更早：2026-09-19 为 310、2026-09-13 为 308）。构建测试 `test_v2_package_builders` 在宿主机跑（`cd backend && python3 -m unittest build_tests.test_v2_package_builders`，26 tests OK）。**失败是否回归，先与最近一次基线对照再下结论。**

### 4.2 前端测试 + 构建

在 `10.20.11.3` 上（node:22-alpine 容器）：

```bash
docker run --rm -v /data/smartx-storage-forecast/project/frontend:/app -w /app node:22-alpine sh -c "npx tsc -b && npx vitest run"
```

- 基线：85 前端测试全绿（7 个测试文件）。
- 部署后 `docker compose up -d frontend` 并确认容器重建（镜像变化才会重建）。

### 4.3 部署健康检查

```bash
curl -fsS http://127.0.0.1:8000/api/system/health   # 期望 ok=true, version, runner_version, checks 全 true
curl -fsSI http://127.0.0.1:8080 | head -n 1        # 期望 HTTP/1.1 200
```

### 4.4 升级链路验证

固定升级链路（AGENTS.md 第 7 节）：

```text
v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2 -> v0.5.3
```

- **v0.5.1u2 + runner v0.3.1 可直接升级到最新版本（v0.5.3）**（已验证，见 progress.md）。
- 升级走升级中心 API：上传升级包 → 预检查 → 开始升级 → 轮询状态 → 验证。
- **runner 基线必须用「已发布」的 runner 组件包**（SHA 以 `docs/releases/CHANGELOG.md` 对应版本「当前正式升级包」为准），禁止用开发期本地重建镜像充当基线：2026-09-27 `.12` 实测，用开发镜像跑通的 v0.5.3 升级，换回发布包 `d10e15cf…` 就在切换后失败（`Runner 不支持动作：post_upgrade.schedule_collection`）——验收环境 ≠ 交付环境。同理，**未经用户同意不得修改 runner 能力/代码，改能力必须同步提升 `RUNNER_VERSION`**（详见 `docs/version-governance.md`「Runner 能力与版本治理」）。
- 升级验收 8 项：health、容器镜像 tag、project/network、SQLite 行数、Prometheus 历史、Tower 凭据、.env 权限、旧目录/历史/自动采集。
- 升级前记录基线（health、容器、网络、SQLite 行数、Prometheus series、Tower 凭据、.env 状态）。
- 升级前备份 `.env` 和 DB，确认配对（避免 Tower 凭据丢失）。

## 4.5 在运行着实例的机器上做测试（US-37 硬纪律）

> 2026-09-30 `.3` 服务中断事故的直接成因：在一台**正跑着平台实例**的机器上，
> 用另一份 compose 文件对**同一个 project 名**执行 `up` → Docker 判定配置变了 →
> recreate → 旧容器 SIGKILL（`exit 137`、`OOMKilled=false`）→ 服务中断。
> 详见 [troubleshooting.md](troubleshooting.md) §10。

**以下纪律不可省略：**

1. **必须用独立 project 名**
   在 `.3` / `.12` 这类有实例在跑的机器上做测试，一律加 `-p <独立名字>`，例如：

   ```bash
   docker compose -f docker-compose.offline.yml -p smartx-verify-<时间戳> up -d
   ```

   物理隔离，不会碰到在跑的那套。**这是首选做法。**

2. **实在不能用独立 project 时**（验证的就是生产布局本身），
   **先完整 down/up 一次再测**，测完恢复原状。不要在运行中的实例上直接 `up`。

3. **测试目录用完即删**。事故当日残留两个测试目录各 3.4G，
   且长期滞留会持续污染现场。收工前 `docker compose -p <独立名> down -v` 并 `rm -rf` 测试目录。

4. **不要把 `.3` 当成"随便跑 compose 的构建机"**。它在某些时段是真实服务现场；
   `.14` 才是可以放手做 compose 实验的机器。

5. **`ops/package.sh` 不调用 compose**（只做镜像构建与打包），在运行中的机器上跑它是安全的。
   风险只在手工执行 `docker compose` 时。

> 曾提议加 `ops/lib/test-env.sh` 提供 `test_project_name` 辅助函数，**已否决**：
> 薄封装约束不了真正危险的场景（人在错误机器上手敲 `docker compose`），
> 反而制造「已经有防护」的错觉。改为以上纯纪律。

## 5. 验证脚本

- `scripts/verify_full_upgrade_chain.py`：v0.5.1 + runner v0.3.0 → v0.5.1u2 → runner v0.3.1 → v0.5.2 一键回归。
- `scripts/release_smoke_check.py`：只读 release canary smoke 检查。
- `scripts/capture_baseline.py`：基线产物 capture/verify 闭环。

## 6. 文档维护

- 详细执行过程、失败证据写入 `docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md`。
- 稳定问题和根因写入 `docs/upgrade-issues.md` 或对应专项 issue 文档。
- 包路径、SHA、状态写入 `docs/upgrade-package-ledger.md`。
- 计划写入 `docs/*plan*.md`、`docs/superpowers/plans/`；设计写入 `docs/superpowers/specs/`。
- 每次发布变更同步更新 `docs/releases/CHANGELOG.md`。
- 新增、移动或废弃文档时，同步更新 `docs/doc-map.md`。
