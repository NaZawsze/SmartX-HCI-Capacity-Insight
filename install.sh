#!/usr/bin/env bash
# 统一一键安装（离线 / 在线）：SmartX HCI Capacity Insight
#
# 一个脚本、两种模式（Phase 86，设计 docs/superpowers/specs/2026-10-22-install-entry-unification-design.md）：
#   · 离线（交付包默认）：镜像来自脚本旁 images/（交付包自含）或 --images <tar 目录>（传 tar 场景）
#   · 在线（仓库形态默认）：按 compose 声明的 tag 从 DockerHub 拉取
#
# 原则（失败即停，不留半成品）：
#   · 任一步失败 → 打印已完成到哪一步 + 补救命令，**绝不启动半套服务**
#   · 不删除已加载的镜像（无害），但也不"回滚"宿主上其它内容
#   · 密钥由本脚本生成，**不打印明文**，不写进交付物
#
set -Eeuo pipefail

# 任何"静默退出"都是最难排查的失败模式（用户只看到脚本没了、没有原因）。
# 装一个陷阱：命令失败时打印行号与退出码，再由调用方决定如何提示。
LAST_ERROR_LINE=""
trap 'rc=$?; if [ $rc -ne 0 ] && [ -n "${BASH_COMMAND:-}" ]; then
  printf "\n"
  c_red "  [XX] 内部错误：第 ${BASH_LINENO[0]} 行命令失败（退出码 ${rc}）"
  printf "       命令：%s\n" "$BASH_COMMAND"
  printf "       当前步骤：%s\n" "${CURRENT_STEP_NAME:-（未记录）}"
fi' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# US-37：加载 compose 变体守卫。守卫自包含，不依赖 lib/。
# 交付包形态 = 脚本旁 compose-guard.sh；仓库形态 = delivery/compose-guard.sh。
if [ -f "$SCRIPT_DIR/compose-guard.sh" ]; then
  COMPOSE_GUARD="$SCRIPT_DIR/compose-guard.sh"
  . "$COMPOSE_GUARD"
elif [ -f "$SCRIPT_DIR/delivery/compose-guard.sh" ]; then
  COMPOSE_GUARD="$SCRIPT_DIR/delivery/compose-guard.sh"
  . "$COMPOSE_GUARD"
else
  COMPOSE_GUARD=""
fi

# ---- 默认值（可由命令行覆盖）----
INSTALL_ROOT="/data/smartx-storage-forecast"
ADMIN_USER="admin"
ADMIN_PASSWORD="password"
TOWER_URL=""
TOWER_USER=""
TOWER_PASSWORD=""
ASSUME_YES=0
FORCE_ENV=0
FORCE_COMPOSE_SWITCH=0
HEALTH_TIMEOUT=180
DISK_HEADROOM_GIB=10

COMPOSE_PROJECT="smartx-hci-capacity-insight"
COMPOSE_FILE_OFFLINE="docker-compose.offline.yml"
COMPOSE_FILE_ONLINE="docker-compose.online.yml"
COMPOSE_FILE="$COMPOSE_FILE_OFFLINE"   # detect_resources() 按 --mode 重设
MODE_REQUESTED="auto"                  # auto|online|offline
IMAGES_ARG=""                          # --images <目录>
PROMETHEUS_UID="${PROMETHEUS_UID:-65534}"
PROMETHEUS_GID="${PROMETHEUS_GID:-65534}"

# ---- 输出helpers ----
STEP=0
COMPLETED_STEPS=()
# 总步数 = step 调用数（含 US-37 的「记录生效的 compose 变体」）；
# detect_resources() 会按 --mode 重设（offline=11 / online=10）。
TOTAL_STEPS=11
c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
info()  { printf '     %s\n' "$*"; }
ok()    { c_green "  [OK] $*"; }
warn()  { c_yellow "  [!!] $*"; }
fail()  { c_red "  [XX] $*"; }

step() {
  STEP=$((STEP + 1))
  CURRENT_STEP_NAME="$1"
  printf '\n%s\n' "─── 步骤 ${STEP}/${TOTAL_STEPS}：$1 ─────────────────────────────────────────"
}
mark_done() { COMPLETED_STEPS+=("$1"); }

die() {
  fail "$1"
  printf '\n'
  c_red "安装未完成，已停在：$1"
  printf '\n当前进度与补救建议：\n'
  if [ "${#COMPLETED_STEPS[@]}" -eq 0 ]; then
    printf '  （尚未完成任何步骤，宿主环境未被修改，可直接修正后重跑）\n'
  else
    for done in "${COMPLETED_STEPS[@]}"; do
      printf '  [已完成] %s\n' "$done"
    done
  fi
  if [ -n "${DIE_HINT:-}" ]; then
    printf '\n%s\n' "$DIE_HINT"
  fi
  printf '\n重新运行本脚本即可（已完成的步骤会自动跳过或安全覆盖）。\n'
  exit 1
}

