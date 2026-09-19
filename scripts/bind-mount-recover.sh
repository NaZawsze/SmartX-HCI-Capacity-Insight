#!/usr/bin/env bash
# SmartX HCI Capacity Insight — UPG-050 嵌套 bind mount 挂载点修复脚本
#
# 背景（findings.md UPG-050，2026-09-19 定案）：
#   容器创建时 dockerd 会穿过 /data（app）挂载自动补建嵌套挂载点目录，
#   宿主机侧表现为 /data/smartx-storage-forecast/app/{upgrades,backups,
#   exports,compose-runtime,smartx-storage-forecast}——它们被容器内的真实
#   bind 遮蔽，是挂载的附着载体。**运行期对它们执行 rm/mv 会把全机所有
#   容器的对应挂载一起拆掉（挂载附着在目录 inode 上）**，表现为"静默衰减"：
#   docker inspect 仍显示挂载配置（不可信），仅容器内 /proc/mounts 可判。
#   因此：这些目录不是垃圾，永远不要在容器运行时删除或改名；
#   挂载丢失时用本脚本 recover（全量先停后建）恢复。
#
# 用法（在目标宿主机上执行，需要 root）：
#   bind-mount-recover.sh check               # 只体检，不改动；挂载缺失时退出码 1
#   bind-mount-recover.sh recover             # 全量重建全部服务并验证（一键修复）
#
# 环境变量：
#   PROJECT_DIR   默认 /data/smartx-storage-forecast/project
#   COMPOSE_FILE  默认 docker-compose.offline.yml（不存在则回退 docker-compose.yml）
#   HEALTH_URL    默认 http://localhost:8080/api/system/health
#
# 注意：恢复动作会重启平台容器（约 30-60 秒中断）；不要在升级任务执行中运行。

set -u

PROJECT_DIR="${PROJECT_DIR:-/data/smartx-storage-forecast/project}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.offline.yml}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8080/api/system/health}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-smartx-hci-capacity-insight}"

MODE="${1:-recover}"

# 服务 -> 必须存在的容器内挂载目的路径（嵌套 bind 是衰减的观测点）
SERVICE_MOUNTS="
web-api:/data
web-api:/data/upgrades
web-api:/data/backups
web-api:/data/exports
web-api:/data/compose-runtime
web-api:/data/smartx-storage-forecast/project
web-api:/run/smartx-runtime.env
collector-worker:/data
collector-worker:/data/upgrades
collector-worker:/data/backups
collector-worker:/data/exports
collector-worker:/data/compose-runtime
upgrade-runner:/data
upgrade-runner:/data/upgrades
upgrade-runner:/data/backups
upgrade-runner:/data/exports
upgrade-runner:/data/compose-runtime
upgrade-runner:/data/smartx-storage-forecast/project
upgrade-runner:/prometheus-data
prometheus:/prometheus
"

container_of() {
    echo "${COMPOSE_PROJECT}-${1}-1"
}

mount_present() {
    # $1=容器名 $2=容器内挂载路径
    docker exec "$1" sh -c "grep -c \" $2 \" /proc/mounts" 2>/dev/null || echo 0
}

check_mounts() {
    local failures=0
    local service dest container count
    while IFS= read -r entry; do
        [ -z "$entry" ] && continue
        service="${entry%%:*}"
        dest="${entry#*:}"
        container="$(container_of "$service")"
        count="$(mount_present "$container" "$dest")"
        if [ "$count" -ge 1 ]; then
            echo "  [ok]   $container $dest"
        else
            echo "  [MISS] $container $dest"
            failures=$((failures + 1))
        fi
    done <<< "$SERVICE_MOUNTS"
    return "$failures"
}

check_health() {
    local payload
    payload="$(curl -fsS --max-time 10 "$HEALTH_URL" 2>/dev/null)" || return 1
    echo "$payload"
    echo "$payload" | grep -q '"ok":true'
}

do_check() {
    echo "== 挂载体检 $(date '+%F %T') =="
    local failures=0
    check_mounts || failures=$?
    echo "== 平台健康 =="
    if check_health >/dev/null 2>&1; then
        echo "  [ok]   health ok=true"
    else
        echo "  [FAIL] health 异常：$(curl -sS --max-time 10 "$HEALTH_URL" 2>/dev/null || echo unreachable)"
        failures=$((failures + 1))
    fi
    if [ "$failures" -gt 0 ]; then
        echo "== 体检失败：$failures 项（宿主 bind mount 衰减，执行 recover 修复）=="
        return 1
    fi
    echo "== 体检通过：挂载与健康全部正常 =="
}

do_recover() {
    echo "== UPG-050 恢复：全量重建全部服务（先全停后全建）$(date '+%F %T') =="
    if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
        if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
            COMPOSE_FILE="docker-compose.yml"
        else
            echo "错误：$PROJECT_DIR 下找不到 $COMPOSE_FILE / docker-compose.yml" >&2
            return 1
        fi
    fi
    # 关键：不带服务参数，全项目一次性重建；单服务重建会触发衰减扩散（findings UPG-050）
    if ! (cd "$PROJECT_DIR" && docker compose -f "$COMPOSE_FILE" up -d --force-recreate); then
        echo "错误：compose 全量重建失败" >&2
        return 1
    fi
    echo "== 等待容器就绪 =="
    sleep 12

    local attempt ok
    for attempt in 1 2 3; do
        ok=1
        check_mounts || ok=0
        if [ "$ok" -eq 1 ] && check_health >/dev/null 2>&1; then
            echo "== 恢复成功（第 $attempt 次验证）：挂载与健康全部正常 =="
            check_health
            return 0
        fi
        echo "== 第 $attempt 次验证未通过，10 秒后重试 =="
        sleep 10
    done
    echo "== 恢复失败：全量重建后挂载仍缺失，宿主 docker 环境需进一步处置 =="
    echo "   （建议顺序：systemctl restart docker 后重跑本脚本；仍失败则宿主机重启或对齐 docker 版本，见 findings.md UPG-050）"
    return 1
}

case "$MODE" in
    check)   do_check ;;
    recover) do_recover ;;
    *)
        echo "用法：$0 {check|recover}" >&2
        echo "警告：/data/smartx-storage-forecast/app/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}" >&2
        echo "      是 dockerd 补建的挂载点目录（被容器内真实 bind 遮蔽），容器运行期禁止 rm/mv，" >&2
        echo "      否则会拆掉全机对应挂载（findings.md UPG-050）。" >&2
        exit 2
        ;;
esac
