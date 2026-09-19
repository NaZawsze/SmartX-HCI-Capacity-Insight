#!/usr/bin/env bash
# SmartX HCI Capacity Insight — UPG-050 嵌套 bind mount 挂载点体检/恢复/加锁脚本
#
# 背景（findings.md UPG-050，2026-09-19 定案）：
#   容器创建时 dockerd 会穿过 /data（app）挂载自动补建嵌套挂载点目录，
#   宿主机侧表现为 /data/smartx-storage-forecast/app/{upgrades,backups,
#   exports,compose-runtime,smartx-storage-forecast}——它们被容器内的真实
#   bind 遮蔽，是挂载的附着载体。**运行期对它们执行 rm/mv 会把全机所有
#   容器的对应挂载一起拆掉（挂载附着在目录 inode 上）**，表现为"静默衰减"：
#   docker inspect 仍显示挂载配置（不可信），仅容器内 /proc/mounts 可判。
#   因此：这些目录不是垃圾，永远不要在容器运行时删除或改名；
#   挂载丢失时用本脚本 recover（自动解锁→全量重建→验证→复锁）恢复。
#
# 用法（在目标宿主机上执行，需要 root）：
#   bind-mount-recover.sh check               # 只体检，不改动；挂载缺失时退出码 1
#   bind-mount-recover.sh recover             # 自动解锁→全量重建→验证→自动复锁（一键修复）
#   bind-mount-recover.sh lock                # 对 6 个载体路径 chattr +i（幂等）
#   bind-mount-recover.sh unlock              # 对 6 个载体路径 chattr -i（幂等）
#
# 环境变量：
#   PROJECT_DIR   默认 /data/smartx-storage-forecast/project
#   COMPOSE_FILE  默认 docker-compose.offline.yml（不存在则回退 docker-compose.yml）
#   HEALTH_URL    默认 http://localhost:8080/api/system/health
#   APP_ROOT      默认 /data/smartx-storage-forecast/app
#
# 锁的边界（设计文档 docs/superpowers/specs/2026-09-20-upg050-carrier-lock-and-prepare-skeleton-design.md）：
#   锁只保护 6 个挂载载体目录；app/ 本身（SQLite WAL 需建文件）与
#   真实数据目录刻意不锁；锁防误删载体，不防删库。
#
# 注意：recover 会重启平台容器（约 30-60 秒中断）；不要在升级任务执行中运行。

set -u

PROJECT_DIR="${PROJECT_DIR:-/data/smartx-storage-forecast/project}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.offline.yml}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8080/api/system/health}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-smartx-hci-capacity-insight}"
APP_ROOT="${APP_ROOT:-/data/smartx-storage-forecast/app}"

MODE="${1:-recover}"

# UPG-050 挂载载体路径（挂载附着点；运行期 rm/mv = 拆全机挂载）
LOCK_PATHS=(
    "$APP_ROOT/upgrades"
    "$APP_ROOT/backups"
    "$APP_ROOT/exports"
    "$APP_ROOT/compose-runtime"
    "$APP_ROOT/smartx-storage-forecast"
    "$APP_ROOT/smartx-storage-forecast/project"
)

warn_upg050() {
    echo "警告：$APP_ROOT/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}" >&2
    echo "      是 dockerd 补建的挂载点目录（被容器内真实 bind 遮蔽），容器运行期禁止 rm/mv，" >&2
    echo "      否则会拆掉全机对应挂载（findings.md UPG-050）。" >&2
}

# $1=路径；退出码 0=已锁(+i) 1=未锁 2=lsattr 失败（路径异常/缺失）
attr_has_i() {
    local out
    if ! out="$(lsattr -d "$1" 2>/dev/null)"; then
        return 2
    fi
    case "${out%% *}" in
        *i*) return 0 ;;
        *)   return 1 ;;
    esac
}

# chattr +i 语义仅验证过 ext4/xfs；其他文件系统报错退出（该机不加锁并记录）
fs_supports_chattr() {
    local fstype
    fstype="$(stat -f -c %T "$APP_ROOT" 2>/dev/null)" || {
        echo "错误：无法探测 $APP_ROOT 文件系统类型，不加锁" >&2
        return 1
    }
    case "$fstype" in
        ext2/ext3/ext4|xfs) return 0 ;;
        *)
            echo "错误：$APP_ROOT 文件系统为 $fstype，chattr +i 语义未验证；该机不加锁（记录原因后终止）" >&2
            return 1
            ;;
    esac
}

do_lock() {
    echo "== UPG-050 载体目录加锁 $(date '+%F %T') =="
    warn_upg050
    fs_supports_chattr || return 1
    local failures=0 path state
    for path in "${LOCK_PATHS[@]}"; do
        if [ ! -d "$path" ]; then
            if ! mkdir -p "$path"; then
                echo "  [FAIL] $path 目录缺失且创建失败" >&2
                failures=$((failures + 1))
                continue
            fi
        fi
        attr_has_i "$path"
        state=$?
        if [ "$state" -eq 0 ]; then
            echo "  [already] $path"
            continue
        fi
        if [ "$state" -eq 2 ]; then
            echo "  [FAIL] $path lsattr 失败（路径异常？）" >&2
            failures=$((failures + 1))
            continue
        fi
        if chattr +i "$path" 2>/dev/null; then
            echo "  [locked] $path"
        else
            echo "  [FAIL] $path chattr +i 失败" >&2
            failures=$((failures + 1))
        fi
    done
    if [ "$failures" -gt 0 ]; then
        echo "== 加锁失败：$failures 项（未锁路径仍可被 rm/mv 误删）==" >&2
        return 1
    fi
    echo "== 加锁完成：载体路径全部 +i（unlock 可解锁；recover 会自动解锁/复锁）=="
}