usage() {
  cat <<'USAGE'
一键安装（离线 / 在线）· SmartX HCI Capacity Insight

用法:
  sudo bash install.sh [选项]

安装模式（--mode，默认 auto 自动判定）:
  auto      交付包形态（脚本旁有 images/）→ 离线；否则 → 在线（docker pull）
  offline   离线安装：镜像来自交付包 images/ 或 --images <目录>（传 tar 场景）
  online    在线安装：按 compose 声明的 tag 从 DockerHub 拉取

选项:
  --mode <auto|online|offline>  安装模式（默认 auto）
  --images <目录>               离线安装的镜像归档目录（含 *.tar 与 SHA256SUMS）；
                                缺省用脚本旁 images/（交付包形态才存在）
  --install-root <路径>     数据根目录（默认 /data/smartx-storage-forecast）
  --admin-user <用户名>     管理员用户名（默认 admin）
  --admin-password <口令>   管理员初始口令（默认 password）
  --tower-url <地址>        CloudTower 地址（可选，写入 .env 便于首次配置）
  --tower-user <账号>       CloudTower 账号（可选）
  --tower-password <口令>   CloudTower 口令（可选）
  --health-timeout <秒>     健康检查超时（默认 180）
  --yes                     非交互模式（跳过确认）
  --force-env               已存在 .env 时重新生成（默认不覆盖）
  --force-compose-switch    确认要把实例换成另一份 compose 变体。
                            会**先完整停机（down）再启动**，造成计划内中断。
                            不加此参数时，若 .env 记录的 compose 与本脚本使用的
                            不一致，将直接拒绝执行（防服务被 recreate 掉）。
  -h, --help                显示本帮助

示例:
  # 交付包安装（交互确认；进入交付目录后执行）
  bash install/install.sh

  # 自装机在线安装（从仓库 clone 后执行；镜像自动 pull）
  sudo bash install.sh --yes

  # 只有镜像 tar 的离线安装（不能 clone、又不能出网的场景）
  sudo bash install.sh --mode offline --images /path/to/tars --yes

  # 批量/涉密场景，非交互
  bash install/install.sh --yes --tower-url https://tower.example.com

注意:
  · 必须以 root 运行
  · 脚本只操作部署目录与平台标准路径，不会清理宿主上的其它内容
  · 首次登录后请立即在 Web 界面修改管理员口令
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mode)           MODE_REQUESTED="${2:?}"; shift 2 ;;
    --images)         IMAGES_ARG="${2:?}"; shift 2 ;;
    --install-root)   INSTALL_ROOT="${2:?}"; shift 2 ;;
    --admin-user)     ADMIN_USER="${2:?}"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="${2:?}"; shift 2 ;;
    --tower-url)      TOWER_URL="${2:?}"; shift 2 ;;
    --tower-user)     TOWER_USER="${2:?}"; shift 2 ;;
    --tower-password) TOWER_PASSWORD="${2:?}"; shift 2 ;;
    --health-timeout) HEALTH_TIMEOUT="${2:?}"; shift 2 ;;
    --yes|-y)         ASSUME_YES=1; shift ;;
    --force-env)      FORCE_ENV=1; shift ;;
    --force-compose-switch) FORCE_COMPOSE_SWITCH=1; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) fail "未知选项：$1"; usage; exit 1 ;;
  esac
done

# ══════════════════════════════════════════════════════════════
# 形态判定与资源解析（Phase 86 统一安装器）
# 三种情景共用一个脚本：交付包形态 / 仓库形态（clone 或 git archive）/ 传 tar 场景
# ══════════════════════════════════════════════════════════════
detect_resources() {
  # 镜像目录（离线模式必需）
  if [ -n "$IMAGES_ARG" ]; then
    [ -d "$IMAGES_ARG" ] || die "指定的镜像目录不存在：$IMAGES_ARG" \
      "请给 --images <包含 *.tar 的目录>；或去掉 --mode auto 让脚本按环境判定。服务**未**启动。"
    IMAGES_DIR="$IMAGES_ARG"
  elif [ -d "$SCRIPT_DIR/images" ]; then
    IMAGES_DIR="$SCRIPT_DIR/images"
  else
    IMAGES_DIR=""
  fi

  # 形态：仓库（脚本根含 compose 源）优先于交付包（脚本旁 project/）
  if [ -f "$SCRIPT_DIR/$COMPOSE_FILE_OFFLINE" ]; then
    SHAPE="repo"
    PROJECT_SRC="$SCRIPT_DIR"
  elif [ -d "$SCRIPT_DIR/project" ]; then
    SHAPE="delivery"
    PROJECT_SRC="$SCRIPT_DIR/project"
  else
    die "无法识别安装环境（既不是仓库形态也不是交付包形态）" \
      "  在线安装：在本仓库根执行本脚本（需要 docker-compose.offline.yml / docker-compose.online.yml）。
  离线安装：使用交付包（install/ 目录，自带 images/ 与 project/），
  或加 --mode offline --images <tar 目录> 并确保脚本旁有完整部署文件。
  服务**未**启动，宿主环境未被修改。"
  fi

  # 模式
  case "$MODE_REQUESTED" in
    auto)
      if [ -n "$IMAGES_DIR" ]; then MODE="offline"; else MODE="online"; fi
      ;;
    offline|online) MODE="$MODE_REQUESTED" ;;
    *) die "未知安装模式：$MODE_REQUESTED" "可用 --mode auto（默认）/ online / offline。服务**未**启动。" ;;
  esac

  if [ "$MODE" = "online" ]; then
    COMPOSE_FILE="$COMPOSE_FILE_ONLINE"
    TOTAL_STEPS=10
  else
    COMPOSE_FILE="$COMPOSE_FILE_OFFLINE"
    TOTAL_STEPS=11
  fi

  # .env 模板：交付包 = .env.template；仓库 = .env.example（占位符换成 __GENERATE__）
  if [ -f "$SCRIPT_DIR/.env.template" ]; then
    ENV_TEMPLATE="$SCRIPT_DIR/.env.template"
    ENV_TEMPLATE_SOURCE=""
  elif [ -f "$SCRIPT_DIR/.env.example" ]; then
    ENV_TEMPLATE=""
    ENV_TEMPLATE_SOURCE="$SCRIPT_DIR/.env.example"
  else
    die "找不到 .env 模板（交付包应有 .env.template；仓库应有 .env.example）" \
      "请确认脚本所在目录完整（当前：${SCRIPT_DIR}）。服务**未**启动。"
  fi

  case "$SHAPE:$MODE" in
    delivery:offline) info "安装模式：离线（交付包自含镜像 ${IMAGES_DIR}）" ;;
    delivery:online)  info "安装模式：在线（交付形态 + docker pull，现场需能访问镜像仓库）" ;;
    repo:offline)     info "安装模式：离线（外部镜像目录 ${IMAGES_DIR}）" ;;
    repo:online)      info "安装模式：在线（docker pull，现场需能访问 docker.io）" ;;
  esac
}

