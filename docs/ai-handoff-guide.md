# AI 交接执行手册（接手待办任务前必读）

更新时间：2026-09-19
用途：本项目的待办任务（见 [pending-tasks.md](pending-tasks.md)）可能交给不同的 AI 会话实施。本文档是交接执行的总纲——执行环境、流程、基线、陷阱。**三份待实施设计文档（49-13/49-14/49-15）都假设你已读完本文。**

## 1. 入口与必读顺序

1. [AGENTS.md](../AGENTS.md)（仓库根目录）：协作标准、三台服务器边界、提交策略。**含测试机登录方式**（本地文件，不在 git 里）。
2. [docs/doc-map.md](doc-map.md)：全文档地图。
3. [docs/pending-tasks.md](pending-tasks.md)：任务队列与各设计文档链接。
4. 你要实施任务的设计文档（superpowers/specs/ 下，链接在 pending-tasks 各行）。

## 2. 提交策略（2026-09-13 起生效，必须遵守）

- **dev2 默认只在本地提交**。推送到 origin（GitHub）必须由用户明确要求——不要因为"流程惯例"而推送。
- 向测试机 .3 同步代码**不依赖推送**（.3 项目目录不是 git 检出）：
  ```bash
  git archive --format=tar.gz -o /tmp/dev2-<short>.tar.gz dev2
  scp /tmp/dev2-<short>.tar.gz user1@10.20.11.3:/home/user1/
  # .3 上（root）解压：tar -xzf /home/user1/dev2-<short>.tar.gz -C /data/smartx-storage-forecast/project
  ```
- 每个任务独立提交；设计文档与实现分开提交。

## 3. 测试机 .3 操作要点

- 登录：`ssh user1@10.20.11.3`（密码见 AGENTS.md），docker/root 操作需 `su - root`——su 需要 tty，用 `python3 pty` 脚本或把多步命令写成 shell 脚本 scp 过去再执行（**引号嵌套超过两层必然出错，用脚本文件**）。
- user1 不在 sudoers/docker 组；root 已禁用 SSH 直登。
- 部署标准步骤（在 /data/smartx-storage-forecast/project）：
  ```bash
  tar -xzf /home/user1/<pkg>.tar.gz -C /data/smartx-storage-forecast/project
  docker compose build web-api collector-worker frontend [upgrade-runner]
  docker compose up -d web-api collector-worker frontend [upgrade-runner]
  sleep 10
  curl -fsS http://127.0.0.1:8000/api/system/health
  curl -fsSI http://127.0.0.1:8080 | head -n 1
  ```
- **tar 解压不会删除归档中不存在的文件**。删除型变更部署后，必须手工清理 .3 上的残留文件（否则残留文件参与测试/构建产生假错误）。

## 4. 验证基线与已知陷阱（勿追幽灵）

### 测试基线

- 本地（macOS，python3.9，无 fastapi/apscheduler/cryptography/pytest）：部分测试**环境跳过或报 ModuleNotFoundError** 属正常——fastapi 依赖的测试已加 skipTest。
- .3 容器内全量：**386 tests 全绿**（2026-09-27 起；此前时点：2026-09-19 为 310、2026-09-13 为 308；`skipped=2` 为环境条件跳过）。构建测试 `test_v2_package_builders` 已移到 `backend/build_tests/`（需写项目根 VERSION，web-api 容器只读挂载，改在宿主机跑 26 tests OK）；`test_deployment_config` 已改 unittest（无 pytest 依赖）。**任何失败都是真回归。**
- 容器内跑法：
  ```bash
  docker compose exec -T web-api sh -lc "cd /data/smartx-storage-forecast/project/backend && PYTHONPATH=/data/smartx-storage-forecast/project/backend python -m unittest discover -s tests 2>&1 | tail -3"
  ```
- 前端：node:22-alpine 容器内 `npm install && npm test -- --run <files>`；构建（tsc）在 Dockerfile 内，构建失败会输出 error TS。

### 陷阱清单（全部真实踩过）