do_unlock() {
    echo "== UPG-050 载体目录解锁 $(date '+%F %T') =="
    local failures=0 path state
    for path in "${LOCK_PATHS[@]}"; do
        attr_has_i "$path"
        state=$?
        if [ "$state" -ne 0 ]; then
            # 1=未锁；2=lsattr 失败（目录多半不存在）——均无锁可解
            echo "  [not-locked] $path"
            continue
        fi
        if chattr -i "$path" 2>/dev/null; then
            echo "  [unlocked] $path"
        else
            echo "  [FAIL] $path chattr -i 失败" >&2
            failures=$((failures + 1))
        fi
    done
    if [ "$failures" -gt 0 ]; then
        echo "== 解锁失败：$failures 项 ==" >&2
        return 1
    fi
    echo "== 解锁完成 =="
}

report_lock_status() {
    local path state locked=0 total=0
    echo "== 载体目录锁状态（UPG-050）=="
    for path in "${LOCK_PATHS[@]}"; do
        total=$((total + 1))
        attr_has_i "$path"
        state=$?
        if [ "$state" -eq 0 ]; then
            echo "  [locked]   $path"
            locked=$((locked + 1))
        elif [ "$state" -eq 2 ]; then
            echo "  [missing]  $path（lsattr 失败）"
        else
            echo "  [unlocked] $path"
        fi
    done
    echo "  （$locked/$total 已锁定；加锁：$0 lock，解锁：$0 unlock）"
}

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
    report_lock_status
    if [ "$failures" -gt 0 ]; then
        echo "== 体检失败：$failures 项（宿主 bind mount 衰减，执行 recover 修复）=="
        return 1
    fi
    echo "== 体检通过：挂载与健康全部正常 =="
}

do_recover() {
    echo "== UPG-050 恢复：自动解锁→全量重建→验证→复锁 $(date '+%F %T') =="
    warn_upg050
    if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
        if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
            COMPOSE_FILE="docker-compose.yml"
        else
            echo "错误：$PROJECT_DIR 下找不到 $COMPOSE_FILE / docker-compose.yml" >&2
            return 1
        fi
    fi
    # 锁定状态下先自动解锁；复锁只在恢复验证通过后执行，失败保持解锁并大声提示
    local was_locked=0 path
    for path in "${LOCK_PATHS[@]}"; do
        if attr_has_i "$path"; then
            was_locked=1
            break
        fi
    done
    if [ "$was_locked" -eq 1 ]; then
        echo "== 检测到载体目录带锁，自动解锁（验证通过后自动复锁）=="
        if ! do_unlock; then
            echo "错误：自动解锁失败，中止恢复（请手工 unlock 后重试）" >&2
            return 1
        fi
    fi
    # 关键：不带服务参数，全项目一次性重建；单服务重建会触发衰减扩散（findings UPG-050）
    if ! (cd "$PROJECT_DIR" && docker compose -f "$COMPOSE_FILE" up -d --force-recreate); then
        echo "错误：compose 全量重建失败" >&2
        if [ "$was_locked" -eq 1 ]; then
            echo "注意：载体目录已解锁（恢复未成功不自动复锁）；修复后重跑 recover 或手工 lock" >&2
        fi
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
            if [ "$was_locked" -eq 1 ]; then
                echo "== 恢复验证通过，自动复锁 =="
                if ! do_lock; then
                    echo "错误：自动复锁失败——平台已恢复但载体目录处于未锁状态，请手工执行 $0 lock" >&2
                    return 1
                fi
                echo "== 恢复完成且锁定状态保持 =="
            fi
            return 0
        fi
        echo "== 第 $attempt 次验证未通过，10 秒后重试 =="
        sleep 10
    done
    echo "== 恢复失败：全量重建后挂载仍缺失，宿主 docker 环境需进一步处置 =="
    echo "   （建议顺序：systemctl restart docker 后重跑本脚本；仍失败则宿主机重启或对齐 docker 版本，见 findings.md UPG-050）"
    if [ "$was_locked" -eq 1 ]; then
        echo "   注意：载体目录当前为解锁状态（恢复未成功不自动复锁）；处置完成后再跑 recover 或手工 lock" >&2
    fi
    return 1
}

case "$MODE" in
    check)   do_check ;;
    recover) do_recover ;;
    lock)    do_lock ;;
    unlock)  do_unlock ;;
    *)
        echo "用法：$0 {check|recover|lock|unlock}" >&2
        warn_upg050
        exit 2
        ;;
esac