detect_resources

PROJECT_DIR="$INSTALL_ROOT/project"
ENV_FILE="$PROJECT_DIR/.env"
COMPOSE_PATH="$PROJECT_DIR/$COMPOSE_FILE"

# ══════════════════════════════════════════════════════════════
step "前置检查"
# ══════════════════════════════════════════════════════════════
[ "$(id -u)" = "0" ] || die "必须以 root 运行（当前 uid=$(id -u)）" "请用：sudo bash install.sh"
command -v docker >/dev/null 2>&1 || die "未找到 docker" "请先安装 Docker Engine 20.10+，并确认 systemctl status docker 正常。"
docker compose version >/dev/null 2>&1 || die "docker compose 不可用（需要 Compose V2 插件）" "请安装 docker-compose-plugin。"
docker info >/dev/null 2>&1 || die "docker 守护进程未运行或当前用户无权限" "请确认：systemctl start docker"
[ -d "$PROJECT_SRC" ] || die "找不到部署文件目录：$PROJECT_SRC" "请确认脚本所在目录完整（交付包 = install/project/；仓库 = 仓库根）。"
[ -f "$PROJECT_SRC/$COMPOSE_FILE" ] || die "找不到 compose 文件：$PROJECT_SRC/$COMPOSE_FILE" \
  "仓库应有 docker-compose.offline.yml 与 docker-compose.online.yml；交付包 install/project/ 应有对应文件。"
if [ "$MODE" = "offline" ]; then
  [ -n "$IMAGES_DIR" ] || die "离线安装未指定镜像目录" \
    "交付包形态自带 install/images/；仓库/传 tar 场景请加 --images <含 *.tar 的目录>，或改用 --mode online 在线拉取。"
fi
ok "root 权限 / docker / 部署文件就绪（${SHAPE} / ${MODE}）"

# 磁盘：镜像总和 ×3 + 余量（解包 + 加载 + 运行都需要空间）
# 注意：--install-root 指向的目录此时**可能还不存在**，`df` 会失败并返回空，
# 必须在 set -e 下显式兜底，否则会静默退出（无任何提示，最难排查的一类失败）。
avail_bytes_of() {
  local target="$1"
  # 注意 set -u：必须先给 out 赋空值，否则"目录不存在"分支里引用未定义变量会报
  # unbound variable（而这恰恰是最常见的路径——install-root 通常还没建）
  local out=""
  if [ -d "$target" ]; then
    out="$(df -PB1 "$target" 2>/dev/null | awk 'END {print $4}')"
  fi
  if [ -z "$out" ]; then
    # 逐级向上找最近存在的祖先目录
    local probe="$target"
    while [ -n "$probe" ] && [ "$probe" != "/" ]; do
      probe="$(dirname "$probe")"
      if [ -d "$probe" ]; then
        out="$(df -PB1 "$probe" 2>/dev/null | awk 'END {print $4}')"
        [ -n "$out" ] && break
      fi
    done
  fi
  if [ -z "$out" ]; then
    out="$(df -PB1 / 2>/dev/null | awk 'END {print $4}')"
  fi
  printf '%s' "${out:-0}"
}

if command -v du >/dev/null 2>&1 && command -v df >/dev/null 2>&1; then
  if [ "$MODE" = "offline" ]; then
    IMAGES_BYTES="$(du -sb "$IMAGES_DIR" 2>/dev/null | awk 'END {print $1}')"
    IMAGES_BYTES="${IMAGES_BYTES:-0}"
    NEED_GIB=$(( IMAGES_BYTES * 3 / 1024 / 1024 / 1024 + DISK_HEADROOM_GIB ))
    NEED_DESC="（离线：镜像 ${IMAGES_BYTES} 字节的 3 倍 + ${DISK_HEADROOM_GIB} GiB 余量）"
  else
    NEED_GIB=15
    NEED_DESC="（在线：按镜像与数据经验值估算）"
  fi
  AVAIL_BYTES="$(avail_bytes_of "$INSTALL_ROOT")"
  AVAIL_GIB=$(( AVAIL_BYTES / 1024 / 1024 / 1024 ))
  if [ "$AVAIL_BYTES" -lt $(( NEED_GIB * 1024 * 1024 * 1024 )) ]; then
    DIE_HINT="  磁盘可用 ${AVAIL_GIB} GiB < 需要约 ${NEED_GIB} GiB ${NEED_DESC}
  清理磁盘或用 --install-root 指定容量更大的已存在目录后重跑。
  服务**未**启动，宿主环境未被修改。"
    die "磁盘空间不足" "$DIE_HINT"
  fi
  ok "磁盘可用 ${AVAIL_GIB} GiB（需要约 ${NEED_GIB} GiB）"