| 陷阱 | 后果 | 规避 |
| --- | --- | --- |
| `docker compose build \| tail -1` / grep 过滤 | 构建失败被吞，`up -d` 显示 Running（未重建），旧代码继续跑 | 看完整构建输出；tsc 前端用 `npx tsc -b` 显式检查；必要时 `up -d --force-recreate` |
| `docker compose restart` | 不换镜像，跑的还是旧代码 | 部署新代码必须 build + `up -d`（镜像变化才会重建） |
| tar 解压 | 不删除已不存在的旧文件 | 删除型变更后手工清理 .3 残留 |
| 本地 python3.9 | 缺 fastapi/apscheduler/cryptography/pytest | 相关测试已加 skipTest；不要"修复"这些跳过 |
| 远程命令引号嵌套（ssh → su → sh） | 引号被吃、命令损坏 | 多步操作写成脚本文件 scp 过去执行 |
| `.env` 权限 600 且属 root | user1 跑 `docker compose` 读 .env 失败 | 一律 su root 执行 compose 命令 |
| unittest.TestCase 里定义 `_outcome` 等框架内部名 | 被框架覆盖，报诡异 TypeError | 避免框架保留名 |
| 业务库路径 | 真库在 `/data/smartx-storage-forecast/app/smartx.db`（容器内 /data/smartx.db）；宿主机 `/data/smartx.db` 是 v0.5.1 旧残留（无业务表） | 操作前核对路径 |
| 容器运行期 rm/mv `app/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}` | 这些是 dockerd 补建的挂载点载体，删/移即拆掉全机容器的对应挂载（UPG-050） | 运行期禁删禁移；衰减后全服务 `docker compose up -d --force-recreate` 恢复，用 `scripts/bind-mount-recover.sh` 体检 |
| GitHub push 偶发被代理拦截 | push 失败 | 重试即可；本地提交不丢 |

### 版本事实

- 平台 v0.5.3（**候选，尚未发布**；已正式发布 v0.5.2）/ 已发布 runner v0.3.1（仓库开发线已 bump 到 v0.3.2，尚无 tag/镜像/组件包资产交付）/ 分支 dev2（当前本地领先 origin，推送需用户要求）。
- **compose 镜像 tag 已字面量化**：三个源码 compose 直接写死 `v0.5.3` / `v0.3.2` / `v2.55.1` 字面量（49-3，2026-09-20），`check_versions` 门禁做字面量断言并**禁止模板变量回潮**——不要再引入 `${SMARTX_IMAGE_TAG:-…}` 这类占位符，会被门禁直接判失败。历史教训见 p1-infra-batch-design §5。
- `CollectionService.run_manual_collection` 落库前**已在内部与采集前的旧快照合并**（49-37，2026-09-25 起）：失败/被过滤目标沿用最后已知样本，任何调用路径（含 API 手动采集）都不会再整体替换 `metric_snapshots` 抹掉历史样本；worker 外层的 `merge` 保留为双保险（幂等）。新增采集路径无需再自行合并。

## 5. 流程要求

- 设计先行：task_plan 立项 → specs/ 设计（本文档假设已读）→ 实施 → 本地提交 → .3 验证 → 回填勾选 + progress.md 证据。
- 测试基线外的新失败：先停下记录根因，禁止静默重试。
- 完成判定必须有 .3 实际验证输出，"应该没问题"不算。

## 6. 近期设计实施状态（49-13~49-16 均已完成）

| 任务 | 设计文档 | 备注 |
| --- | --- | --- |
| 49-13 拆分巨型文件 | [specs/2026-09-13-split-giant-files-design.md](superpowers/specs/2026-09-13-split-giant-files-design.md)（含附录 A 函数映射清单） | ✅ 已完成（2026-09-13，api.py/ServicePage/export.py/upgrade/service.py 四项独立提交+部署，回归零新增） |
| 49-14 API 响应模型 | [specs/2026-09-13-api-response-models-design.md](superpowers/specs/2026-09-13-api-response-models-design.md)（含附录 B 契约脚本规格） | ✅ 已完成（五批响应模型落地） |
| 49-15 compose 字面量 tag | [specs/2026-09-13-compose-literal-tags-design.md](superpowers/specs/2026-09-13-compose-literal-tags-design.md) | ✅ 已完成（2026-09-13，见 progress.md） |
| 49-16 前后端契约对齐 | [specs/2026-09-13-contract-alignment-design.md](superpowers/specs/2026-09-13-contract-alignment-design.md) | ✅ 已完成（2026-09-13：后端补发 kpis/latest_run/top_vms/tower_runs + item metric/value，前端删 normalizer） |

> 以上四项均已完成（2026-09-13~19，见 progress.md）；当前待办以 [pending-tasks.md](pending-tasks.md) 为准。
