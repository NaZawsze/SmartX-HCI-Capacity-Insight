#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/smartx-storage-forecast}"
DATA_ROOT="${DATA_ROOT:-/data}"
APP_DATA_DIR="${APP_DATA_DIR:-${DATA_ROOT}/smartx-capacity-insight-data/app}"
PROMETHEUS_DATA_DIR="${PROMETHEUS_DATA_DIR:-${DATA_ROOT}/smartx-capacity-insight-data/prometheus}"
RUNTIME_DIR="${RUNTIME_DIR:-${DATA_ROOT}/compose-runtime}"
BACKUP_DIR="${BACKUP_DIR:-${DATA_ROOT}/backups}"
PROJECT_NAME="${SMARTX_COMPOSE_PROJECT_NAME:-smartx-capacity-insight}"
COMPOSE_FILE="${SMARTX_COMPOSE_FILE:-docker-compose.offline.yml}"
RUNNER_IMAGE="${RUNNER_IMAGE:-nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.2.2}"
RUNNER_VERSION="${RUNNER_VERSION:-v0.2.2}"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
BACKUP_PATH="${BACKUP_DIR}/manual-before-runner-${RUNNER_VERSION}-${TIMESTAMP}.tar.gz"
RUNNER_OVERRIDE="${RUNTIME_DIR}/docker-compose.runner-upgrade.yml"
RUNNER_COMPOSE="${RUNTIME_DIR}/docker-compose.runner-first.yml"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "请使用 root 执行：sudo $0" >&2
    exit 1
  fi
}

require_file() {
  if [ ! -f "$1" ]; then
    echo "缺少文件：$1" >&2
    exit 1
  fi
}

require_dir() {
  if [ ! -d "$1" ]; then
    echo "缺少目录：$1" >&2
    exit 1
  fi
}

backup_data() {
  log "步骤 1/3：手动备份业务库和 Prometheus 历史指标"
  require_dir "$APP_DATA_DIR"
  require_dir "$PROMETHEUS_DATA_DIR"
  mkdir -p "$BACKUP_DIR"
  tar --warning=no-file-changed \
    --exclude='smartx-capacity-insight-data/app/upgrades' \
    --exclude='smartx-capacity-insight-data/app/backups' \
    --exclude='smartx-capacity-insight-data/app/exports' \
    --exclude='smartx-capacity-insight-data/app/compose-runtime' \
    --exclude='smartx-capacity-insight-data/app/__pycache__' \
    -czf "$BACKUP_PATH" \
    -C "$DATA_ROOT" \
    smartx-capacity-insight-data/app \
    smartx-capacity-insight-data/prometheus
  log "备份完成：$BACKUP_PATH"
  sha256sum "$BACKUP_PATH" | tee "${BACKUP_PATH}.sha256"
}

prepare_runtime_dir() {
  log "准备运行时目录"
  mkdir -p "$RUNTIME_DIR" "${DATA_ROOT}/upgrades" "${DATA_ROOT}/backups" "${DATA_ROOT}/exports" "${DATA_ROOT}/compose-runtime"
  require_file "${PROJECT_ROOT}/${COMPOSE_FILE}"
  require_file "${PROJECT_ROOT}/.env"
}

cleanup_old_runner_override() {
  log "步骤 2/3：清理旧 runner override"
  if [ -f "$RUNNER_OVERRIDE" ]; then
    local backup="${RUNNER_OVERRIDE}.before-${TIMESTAMP}"
    cp -f "$RUNNER_OVERRIDE" "$backup"
    rm -f "$RUNNER_OVERRIDE"
    log "已备份并删除旧 override：$backup"
  else
    log "未发现旧 override，跳过删除"
  fi
}

install_runner_override() {
  log "步骤 3/3：安装新 runner override"
  docker image inspect "$RUNNER_IMAGE" >/dev/null
  cat > "$RUNNER_OVERRIDE" <<EOF_OVERRIDE
services:
  upgrade-runner:
    image: ${RUNNER_IMAGE}
    pull_policy: never
EOF_OVERRIDE
  cat > "$RUNNER_COMPOSE" <<EOF_COMPOSE
services:
  upgrade-runner:
    image: ${RUNNER_IMAGE}
    pull_policy: never
    command: ["python", "-m", "app.upgrade.runner"]
    env_file:
      - ${PROJECT_ROOT}/.env
    environment:
      TZ: Asia/Shanghai
      SMARTX_PROJECT_PATH: /opt/smartx-storage-forecast
      SMARTX_COMPOSE_FILE: ${COMPOSE_FILE}
      SMARTX_COMPOSE_PROJECT_NAME: ${PROJECT_NAME}
      SMARTX_RUNNER_VERSION: ${RUNNER_VERSION}
    volumes:
      - ${PROJECT_ROOT}:/opt/smartx-storage-forecast
      - ${APP_DATA_DIR}:/data
      - ${DATA_ROOT}/upgrades:/data/upgrades
      - ${DATA_ROOT}/backups:/data/backups
      - ${DATA_ROOT}/exports:/data/exports
      - ${DATA_ROOT}/compose-runtime:/data/compose-runtime
      - ${PROMETHEUS_DATA_DIR}:/prometheus-data
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - smartx-net
    restart: unless-stopped

networks:
  smartx-net:
    driver: bridge
    ipam:
      config:
        - subnet: 10.249.249.0/24
EOF_COMPOSE
  log "已写入：$RUNNER_OVERRIDE"
  log "已写入：$RUNNER_COMPOSE"
  docker compose -p "$PROJECT_NAME" -f "$RUNNER_COMPOSE" up -d --no-deps upgrade-runner
  echo "$RUNNER_VERSION" > "${APP_DATA_DIR}/upgrade-runner.version"
  log "runner 已切换到：$RUNNER_IMAGE"
}

show_next_step() {
  cat <<EOF_NEXT

准备完成。下一步：
1. 打开平台页面 -> 服务管理 -> 升级中心/系统升级。
2. 上传平台升级包，例如：/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.4.0.tar.gz。
3. 执行预检查，确认 runner 版本、compose 文件、目标镜像 tag 正常。
4. 点击开始升级。

可检查：
  docker ps --filter name=upgrade-runner
  docker logs --tail=80 ${PROJECT_NAME}-upgrade-runner-1
  cat ${APP_DATA_DIR}/upgrade-runner.version
  cat ${RUNNER_OVERRIDE}
  cat ${RUNNER_COMPOSE}

备份文件：
  ${BACKUP_PATH}
EOF_NEXT
}

main() {
  require_root
  backup_data
  prepare_runtime_dir
  cleanup_old_runner_override
  install_runner_override
  show_next_step
}

main "$@"