fi

# 端口占用：8000/8080/9090 是对外服务端口
PORT_PROBE_TOOL=""
port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    PORT_PROBE_TOOL="ss"
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$" && return 0
  elif command -v netstat >/dev/null 2>&1; then
    PORT_PROBE_TOOL="netstat"
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$" && return 0
  else
    # 两者都没有：不能假装端口空闲（会在 compose up 时才炸，且信息更少）
    PORT_PROBE_TOOL="none"
    return 1
  fi
  return 1
}
BUSY_PORTS=""
for port in 8000 8080 9090; do
  if port_in_use "$port"; then BUSY_PORTS="$BUSY_PORTS $port"; fi
done
if [ -n "$BUSY_PORTS" ]; then
  # 已安装过的实例自己占着端口是正常的（下面幂等检查会先拦），这里只提示
  warn "以下端口已被占用：$BUSY_PORTS"
  if [ ! -f "$ENV_FILE" ]; then
    DIE_HINT="  这些端口必须空闲（8000=web-api，8080=前端，9090=Prometheus）。
  请先停止占用它们的服务，或修改 compose 中的端口映射后重跑。
  服务**未**启动，宿主环境未被修改。"
    die "端口被占用" "$DIE_HINT"
  fi
fi
if [ "$PORT_PROBE_TOOL" = "none" ]; then
  warn "系统既无 ss 也无 netstat，无法预检端口占用"
  info "若 8000/8080/9090 已被占用，compose 启动时会报错，届时按步骤 8 的诊断处理。"
fi
mark_done "前置检查"
ok "前置检查通过"

# ══════════════════════════════════════════════════════════════
step "记录生效的 compose 变体（US-37）"
# ══════════════════════════════════════════════════════════════
# .env 里的 SMARTX_COMPOSE_FILE_ACTIVE 是「这个实例用哪份 compose 起」的唯一事实源，
# 供 compose-guard.sh 在后续任何 up/down/restart 前拦截误用别的变体。
#
# 必须放在幂等检查**之前**：已有安装时本脚本会在下面直接 exit 0，
# 放到之后就永远补不上标记——而那恰恰是最需要守卫的现场（2026-09-30 .3 事故）。
# 注意必须用 declare -F 验证**函数**存在：守卫加载的是函数不是变量，
# 写成 ${compose_guard_resolve:-} 恒为空、整个分支永远不执行（.14 实测踩坑）。
if [ -f "$ENV_FILE" ] && declare -F compose_guard_resolve >/dev/null; then
  RESOLVED_COMPOSE="$(compose_guard_resolve "$ENV_FILE" "$COMPOSE_PROJECT" "$COMPOSE_FILE")"
  ok "生效 compose 变体：${RESOLVED_COMPOSE}"
  mark_done "记录生效的 compose 变体"
fi

# ══════════════════════════════════════════════════════════════
step "幂等检查：是否已安装"
# ══════════════════════════════════════════════════════════════
if [ -f "$ENV_FILE" ] && [ "$FORCE_ENV" -eq 0 ]; then
  c_yellow "已检测到安装：$ENV_FILE"
  info "本次不做任何修改。如需重新生成 .env，请加 --force-env；"
  info "如需完全卸载，请参考部署文档的「卸载」章节（数据不可恢复）。"
  exit 0
fi
ok "未检测到已有安装（.env 不存在）"

if [ "$MODE" = "offline" ]; then
  # ══════════════════════════════════════════════════════════════
  step "校验镜像完整性"
  # ══════════════════════════════════════════════════════════════
  if [ ! -f "$IMAGES_DIR/SHA256SUMS" ]; then
    die "缺少校验文件：$IMAGES_DIR/SHA256SUMS" "交付目录不完整，请重新获取交付包。"
  fi
  if (cd "$IMAGES_DIR" && sha256sum -c SHA256SUMS >/dev/null 2>&1); then
    ok "全部镜像校验通过"
  else
    c_red "镜像校验失败："
    (cd "$IMAGES_DIR" && sha256sum -c SHA256SUMS 2>&1 | grep -vE ': OK$' | head -10) || true
    DIE_HINT="  交付包在传输中可能已损坏。请重新传输交付包后再运行。
    注意：服务**未**启动，宿主环境未被改动。"
    die "镜像 SHA256 校验未通过" "$DIE_HINT"
  fi
  mark_done "镜像完整性校验"

  # ══════════════════════════════════════════════════════════════
  step "加载镜像"
  # ══════════════════════════════════════════════════════════════
  for tar in "$IMAGES_DIR"/*.tar; do
    [ -f "$tar" ] || continue
    name="$(basename "$tar")"
    printf '     加载 %s ... ' "$name"
    if docker load -i "$tar" >/dev/null 2>&1; then
      ok "$name"
    else
      fail "$name"
      DIE_HINT="  docker load 失败。可手工执行查看原因：
      docker load -i $tar
    已加载的镜像不会被自动删除（无害）。服务**未**启动。"
      die "加载镜像失败：$name" "$DIE_HINT"
    fi
  done
  mark_done "加载镜像"
else
  # ══════════════════════════════════════════════════════════════
  step "在线拉取镜像"
  # ══════════════════════════════════════════════════════════════
  EXPECTED_IMAGES=$(grep -E '^\s+image:\s' "$PROJECT_SRC/$COMPOSE_FILE" | sed -E 's/^\s+image:\s*//' | sort -u)
  PULL_FAILED=""
  PULL_COUNT=0
  for image in $EXPECTED_IMAGES; do
    printf '     拉取 %s ... ' "$image"
    if docker pull "$image" >/dev/null 2>&1; then
      ok "$image"
      PULL_COUNT=$((PULL_COUNT + 1))
    else
      fail "$image"
      PULL_FAILED="$PULL_FAILED $image"
    fi
  done
  if [ -n "$PULL_FAILED" ]; then
    DIE_HINT="  以下镜像拉取失败：$PULL_FAILED
  现场不能出网时改用离线方式：
    sudo bash $SCRIPT_DIR/install.sh --mode offline --images <含 *.tar 的目录>
  或直接使用交付包（自带 images/ 与 project/）。
  服务**未**启动，宿主环境未被修改。"
    die "在线拉取镜像失败" "$DIE_HINT"
  fi
  ok "全部 $PULL_COUNT 个镜像拉取完成"
  mark_done "拉取镜像"
