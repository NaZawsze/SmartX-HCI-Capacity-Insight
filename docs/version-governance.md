# 版本治理说明

本文档记录平台版本、upgrade-runner 组件版本、Docker 镜像 tag 和升级包的维护规则。

## 版本模型

- 平台版本由根目录 `VERSION` 定义，当前为 `v0.4.1`。
- 平台服务包括 `web-api`、`collector-worker`、`frontend`。
- `upgrade-runner` 是独立升级执行组件，版本由根目录 `RUNNER_VERSION` 定义，当前为 `v0.2.2`。
- 平台升级包不包含 `upgrade-runner`，也不重启 `upgrade-runner`。
- `upgrade-runner` 只能通过组件升级包更新。

## Docker 镜像 tag

平台服务镜像使用平台版本：

```text
nazawsze/smartx-hci-capacity-insight-web-api:v0.4.1
nazawsze/smartx-hci-capacity-insight-collector-worker:v0.4.1
nazawsze/smartx-hci-capacity-insight-frontend:v0.4.1
```

runner 组件镜像使用 runner 组件版本：

```text
nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.2.2
```

`docker-compose.offline.yml` 和 `docker-compose.release.yml` 使用两个独立变量：

```text
SMARTX_IMAGE_TAG          # 平台服务 tag，例如 v0.4.1
SMARTX_RUNNER_IMAGE_TAG   # upgrade-runner tag，例如 v0.2.2
```

## GitHub Actions

- `.github/workflows/docker-images.yml` 只构建平台三件套。
- `.github/workflows/upgrade-runner-image.yml` 只构建 `upgrade-runner`。
- runner 镜像只通过手动 workflow 或 `runner-v*` tag 构建，例如推送 `runner-v0.2.2` 后，DockerHub 镜像 tag 为 `v0.2.2`。
- 不允许 runner 跟随平台 `v*` tag 自动构建。

## 升级包规则

平台升级包由 `scripts/build_upgrade_package.py` 生成，包含：

```text
manifest.json
release-notes.md
images/web-api.tar
images/collector-worker.tar
images/frontend.tar
scripts/migrate.sh
project/**
```

组件升级包由 `scripts/build_runner_component_package.py` 生成，包含：

```text
manifest.json
release-notes.md
images/upgrade-runner.tar
```

## 发版检查清单

每次发版必须检查并更新：

- `VERSION`
- `RUNNER_VERSION`，仅 runner 组件变化时更新
- `backend/app/core/config.py` 中平台默认版本
- `docker-compose.offline.yml`
- `docker-compose.release.yml`
- `docker-compose.upgrade.yml`
- `README.md`
- `README.zh-CN.md`
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

for TAG in v0.4.1 v0.4.0 v0.3.3u2 v0.3.3U1 v0.3.3 v0.3.2 v0.3.1 main latest; do
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

