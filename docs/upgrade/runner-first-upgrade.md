# Runner 优先升级现场步骤

适用场景：旧平台升级流程不稳定，或旧 `upgrade-runner` / 旧 runner override 会导致平台升级卡在备份、重启或 compose 路径阶段。推荐先手动切换到新的 runner，再从 Web 页面执行平台升级。

## 升级办法

1. 手动备份数据。
2. 清理旧 runner override。
3. 安装新 runner override 并重启 `upgrade-runner`。
4. 回到 Web 页面执行系统升级。

仓库提供脚本：

```bash
bash docs/upgrade/runner-first-upgrade.sh
```

默认参数：

```text
PROJECT_ROOT=/opt/smartx-storage-forecast
DATA_ROOT=/data
SMARTX_COMPOSE_PROJECT_NAME=smartx-capacity-insight
SMARTX_COMPOSE_FILE=docker-compose.offline.yml
RUNNER_IMAGE=nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.2.2
RUNNER_VERSION=v0.2.2
```

如果现场 runner 镜像名不同，可以覆盖：

```bash
RUNNER_IMAGE=smartx-storage-forecast-upgrade-runner:v0.2.2 \
RUNNER_VERSION=v0.2.2 \
bash docs/upgrade/runner-first-upgrade.sh
```

## 步骤解释

### 1. 手动备份数据

脚本会生成：

```text
/data/backups/manual-before-runner-v0.2.2-YYYYMMDDHHMMSS.tar.gz
/data/backups/manual-before-runner-v0.2.2-YYYYMMDDHHMMSS.tar.gz.sha256
```

备份范围包含业务库和 Prometheus 历史指标；会排除旧运行产物目录，例如 `upgrades`、`backups`、`exports`、`compose-runtime` 和 `__pycache__`。

### 2. 清理旧 runner override

旧文件路径：

```text
/data/compose-runtime/docker-compose.runner-upgrade.yml
```

如果存在，脚本会先备份为：

```text
/data/compose-runtime/docker-compose.runner-upgrade.yml.before-YYYYMMDDHHMMSS
```

然后删除旧 override，避免旧 runner 或旧挂载继续生效。

### 3. 安装新 runner override

脚本会写入两个运行时文件：

```text
/data/compose-runtime/docker-compose.runner-upgrade.yml   # 留给后续平台升级流程识别 runner 镜像
/data/compose-runtime/docker-compose.runner-first.yml     # 本脚本立即重启 runner 使用的完整 compose
```

新 runner compose 会挂载：

```text
/data/upgrades -> /data/upgrades
/data/backups -> /data/backups
/data/exports -> /data/exports
/data/compose-runtime -> /data/compose-runtime
/data/smartx-capacity-insight-data/app -> /data
/data/smartx-capacity-insight-data/prometheus -> /prometheus-data
/var/run/docker.sock -> /var/run/docker.sock
```

然后执行：

```bash
docker compose -p smartx-capacity-insight \
  -f /data/compose-runtime/docker-compose.runner-first.yml \
  up -d --no-deps upgrade-runner
```

### 4. Web 页面升级系统

准备完成后，在 Web 页面上传平台升级包，例如：

```text
/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.4.0.tar.gz
```

然后执行预检查和开始升级。

平台升级包负责升级 `web-api`、`collector-worker`、`frontend`，并同步项目文件、compose 文件和文档。`upgrade-runner` 是正在执行升级的组件，原则上不在平台升级过程中替换；需要升级 runner 时，优先走本流程或组件升级流程。

## 备选方案：重新安装新版本并命令迁出数据

如果现场旧版本升级链路已经不可信，推荐更稳的方式是：直接重新安装最新版本的存储预测平台，然后在旧系统服务器 CLI 执行数据迁出命令，把迁移包导入新系统。

在旧系统服务器上执行：

```bash
WEB_API_CONTAINER="${WEB_API_CONTAINER:-$(docker ps --format '{{.Names}}' | grep -E 'web-api' | head -n 1)}"
if [ -z "$WEB_API_CONTAINER" ]; then
  echo "未找到 web-api 容器，请手动设置 WEB_API_CONTAINER=容器名" >&2
  exit 1
fi

filename="$(
  docker exec "$WEB_API_CONTAINER" python - <<'PY'
from app.services.data_migration import build_migration_archive
_, filename = build_migration_archive(save_export=True)
print(filename)
PY
)"

export_root="$(docker inspect "$WEB_API_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/data/exports"}}{{.Source}}{{end}}{{end}}')"
if [ -z "$export_root" ]; then
  data_root="$(docker inspect "$WEB_API_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
  export_root="${data_root}/exports"
fi

host_path="${export_root}/migrations/${filename}"
ls -lh "$host_path"
sha256sum "$host_path"
```

说明：

- 不需要 `sshpass`，这条命令是在旧系统服务器本机 CLI 执行。
- 如果自动识别不到容器名，可以先执行 `docker ps`，然后手动指定 `WEB_API_CONTAINER=实际web-api容器名` 再执行命令。
- 迁移包包含业务库和 Prometheus 历史指标。
- 新系统导入完成后，需要到服务管理页重启数据服务。

## 验证命令

```bash
docker ps --filter name=upgrade-runner
cat /data/smartx-capacity-insight-data/app/upgrade-runner.version
cat /data/compose-runtime/docker-compose.runner-upgrade.yml
cat /data/compose-runtime/docker-compose.runner-first.yml
docker inspect smartx-capacity-insight-upgrade-runner-1 \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

期望看到 runner 版本为 `v0.2.2`，并且挂载包含 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`。

## 注意事项

- 执行脚本前，确保目标 runner 镜像已经存在于本机：`docker image inspect <RUNNER_IMAGE>`。
- 脚本不会自动执行平台升级，第 4 步需要在 Web 页面手动确认。
- `.env`、业务库、Prometheus 数据不会被 runner override 覆盖。
- 如果升级失败，先保留 `/data/backups/manual-before-runner-*` 和 `/data/compose-runtime/*.before-*`，不要立即删除。