fi

# 确认 compose 需要的 tag 都在（加载成功≠tag 正确）
EXPECTED_IMAGES=$(grep -E '^\s+image:\s' "$PROJECT_SRC/$COMPOSE_FILE" | sed -E 's/^\s+image:\s*//' | sort -u)
MISSING_IMAGES=""
for image in $EXPECTED_IMAGES; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    MISSING_IMAGES="$MISSING_IMAGES $image"
  fi
done
if [ -n "$MISSING_IMAGES" ]; then
  if [ "$MODE" = "offline" ]; then
    DIE_HINT="  compose 需要但本地缺失的镜像：$MISSING_IMAGES
  请确认交付包 images/ 完整，且镜像 tag 与 compose 声明一致。
  服务**未**启动。"
  else
    DIE_HINT="  compose 需要但本地缺失的镜像：$MISSING_IMAGES
  拉取步骤显示成功但镜像仍缺失，可能是 tag 声明与实际拉取不符——
  请核对 $PROJECT_SRC/$COMPOSE_FILE 的 image: 行。
  服务**未**启动。"
  fi
  die "镜像 tag 与 compose 声明不匹配" "$DIE_HINT"
fi
ok "compose 所需的镜像 tag 全部就位（$(echo "$EXPECTED_IMAGES" | wc -l) 个）"

# ══════════════════════════════════════════════════════════════
step "准备数据目录"
# ══════════════════════════════════════════════════════════════
mkdir -p "$PROJECT_DIR"
# 复用交付物里的 pre_install.sh（目录与权限逻辑只此一份，不重复发明）
if [ -f "$PROJECT_SRC/pre_install.sh" ]; then
  if SMARTX_INSTALL_ROOT="$INSTALL_ROOT" \
     SMARTX_PROJECT_PATH="$PROJECT_DIR" \
     SMARTX_PROMETHEUS_UID="$PROMETHEUS_UID" \
     SMARTX_PROMETHEUS_GID="$PROMETHEUS_GID" \
     sh "$PROJECT_SRC/pre_install.sh" >/dev/null 2>&1; then
    ok "目录与权限就绪（含 prometheus uid/gid=${PROMETHEUS_UID}:${PROMETHEUS_GID}）"
  else
    # pre_install.sh 在非默认路径下可能因目录已存在等非致命原因返回非零，这里兜底自建
    warn "pre_install.sh 返回非零，改用兜底方式准备目录"
    for sub in app prometheus upgrades backups exports compose-runtime; do
      mkdir -p "$INSTALL_ROOT/$sub"
    done
    mkdir -p "$INSTALL_ROOT/exports/reports" "$INSTALL_ROOT/exports/migrations" \
             "$INSTALL_ROOT/exports/imports" "$INSTALL_ROOT/exports/migration-tasks"
    chown -R "$PROMETHEUS_UID:$PROMETHEUS_GID" "$INSTALL_ROOT/prometheus" 2>/dev/null || true
  fi
else
  die "交付物缺少 pre_install.sh" "交付目录不完整，请重新获取交付包。"
fi
mark_done "准备数据目录"

# ══════════════════════════════════════════════════════════════
step "放置平台部署文件"
# ══════════════════════════════════════════════════════════════
# 先备份既有 compose（重装场景，便于人工比对）。
# 变体 2026-10-07 改名（dev/online 取代 yml/release）：旧名文件在旧现场可能仍在，
# 一并备份后再覆盖。
for name in "$COMPOSE_FILE" docker-compose.dev.yml docker-compose.online.yml docker-compose.yml docker-compose.release.yml; do
  if [ -f "$PROJECT_DIR/$name" ] && [ "$name" != "$COMPOSE_FILE" ]; then
    cp -p "$PROJECT_DIR/$name" "$PROJECT_DIR/$name.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
  fi
done
if [ "$SHAPE" = "repo" ]; then
  # 仓库形态：只复制部署清单（与 build_offline_delivery.copy_project_files 对齐，
  # 不把整仓拷进 /data；prometheus.yml 必须落在 project/prometheus/ 才能被挂载）
  cp -a "$PROJECT_SRC/$COMPOSE_FILE_OFFLINE" "$PROJECT_DIR/"
  cp -a "$PROJECT_SRC/$COMPOSE_FILE_ONLINE" "$PROJECT_DIR/"
  cp -a "$PROJECT_SRC/docker-compose.dev.yml" "$PROJECT_DIR/"
  mkdir -p "$PROJECT_DIR/prometheus"
  cp -a "$PROJECT_SRC/prometheus/prometheus.yml" "$PROJECT_DIR/prometheus/"
else
  cp -a "$PROJECT_SRC/." "$PROJECT_DIR/"
fi

# US-37：把 compose 变体守卫也放进 project 目录。
# 交付目录可能被客户挪走或删除，但 project 目录是长期驻留的——
# 运维手册与 troubleshooting §10 指引的诊断路径是
# /data/smartx-storage-forecast/project/compose-guard.sh，必须真实存在。
if [ -n "$COMPOSE_GUARD" ] && [ -f "$COMPOSE_GUARD" ]; then
  install -m 0755 "$COMPOSE_GUARD" "$PROJECT_DIR/compose-guard.sh"
  ok "compose 守卫已就位（$PROJECT_DIR/compose-guard.sh）"
fi
ok "compose 与 prometheus 配置已就位"

# 非默认 install-root 时渲染 compose 里的绝对路径，并**校验渲染彻底**
DEFAULT_ROOT="/data/smartx-storage-forecast"
if [ "$INSTALL_ROOT" != "$DEFAULT_ROOT" ]; then
  for name in "$COMPOSE_FILE" docker-compose.dev.yml docker-compose.online.yml; do
    target="$PROJECT_DIR/$name"
    [ -f "$target" ] || continue
    sed -i "s#${DEFAULT_ROOT}#${INSTALL_ROOT}#g" "$target"
  done
  LEFTOVER=$(grep -c "$DEFAULT_ROOT" "$COMPOSE_PATH" || true)
  if [ "${LEFTOVER:-0}" -ne 0 ]; then
    # 换成自带反斜杠或含 sed 特殊字符的路径可能导致部分替换未生效
    printf '%s' "$(cat "$COMPOSE_PATH")" > "$COMPOSE_PATH.tmp" && mv "$COMPOSE_PATH.tmp" "$COMPOSE_PATH"
    python3 - "$COMPOSE_PATH" "$DEFAULT_ROOT" "$INSTALL_ROOT" <<'PY' 2>/dev/null || true
import sys
from pathlib import Path
compose, default, install_root = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = compose.read_text(encoding="utf-8").replace(default, install_root)
compose.write_text(text, encoding="utf-8")
PY
  fi
  if grep -q "$DEFAULT_ROOT" "$COMPOSE_PATH"; then
    DIE_HINT="  自定义 --install-root ($INSTALL_ROOT) 渲染后，compose 里仍残留默认路径 ${DEFAULT_ROOT}。
  请使用不含特殊字符的路径（避免 & | \\ 等），或先修正 compose 后重跑。
  服务**未**启动。"
    die "compose 路径渲染不彻底" "$DIE_HINT"
  fi
  ok "compose 绝对路径已渲染为 $INSTALL_ROOT"
fi
mark_done "放置部署文件"

# ══════════════════════════════════════════════════════════════
step "生成 .env"
# ══════════════════════════════════════════════════════════════
gen_secret() {
  # 32 字节随机值，十六进制输出；不打印、不落盘到交付物
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}
SECRET_KEY="$(gen_secret)"
CREDENTIAL_KEY="$(gen_secret)"
if [ ${#SECRET_KEY} -lt 32 ] || [ ${#CREDENTIAL_KEY} -lt 32 ]; then
  die "随机密钥生成失败或长度不足" "请检查系统是否有 openssl 或 /dev/urandom 可用。服务**未**启动。"
fi

if [ -n "$ENV_TEMPLATE" ]; then
  ENV_CONTENT="$(cat "$ENV_TEMPLATE")"
else
  # 仓库形态：.env.example 的占位符与交付 .env.template 采用同一替换表
  # （对应 build_offline_delivery.build_env_template 的替换）
  ENV_CONTENT="$(sed -e 's/replace-with-a-long-random-secret/__GENERATE__/' \
                     -e 's/replace-with-a-different-long-random-secret/__GENERATE__/' \
                     "$ENV_TEMPLATE_SOURCE")"
fi
ENV_CONTENT="${ENV_CONTENT//__GENERATE__/$SECRET_KEY}"
# __GENERATE__ 出现两次（secret + credential），上面一次替换会把两处都替成同一个值，
# 这里把第二个密钥单独纠正（模板顺序固定：先 SECRET_KEY 后 CREDENTIAL_KEY）
ENV_CONTENT="$(printf '%s' "$ENV_CONTENT" | awk -v sk="$SECRET_KEY" -v ck="$CREDENTIAL_KEY" '
  /^SMARTX_SECRET_KEY=/            { print "SMARTX_SECRET_KEY=" sk; next }
  /^SMARTX_CREDENTIAL_KEY=/        { print "SMARTX_CREDENTIAL_KEY=" ck; next }
  { print }
')"
ENV_CONTENT="${ENV_CONTENT//SMARTX_ADMIN_USER=admin/SMARTX_ADMIN_USER=$ADMIN_USER}"
ENV_CONTENT="${ENV_CONTENT//SMARTX_ADMIN_PASSWORD=password/SMARTX_ADMIN_PASSWORD=$ADMIN_PASSWORD}"

# Tower 配置（可选）
if [ -n "$TOWER_URL" ]; then
  ENV_CONTENT="$ENV_CONTENT
SMARTX_TOWER_URL=$TOWER_URL"
fi
if [ -n "$TOWER_USER" ]; then
  ENV_CONTENT="$ENV_CONTENT
SMARTX_TOWER_USER=$TOWER_USER"
fi
if [ -n "$TOWER_PASSWORD" ]; then
  ENV_CONTENT="$ENV_CONTENT
SMARTX_TOWER_PASSWORD=$TOWER_PASSWORD"
fi

# US-37 遗留修复：--force-env 重生成 .env（密钥更换）。若后续守卫因变体不一致拒绝启动，
# 必须恢复原 .env——在跑容器持有的还是原密钥，密钥错位会让下次重启后 Tower 凭据解不开。
# 备份在重生成**之前**落盘（0600）；守卫放行路径在启动成功后删除。
PREEXISTING_ENV_BACKUP=0
if [ "$FORCE_ENV" -eq 1 ] && [ -f "$ENV_FILE" ]; then
  cp -p "$ENV_FILE" "$ENV_FILE.pre-reinstall" && chmod 600 "$ENV_FILE.pre-reinstall"
  PREEXISTING_ENV_BACKUP=1
fi
printf '%s\n' "$ENV_CONTENT" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE" 2>/dev/null || true
# 校验：占位符必须已被替换，密钥不得为空
if grep -q "__GENERATE__" "$ENV_FILE"; then
  DIE_HINT="  .env 模板中的密钥占位符未被完全替换，密钥可能为空。
  请检查交付包 .env.template 是否被手工改动过。服务**未**启动。"
  die "生成的 .env 仍含占位符" "$DIE_HINT"
fi
if grep -qE '^SMARTX_SECRET_KEY=$|^SMARTX_CREDENTIAL_KEY=$' "$ENV_FILE"; then
  die "生成的 .env 密钥为空" "随机数生成异常，请重跑。服务**未**启动。"
fi
# 两把密钥必须不同
SK_IN_FILE=$(grep '^SMARTX_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2-)
CK_IN_FILE=$(grep '^SMARTX_CREDENTIAL_KEY=' "$ENV_FILE" | cut -d= -f2-)
if [ "$SK_IN_FILE" = "$CK_IN_FILE" ]; then
  die "两把密钥相同（模板替换异常）" "请勿手工复用同一密钥；重跑本脚本会重新生成。服务**未**启动。"
fi
# US-37：新生成的 .env 必须带上 compose 变体标记（守卫的事实源）。
# 开头的 compose_guard_resolve 只在「已有 .env」时执行，全新安装拿不到它的输出——
# 若这里不补写，装完的 .env 永远没有标记（T5 判据不成立，守卫对全新环境失效）。
# RESOLVED_COMPOSE 是重装场景的地面真相（旧标记/容器标签），保留它才能让
# --force-env 重装路径仍受守卫的变体不一致判定保护。
if declare -F compose_guard_write >/dev/null; then
  if compose_guard_write "$ENV_FILE" "${RESOLVED_COMPOSE:-$COMPOSE_FILE}"; then
    ok "compose 变体标记已写入（${RESOLVED_COMPOSE:-${COMPOSE_FILE}}）"
  else
    warn "compose 变体标记写入失败（守卫将按无标记放行，不影响本次安装）"
  fi
fi
ok ".env 已生成（0600 root:root），密钥为随机值且两把不同"
info "管理员：$ADMIN_USER / $ADMIN_PASSWORD"
unset ENV_CONTENT SECRET_KEY CREDENTIAL_KEY SK_IN_FILE CK_IN_FILE
mark_done "生成 .env"

# ══════════════════════════════════════════════════════════════
step "启动服务"
# ══════════════════════════════════════════════════════════════
if [ "$ASSUME_YES" -eq 0 ]; then
  printf '\n即将启动以下服务（compose project=%s）：\n' "$COMPOSE_PROJECT"
  grep -E '^  [a-z][a-z0-9-]*:$' "$COMPOSE_PATH" | sed -E 's/^  /  - /; s/:$//' | grep -v '^  - $'
  printf '\n管理员账号：%s\n' "$ADMIN_USER"
  printf '数据目录：%s\n' "$INSTALL_ROOT"
  read -r -p "确认启动？[y/N] " reply
  case "$reply" in
    [yY]|[yY][eE][sS]) ;;
    *) c_yellow "已取消，未启动任何服务。"; exit 0 ;;
  esac
fi

compose_cmd() {
  docker compose -f "$COMPOSE_PATH" -p "$COMPOSE_PROJECT" "$@"
}

# US-37：启动前拦截 compose 变体不一致。守卫缺失时只提醒不阻断（向后兼容）。
if declare -F compose_guard_check >/dev/null; then
  if ! compose_guard_check "$ENV_FILE" "$COMPOSE_FILE" "$COMPOSE_PROJECT"; then
    if [ "$FORCE_COMPOSE_SWITCH" -eq 1 ]; then
      c_yellow "已指定 --force-compose-switch，按「先完整停机再换变体」执行。"
      compose_guard_down_then_switch "$ENV_FILE" "$PROJECT_DIR" "$COMPOSE_PROJECT" "$COMPOSE_FILE" \
        || die "compose 变体切换失败（停机阶段出错）" "服务当前状态：已停机或原样，请用 docker compose -f $PROJECT_DIR/$COMPOSE_FILE -p $COMPOSE_PROJECT ps 确认。"
    else
      if [ "$PREEXISTING_ENV_BACKUP" -eq 1 ] && [ -f "$ENV_FILE.pre-reinstall" ]; then
        cat "$ENV_FILE.pre-reinstall" > "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        rm -f "$ENV_FILE.pre-reinstall"
        PREEXISTING_ENV_BACKUP=0
        warn "已恢复原有 .env（密钥与标记未更换，与在跑容器保持一致）"
      fi
      die "compose 变体不一致，已拒绝启动（见上方守卫输出）" \
        "确认要换变体请加 --force-compose-switch（会先完整停机，造成计划内中断）。服务**未**启动，宿主环境未被改动。"
    fi
  fi
fi

if ! compose_cmd up -d >/dev/null 2>&1; then
  c_red "docker compose up 失败，输出如下："
  compose_cmd up -d 2>&1 | tail -20 || true
  DIE_HINT="  服务**未**完全启动。排查建议：
  1) docker compose -f $COMPOSE_PATH -p $COMPOSE_PROJECT ps
  2) docker compose -f $COMPOSE_PATH -p $COMPOSE_PROJECT logs --tail=100
  3) 确认 .env 权限为 600 且内容完整
  已加载的镜像与已生成的 .env 会保留，修正后重跑本脚本即可。"
  die "启动服务失败" "$DIE_HINT"
fi
ok "compose 已提交启动"
mark_done "启动服务"
# 重装已完成切换、新 .env 已被容器启用：原 .env 备份不再需要（0600 敏感文件不留盘）。
if [ "$PREEXISTING_ENV_BACKUP" -eq 1 ] && [ -f "$ENV_FILE.pre-reinstall" ]; then
  rm -f "$ENV_FILE.pre-reinstall"
  PREEXISTING_ENV_BACKUP=0
fi

# ══════════════════════════════════════════════════════════════
step "健康检查"
# ══════════════════════════════════════════════════════════════
HEALTH_URL="http://127.0.0.1:8000/api/system/health"
printf '     等待健康检查（最长 %s 秒）' "$HEALTH_TIMEOUT"
ELAPSED=0
HEALTHY=0
while [ "$ELAPSED" -lt "$HEALTH_TIMEOUT" ]; do
  if command -v curl >/dev/null 2>&1; then
    BODY="$(curl -s --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
  else
    BODY="$(wget -qO- --timeout=5 "$HEALTH_URL" 2>/dev/null || true)"
  fi
  case "$BODY" in
    *'"ok":true'*|*'"ok": true'*) HEALTHY=1; break ;;
  esac
  printf '.'
  sleep 3
  ELAPSED=$((ELAPSED + 3))
done
printf '\n'
if [ "$HEALTHY" -ne 1 ]; then
  fail "健康检查未通过（等待 ${ELAPSED}s）"
  printf '\n容器状态：\n'
  compose_cmd ps 2>&1 | head -12 || true
  printf '\nweb-api 最近日志：\n'
  compose_cmd logs --tail=40 web-api 2>&1 | tail -40 || true
  DIE_HINT="  常见原因与处理：
  1) 磁盘不足 → df -h $INSTALL_ROOT
  2) 端口冲突 → ss -ltnp | grep -E ':(8000|8080|9090)'
  3) 镜像缺失/不匹配 → docker image inspect 逐个核对 $COMPOSE_PATH 声明的 tag
  4) 目录权限问题 → 确认 $INSTALL_ROOT 下各子目录属主正确
  修正后重跑本脚本（已完成的步骤会自动跳过）。"
  die "服务未在超时内达到健康状态" "$DIE_HINT"
fi
ok "健康检查通过"
mark_done "健康检查"

# ══════════════════════════════════════════════════════════════
step "安装完成"
# ══════════════════════════════════════════════════════════════
VERSION="unknown"
RUNNER_VERSION="unknown"
if command -v curl >/dev/null 2>&1; then
  HEALTH_BODY="$(curl -s --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
  VERSION="$(printf '%s' "$HEALTH_BODY" | sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  RUNNER_VERSION="$(printf '%s' "$HEALTH_BODY" | sed -nE 's/.*"runner_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
fi

c_green "════════════════════════════════════════════════"
c_green " SmartX HCI Capacity Insight 安装完成"
c_green "════════════════════════════════════════════════"
printf '\n'
printf '  平台版本：%s\n' "${VERSION:-unknown}"
printf '  Runner   ：%s\n' "${RUNNER_VERSION:-unknown}"
printf '  访问地址 ：http://<本机IP>:8080\n'
printf '  API 地址 ：%s\n' "$HEALTH_URL"
printf '  管理员   ：%s / %s\n' "$ADMIN_USER" "$ADMIN_PASSWORD"
printf '  数据目录 ：%s\n' "$INSTALL_ROOT"
printf '\n'
c_yellow "  ⚠ 请立即在 Web 界面登录并修改管理员口令（默认口令是公开的）。"
printf '\n'
printf '  常用运维命令：\n'
printf '    查看状态：docker compose -f %s -p %s ps\n' "$COMPOSE_PATH" "$COMPOSE_PROJECT"
printf '    查看日志：docker compose -f %s -p %s logs -f web-api\n' "$COMPOSE_PATH" "$COMPOSE_PROJECT"
printf '    停止服务：docker compose -f %s -p %s stop\n' "$COMPOSE_PATH" "$COMPOSE_PROJECT"
printf '\n'
if [ "$SHAPE" = "delivery" ]; then
  printf '  离线升级：使用交付包的 upgrade/upgrade.sh（走升级中心 API，不需联网）\n'
else
  printf '  升级：使用仓库的 ops/upgrade.sh（自动定位/生成升级物料，走升级中心 API）\n'
fi
printf '\n'
exit 0
