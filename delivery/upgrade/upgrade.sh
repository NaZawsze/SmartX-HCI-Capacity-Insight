#!/usr/bin/env bash
# 离线一键升级：SmartX HCI Capacity Insight
#
# 设计：docs/superpowers/specs/2026-09-28-offline-one-click-install-upgrade-design.md §5
#
# 核心约束：**全程只调本机升级中心 API**，绝不直接改环境。
# 直接 docker load + compose up 会绕过：
#   · 单飞守卫（US-23）——并发升级在错误状态上执行
#   · post-cleanup —— 旧环境不清理、残留累积（US-27 现场已复现）
#   · 任务历史 —— 无留痕、现场无法取证
#   · 失败逃生门（US-25）——卡死任务无产品化出路，环境被永久锁死
# API 是本机 127.0.0.1，离线场景照样可用，因此走 API 不牺牲离线性。
#
# 本脚本**不含** docker load / compose up / rm —— 有单测静态锁定这一点。
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGES_DIR="$SCRIPT_DIR/packages"

BASE_URL="http://127.0.0.1:8000"
PACKAGE=""
RUNNER_PACKAGE=""
ADMIN_USER=""
ADMIN_PASSWORD=""
ALLOW_SAME_VERSION=0
ENV_FILE="/data/smartx-storage-forecast/project/.env"
ASSUME_YES=0
POLL_INTERVAL=10
POLL_TIMEOUT=1800

c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
info()  { printf '     %s\n' "$*"; }
ok()    { c_green "  [OK] $*"; }
warn()  { c_yellow "  [!!] $*"; }
fail()  { c_red "  [XX] $*"; }

usage() {
  cat <<'USAGE'
离线一键升级 · SmartX HCI Capacity Insight

用法:
  bash upgrade/upgrade.sh [选项]

选项:
  --package <包路径>        平台升级包（默认自动选 packages/ 里唯一的平台包）
  --with-runner <组件包>    平台升级成功后再升级 runner 组件（默认不做）
  --allow-same-version      允许目标版本与当前版本相同的**同版本重装**（恢复手段，
                            服务会中断；默认不加此参数时同版本重装会被拦截）
  --base-url <地址>         平台 API（默认 http://127.0.0.1:8000，即本机）
  --admin-user <用户名>     管理员用户名（默认从 .env 读，再回退 admin）
  --admin-password <口令>   管理员口令（默认从 .env 读，再回退 password）
  --env-file <路径>         .env 路径（默认 /data/smartx-storage-forecast/project/.env）
  --poll-timeout <秒>       升级轮询超时（默认 1800）
  --yes                     非交互模式
  -h, --help                显示本帮助

示例:
  # 升级到 packages/ 里唯一的平台包
  bash upgrade/upgrade.sh --yes

  # 指定包，并连带升级 runner 组件
  bash upgrade/upgrade.sh --package packages/smartx-capacity-insight-upgrade-v0.5.3.tar.gz \
                          --with-runner packages/smartx-upgrade-runner-v0.3.2.tar.gz

顺序说明:
  默认**只升平台**。runner 组件升级请在平台升级成功之后单独发起（--with-runner），
  顺序颠倒（旧平台的 web-api 会停掉刚启动的新 runner）可能导致升级中断。
  --with-runner 会先等平台升级后的清理任务（post-cleanup）收敛，再发起 runner 组件升级，
  避免被"同一时刻只允许一个升级任务"的守卫拒绝。
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --package)        PACKAGE="${2:?}"; shift 2 ;;
    --with-runner)    RUNNER_PACKAGE="${2:?}"; shift 2 ;;
    --allow-same-version) ALLOW_SAME_VERSION=1; shift ;;
    --base-url)       BASE_URL="${2:?}"; shift 2 ;;
    --admin-user)     ADMIN_USER="${2:?}"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="${2:?}"; shift 2 ;;
    --env-file)       ENV_FILE="${2:?}"; shift 2 ;;
    --poll-timeout)   POLL_TIMEOUT="${2:?}"; shift 2 ;;
    --yes|-y)         ASSUME_YES=1; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) fail "未知选项：$1"; usage; exit 1 ;;
  esac
done

# ── 包路径归一化（2026-09-30 `.14` 实测修）──
# 相对路径原本按**调用者当前目录**解析，于是交付包 README 里写的
#   bash upgrade/upgrade.sh --with-runner upgrade/packages/smartx-upgrade-runner-v0.3.2.tar.gz
# 只在「恰好 cd 到交付根目录」时成立；在 /root、/tmp 等处调用就报
# 「runner 组件包不存在，跳过：…」——**照文档做却静默不升级**，是最难查的一类问题。
#
# 现在按**脚本自身位置**（SCRIPT_DIR，即 upgrade/）解析，且兼容两种历史写法：
#   packages/<包名>              —— 相对脚本目录（README 与 usage 的标准写法）
#   upgrade/packages/<包名>      —— 相对交付根目录（旧 README 写法，仍兼容）
# 绝对路径原样保留。逐个回退，取第一个真实存在的文件。
# 归一化一个包路径变量（间接传参，bash 3.2 无 nameref）
_normalize_pkg_path() {
  _np_in="$1"
  case "$_np_in" in
    /*) printf '%s' "$_np_in"; return 0 ;;      # 绝对路径原样
    *)  : ;;
  esac
  # 候选顺序：脚本同级 → 交付根（去掉 upgrade/ 前缀）→ 调用者 cwd（保持旧行为兜底）
  for _np_cand in \
      "$SCRIPT_DIR/$_np_in" \
      "$SCRIPT_DIR/../$_np_in" \
      "$_np_in" ; do
    if [ -f "$_np_cand" ]; then
      printf '%s' "$(cd "$(dirname "$_np_cand")" && pwd)/$(basename "$_np_cand")"
      return 0
    fi
  done
  # 都不存在：按脚本同级拼一个，让后续报错信息指向正确位置
  printf '%s' "$SCRIPT_DIR/$_np_in"
}

if [ -n "$PACKAGE" ]; then
  PACKAGE="$(_normalize_pkg_path "$PACKAGE")"
fi
if [ -n "$RUNNER_PACKAGE" ]; then
  RUNNER_PACKAGE="$(_normalize_pkg_path "$RUNNER_PACKAGE")"
fi

die() {
  fail "$1"
  [ -n "${DIE_HINT:-}" ] && printf '\n%s\n' "$DIE_HINT"
  printf '\n本脚本只调 API，不会自行修改环境；请按上方指引在 Web 界面处理后重跑。\n'
  exit 1
}

# 读 .env 里的某个键（不 source 整个文件，避免执行任意内容）
read_env_value() {
  local key="$1" file="$2"
  [ -f "$file" ] || return 1
  grep -E "^${key}=" "$file" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

if [ -z "$ADMIN_USER" ]; then
  ADMIN_USER="$(read_env_value SMARTX_ADMIN_USER "$ENV_FILE" || true)"
  ADMIN_USER="${ADMIN_USER:-admin}"
fi
if [ -z "$ADMIN_PASSWORD" ]; then
  ADMIN_PASSWORD="$(read_env_value SMARTX_ADMIN_PASSWORD "$ENV_FILE" || true)"
  ADMIN_PASSWORD="${ADMIN_PASSWORD:-password}"
fi

# ══════════════════════════════════════════════════════════════
# US-37：加载 compose 变体守卫，仅用于**只读**诊断。
# 本脚本不含 docker load / compose up / rm（有单测静态锁定），守卫不改变这一点。
COMPOSE_GUARD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/compose-guard.sh"
if [ -f "$COMPOSE_GUARD" ]; then
  # shellcheck source=/dev/null
  . "$COMPOSE_GUARD"
else
  COMPOSE_GUARD=""
fi

printf '\n══ 离线一键升级 · SmartX HCI Capacity Insight ══\n'
# ══════════════════════════════════════════════════════════════

# ── 前置检查 ──
command -v curl >/dev/null 2>&1 || die "未找到 curl" "请安装 curl 后重试。"
[ "$(id -u)" = "0" ] || warn "当前非 root；升级通常需要 root 读取 .env 与交付目录。"

HEALTH_URL="$BASE_URL/api/system/health"
HEALTH_BODY="$(curl -s --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
case "$HEALTH_BODY" in
  *'"ok":true'*|*'"ok": true'*) ;;
  *)
    DIE_HINT="  无法访问 $HEALTH_URL
  请确认平台正在运行：docker ps | grep web-api
  离线升级走的是**本机** API，不需要外网。"
    die "平台不可达或健康检查失败" "$DIE_HINT"
    ;;
esac
CURRENT_VERSION="$(printf '%s' "$HEALTH_BODY" | sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
CURRENT_RUNNER="$(printf '%s' "$HEALTH_BODY" | sed -nE 's/.*"runner_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
ok "平台可达：版本 ${CURRENT_VERSION:-unknown}，runner ${CURRENT_RUNNER:-unknown}"

# ── US-37 只读诊断：当前实例生效的 compose 变体 ──
# 不阻断升级（旧环境可能没有标记），只是把事实摆出来：
# 后续若有人手工敲 docker compose up，用错变体会 recreate 掉服务（2026-09-30 .3 事故）。
if [ -n "$COMPOSE_GUARD" ]; then
  _upg_project_dir="/data/smartx-storage-forecast/project"
  _upg_env="$_upg_project_dir/.env"
  if [ -f "$_upg_env" ]; then
    _upg_active="$(compose_guard_marker "$_upg_env")"
    if [ -n "$_upg_active" ]; then
      info "当前实例的 compose 变体：${_upg_active}（记录于 .env）"
    else
      _upg_detected="$(compose_guard_detect_running smartx-hci-capacity-insight)"
      if [ -n "$_upg_detected" ]; then
        warn "compose 变体未记录在 .env；按容器标签实测为 ${_upg_detected}"
        info "建议重跑 install/install.sh 以补上标记（防误用其它变体导致服务 recreate）。"
      fi
    fi
  fi
fi

# ── 选定升级包 ──
if [ -z "$PACKAGE" ]; then
  mapfile -t CANDIDATES < <(find "$PACKAGES_DIR" -maxdepth 1 -name 'smartx-capacity-insight-upgrade-*.tar.gz' 2>/dev/null | sort)
  if [ "${#CANDIDATES[@]}" -eq 1 ]; then
    PACKAGE="${CANDIDATES[0]}"
    info "自动选定升级包：$(basename "$PACKAGE")"
  elif [ "${#CANDIDATES[@]}" -eq 0 ]; then
    DIE_HINT="  在 $PACKAGES_DIR 下未找到平台升级包（smartx-capacity-insight-upgrade-*.tar.gz）。
  请把升级包放进 packages/ 目录，或用 --package 指定路径。"
    die "未找到升级包" "$DIE_HINT"
  else
    printf '  找到多个平台升级包，请用 --package 指定其一：\n'
    for c in "${CANDIDATES[@]}"; do printf '    - %s\n' "$(basename "$c")"; done
    exit 1
  fi
fi
[ -f "$PACKAGE" ] || die "升级包不存在：$PACKAGE" "请检查路径。"
PACKAGE_DIR="$(cd "$(dirname "$PACKAGE")" && pwd)"
PACKAGE_NAME="$(basename "$PACKAGE")"

# ── 校验包完整性 ──
if [ -f "$PACKAGE_DIR/SHA256SUMS" ]; then
  if (cd "$PACKAGE_DIR" && sha256sum -c --ignore-missing SHA256SUMS >/dev/null 2>&1); then
    ok "包 SHA256 校验通过"
  else
    c_red "包 SHA256 校验失败："
    (cd "$PACKAGE_DIR" && sha256sum -c --ignore-missing SHA256SUMS 2>&1 | grep -vE ': OK$' | head -5) || true
    DIE_HINT="  交付包在传输中可能已损坏，请重新传输。
  **尚未发起任何升级**，环境未被改动。"
    die "包校验未通过" "$DIE_HINT"
  fi
else
  warn "未找到 SHA256SUMS，跳过本地校验（建议交付包带上校验文件）"
fi

# ── L3-c 硬拦截：平台包声明的 runner 执行门槛 ──
# 为什么要在这里也拦（而不只靠平台预检查）：跑着 v0.5.2 及更早平台时，它的预检查**还没有**
# 版本门禁（r42 才加），Web 路径拦不住；CLI 是那条时间线上唯一能提前拦住的地方。
# 实测根因：runner v0.3.1 的能力集与 v0.3.2 同名同数，能力级校验放行；但它的沙箱把**容器内**包路径
# 原样挂给 docker（旧布局下容器路径=宿主路径所以能跑），v0.5.2 布局迁移后挂载源不存在 →
# `can't find '__main__' module in '/upgrade/run_migrations.py'`，失败落在 image.load 之后、
# compose.apply 之前，环境半迁移。故 v0.5.4 平台包要求 runner ≥ v0.3.2（先组件、后平台）。
_version_ge() {
  # $1 >= $2 ？（语义化版本，忽略 v 前缀；无法解析时返回"满足"以免误拦）
  local a b
  a="$(printf '%s' "$1" | sed 's/^[vV]//')"
  b="$(printf '%s' "$2" | sed 's/^[vV]//')"
  [ -n "$a" ] && [ -n "$b" ] || return 0
  [ "$(printf '%s\n%s\n' "$b" "$a" | sort -V | head -n1)" = "$b" ]
}
_version_like() {
  # 是否是能比较的版本号（health 在 runner 不在时会返回「未检测到 runner」这类文案）
  printf '%s' "$1" | grep -Eq '^[vV]?[0-9]+(\.[0-9]+)*$'
}
_runner_version_fresh() {
  # 实时重读 health 的 runner 版本（带短重试）。
  # 为什么必须重读：组件升级刚结束时状态文件虽已刷新，但 health 的在场判定可能仍短暂返回旧值
  # （实测：runner v0.3.1→v0.3.2 完成后 10s 内 health 仍报 v0.3.1）。直接拿脚本开头的旧读数做
  # 拦截决策，会把「刷新滞后」误判成「版本不足」——拦截必须建立在事实上，不能建立在过期缓存上。
  local body value attempt
  for attempt in 1 2 3 4 5; do
    body="$(curl -s --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
    value="$(printf '%s' "$body" | sed -nE 's/.*"runner_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
    if [ -n "$value" ]; then
      printf '%s' "$value"
      return 0
    fi
    sleep 4
  done
  printf '%s' "${1:-}"
}
# ── 跨版本硬拦截：平台包声明的源版本支持范围 ──
# 为什么 CLI 也要拦：source_compatibility 预检查只存在于**源端**较新版本的 web-api；
# 跑着 v0.5.1u2 / v0.5.2 时它根本不执行。runner 门槛虽然也会挡住，但给出的
# 「先组件后平台」指引对 ≤v0.5.1u2 是**错的**——v0.5.4 不支持这些源，正确出路是先升 v0.5.3。
# 因此按包 manifest 的 source_compatibility 先判源版本，并把包自带的 remediation 原样透传
# （拒绝必须带出路；文案由包描述支持矩阵，不在脚本里写死版本号）。
if [ -n "$CURRENT_VERSION" ] && [ -f "$PACKAGE" ]; then
  SRC_FRAG="$(tar xzOf "$PACKAGE" manifest.json 2>/dev/null \
    | tr -d '\n' \
    | sed -E 's/.*"source_compatibility"[[:space:]]*:[[:space:]]*\{//; s/\}.*//')"
  SRC_MIN="$(printf '%s' "$SRC_FRAG" | sed -nE 's/.*"min_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1)"
  SRC_MAX="$(printf '%s' "$SRC_FRAG" | sed -nE 's/.*"max_version_inclusive"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1)"
  SRC_REMEDIATION="$(printf '%s' "$SRC_FRAG" | sed -nE 's/.*"remediation"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1)"
  if [ -n "$SRC_MIN" ] && ! { _version_ge "$CURRENT_VERSION" "$SRC_MIN" && _version_ge "$SRC_MAX" "$CURRENT_VERSION"; }; then
    DIE_HINT="  当前平台为 ${CURRENT_VERSION}，本升级包只支持源版本 ${SRC_MIN} ~ ${SRC_MAX:-?}。
  ${SRC_REMEDIATION:-请先升级到受支持的源版本，再升级本包。}
  **尚未发起任何升级**，环境未被改动。"
    die "当前平台版本不在升级包支持范围内（${CURRENT_VERSION} ∉ ${SRC_MIN} ~ ${SRC_MAX:-?}）" "$DIE_HINT"
  fi
  [ -n "$SRC_MIN" ] && info "源版本支持范围：${SRC_MIN} ~ ${SRC_MAX}（当前 ${CURRENT_VERSION}）"
fi
if [ -n "$CURRENT_RUNNER" ] && [ -f "$PACKAGE" ]; then
  RUNNER_NOW="$(_runner_version_fresh "$CURRENT_RUNNER")"
  MIN_RUNNER="$(tar xzOf "$PACKAGE" manifest.json 2>/dev/null \
    | sed -nE 's/.*"minimum_runner_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1)"
  if [ -n "$MIN_RUNNER" ] && { ! _version_like "$RUNNER_NOW" || ! _version_ge "$RUNNER_NOW" "$MIN_RUNNER"; }; then
    if _version_like "$CURRENT_VERSION" && ! _version_ge "$CURRENT_VERSION" "v0.5.3"; then
      # 源端早于 v0.5.3：runner-first 在这里不可靠（源端 web-api 会无条件 stop 掉刚启动的新
      # runner，US-04 实测 SIGKILL/exit=137），所以「先组件后平台」是死胡同。正确路径是先升
      # v0.5.3（已发布包），再组件、再本包——与版本偏斜矩阵的 remediation 一致。
      DIE_HINT="  当前平台为 ${CURRENT_VERSION}，runner 为 ${RUNNER_NOW:-未检测到}，不满足本包执行门槛 ≥ ${MIN_RUNNER}。
  **但该源端不能先升 runner**：v0.5.2 及更早的 web-api 在原地做组件升级时会无条件停掉刚启动的
  新 runner（US-04 实测 SIGKILL/exit=137，之后所有升级都被心跳预检查拒绝）。
  **正确路径：先把平台升到 v0.5.3（已发布包），再升级 runner 到 ${MIN_RUNNER}，最后升级本包。**
  **尚未发起任何升级**，环境未被改动。"
      die "源端 ${CURRENT_VERSION} 无法先升 runner（US-04），且 runner 不满足门槛（${RUNNER_NOW:-未检测到} < ${MIN_RUNNER}）" "$DIE_HINT"
    fi
    DIE_HINT="  当前 upgrade-runner 为 ${RUNNER_NOW:-未检测到}，本平台包要求 ≥ ${MIN_RUNNER} 才能执行升级计划。
  低于该版本的 runner 沙箱无法在 v0.5.2 之后的新布局下挂载包内迁移脚本，会在
  image.load 之后、compose.apply 之前失败，把环境留在半迁移态（L3-c 实测）。
  **正确顺序：先把 upgrade-runner 组件升到 ${MIN_RUNNER}**（Web 升级中心 → 组件升级，
  或对组件包调用 /api/admin/upgrade 的 component 上传与启动），再执行本次平台升级。
  **尚未发起任何升级**，环境未被改动。"
    die "当前 upgrade-runner 低于升级包执行门槛（${RUNNER_NOW} < ${MIN_RUNNER}）" "$DIE_HINT"
  fi
  [ -n "$MIN_RUNNER" ] && info "runner 执行门槛：≥ ${MIN_RUNNER}（当前 ${RUNNER_NOW}）"
fi

# ── 登录取 token ──
LOGIN_BODY="$(curl -s --max-time 20 -X POST "$BASE_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASSWORD\"}" 2>/dev/null || true)"
TOKEN="$(printf '%s' "$LOGIN_BODY" | sed -nE 's/.*"access_token"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
if [ -z "$TOKEN" ]; then
  DIE_HINT="  登录失败。请用 --admin-user / --admin-password 指定正确凭据，
  或确认管理员口令是否已在 Web 界面被修改过。
  **尚未发起任何升级**，环境未被改动。"
  die "登录失败" "$DIE_HINT"
fi
ok "登录成功"

AUTH=(-H "Authorization: Bearer $TOKEN")

# ── 上传 ──
UPLOAD_BODY="$(curl -s --max-time 900 -X POST "$BASE_URL/api/admin/upgrade/upload" \
  "${AUTH[@]}" -F "file=@$PACKAGE" 2>/dev/null || true)"
TASK_ID="$(printf '%s' "$UPLOAD_BODY" | sed -nE 's/.*"task_id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
if [ -z "$TASK_ID" ]; then
  DETAIL="$(printf '%s' "$UPLOAD_BODY" | head -c 300)"
  DIE_HINT="  上传失败：$DETAIL
  **尚未发起任何升级**，环境未被改动。请检查包是否完整、磁盘是否有空间。"
  die "上传升级包失败" "$DIE_HINT"
fi
TARGET_VERSION="$(printf '%s' "$UPLOAD_BODY" | sed -nE 's/.*"target_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
ok "已上传：$PACKAGE_NAME → 任务 $TASK_ID（目标 ${TARGET_VERSION:-unknown}）"

# 重复升级防呆（pending-tasks #60②）：目标版本与当前相同 = 同版本重装——
# 是恢复手段但会造成计划内服务中断，误触双击不该静默执行；默认拦截并给指引，
# 显式 --allow-same-version 才放行（同版本重装本身是已验证能力，不删除）。
if [ -n "$TARGET_VERSION" ] && [ "$TARGET_VERSION" != "unknown" ] \
   && [ -n "${CURRENT_VERSION:-}" ] && [ "$CURRENT_VERSION" != "unknown" ] \
   && [ "$TARGET_VERSION" = "$CURRENT_VERSION" ] && [ "$ALLOW_SAME_VERSION" -eq 0 ]; then
  DIE_HINT="  目标版本 ${TARGET_VERSION} 与当前运行版本相同：继续会执行一次**同版本重装**
  （恢复手段，服务会中断数分钟）。确要执行请加 --allow-same-version 重跑。
  本次**未调用 start**，升级未发起；已上传的任务可在升级中心删除或忽略。"
  die "重复升级已拦截：目标版本与当前版本相同" "$DIE_HINT"
fi

# ── 预检查（逐项打印；任一失败即停）──
PRECHECK_BODY="$(curl -s --max-time 300 -X POST "$BASE_URL/api/admin/upgrade/precheck/$TASK_ID" "${AUTH[@]}" 2>/dev/null || true)"
printf '\n  预检查结果：\n'
# 注意：python 代码用 **双引号** 包裹外层字符串时，内部只用双引号会冲突；
# 这里整体用单引号包裹，内部**只能用双引号**——写成 check.get('name') 会提前闭合
# shell 的单引号，导致后续被当命令执行、预检查结果原样打印 JSON（.14 实测踩到）。
if command -v python3 >/dev/null 2>&1; then
  printf '%s' "$PRECHECK_BODY" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    print("     （无响应）")
    raise SystemExit(0)
try:
    data = json.loads(raw)
except ValueError:
    print("     解析失败：", raw[:200])
    raise SystemExit(0)
checks = data.get("checks") or []
if not checks:
    print("     （无明细字段）")
for check in checks:
    mark = "OK  " if check.get("ok") else "FAIL"
    print("     [" + mark + "] " + str(check.get("name")) + ": " + str(check.get("message"))[:110])
'
else
  c_yellow "  系统无 python3，无法格式化预检查明细，原样输出："
  printf '     %s\n' "$(printf '%s' "$PRECHECK_BODY" | head -c 300)"
fi

if ! printf '%s' "$PRECHECK_BODY" | grep -q '"status":"prechecked"'; then
  DETAIL="$(printf '%s' "$PRECHECK_BODY" | sed -nE 's/.*"detail"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  DIE_HINT="  预检查未通过${DETAIL:+：$DETAIL}
  **未调用 start**，环境未被改动。请按上面失败项处理：
  · 版本不匹配 → 换用正确的升级包
  · 磁盘不足   → 清理空间后重试
  · 存在其它执行中/待恢复的任务 → 先在 Web 界面处理那个任务（单飞守卫，US-23）"
  die "预检查未通过" "$DIE_HINT"
fi
ok "预检查通过"

# ── 确认后开始 ──
if [ "$ASSUME_YES" -eq 0 ]; then
  printf '\n  即将把平台从 %s 升级到 %s。\n' "${CURRENT_VERSION:-unknown}" "${TARGET_VERSION:-unknown}"
  read -r -p "  确认开始升级？[y/N] " reply
  case "$reply" in
    [yY]|[yY][eE][sS]) ;;
    *) c_yellow "已取消，未发起升级。"; exit 0 ;;
  esac
fi

START_BODY="$(curl -s --max-time 120 -X POST "$BASE_URL/api/admin/upgrade/start/$TASK_ID" "${AUTH[@]}" 2>/dev/null || true)"
case "$START_BODY" in
  *'"status":"pending"'*|*'"status":"running"'*|*'"status":"succeeded"'*) ;;
  *'"detail"'*)
    DETAIL="$(printf '%s' "$START_BODY" | sed -nE 's/.*"detail"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
    if printf '%s' "$DETAIL" | grep -qE '正在|执行|恢复|active|running'; then
      DIE_HINT="  已有升级任务在执行或等待恢复，单飞守卫拒绝了本次请求（US-23）。
  请在 Web 界面「服务 → 升级中心」处理那个任务后再重跑。"
    else
      DIE_HINT="  启动升级被拒绝：$DETAIL
  **环境未被改动**。"
    fi
    die "无法开始升级" "$DIE_HINT"
    ;;
  *)
    DIE_HINT="  启动升级无有效响应：$(printf '%s' "$START_BODY" | head -c 200)
  请在 Web 界面确认任务状态。"
    die "无法开始升级" "$DIE_HINT"
    ;;
esac
ok "升级已启动"

# ── #89 兜底：任务终态快照缺失时以 health 版本到达判定 ──
# 2026-10-14 `.12`/`.14` 实测：升级实际成功，但 post-cleanup 回收任务目录后
# `GET /api/admin/upgrade/status/<id>` 返回 404「升级任务不存在。」——响应体没有
# status 字段，轮询记 unknown 空转到 1800s，误报「超时未收敛」（产品其实成功了）。
# 兜底：无 status 快照时查 `/api/system/health`，版本已到达 TARGET_VERSION 即判成功。
health_reports_target_version() {
  # TARGET_VERSION 为空/unknown 时无法比较：放弃兜底（返回 1 = 未收敛）
  [ -n "${TARGET_VERSION:-}" ] && [ "$TARGET_VERSION" != "unknown" ] || return 1
  local _hb _hv
  _hb="$(curl -s --max-time 10 "${HEALTH_URL:-http://127.0.0.1:8000/api/system/health}" 2>/dev/null || true)"
  _hv="$(printf '%s' "$_hb" | sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  [ -n "$_hv" ] && [ "$_hv" = "$TARGET_VERSION" ]
}

# ── 轮询 ──
printf '\n  升级进行中'
ELAPSED=0
FINAL_STATUS=""
CONVERGED_VIA_HEALTH=0
while [ "$ELAPSED" -lt "$POLL_TIMEOUT" ]; do
  STATUS_BODY="$(curl -s --max-time 20 "$BASE_URL/api/admin/upgrade/status/$TASK_ID" "${AUTH[@]}" 2>/dev/null || true)"
  STATUS="$(printf '%s' "$STATUS_BODY" | sed -nE 's/.*"status"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  [ -n "$STATUS" ] || STATUS="unknown"
  printf '.'
  case "$STATUS" in
    succeeded|success)  FINAL_STATUS="$STATUS"; break ;;
    failed|rolled_back|rollback_failed|recovery_required|    runner_restarting)
      # runner_restarting 是组件升级的正常中间态；平台升级遇到则继续等
      if [ "$STATUS" = "runner_restarting" ]; then FINAL_STATUS=""; else FINAL_STATUS="$STATUS"; break; fi
      ;;
  esac
  # #89：无 status 快照（404/字段缺失）时兜底查 health——版本已到达目标即判成功，
  # 不再空转到 1800s 误报。health 暂不可达（升级中 web-api 重启）则继续轮询。
  if [ "$STATUS" = "unknown" ] && health_reports_target_version; then
    CONVERGED_VIA_HEALTH=1
    FINAL_STATUS="succeeded"
    break
  fi
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done
printf '\n\n'

# #89：超时前的最后一线——全程快照缺失（产物被回收）但 health 已到达目标版本
if [ -z "$FINAL_STATUS" ] && health_reports_target_version; then
  CONVERGED_VIA_HEALTH=1
  FINAL_STATUS="succeeded"
fi

# ── 结果 ──
if [ "$FINAL_STATUS" = "succeeded" ] || [ "$FINAL_STATUS" = "success" ]; then
  NEW_HEALTH="$(curl -s --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
  NEW_VERSION="$(printf '%s' "$NEW_HEALTH" | sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  NEW_RUNNER="$(printf '%s' "$NEW_HEALTH" | sed -nE 's/.*"runner_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  CLEANUP_ID="$(printf '%s' "$STATUS_BODY" | sed -nE 's/.*"post_upgrade_cleanup_task_id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  if [ "$CONVERGED_VIA_HEALTH" -eq 1 ]; then
    printf '  说明：任务终态快照缺失（产物已被升级后清理回收），已以 health 版本到达 %s 判定升级成功。\n' "${NEW_VERSION:-$TARGET_VERSION}"
  fi
  c_green "════════════════════════════════════════════════"
  c_green " 升级成功"
  c_green "════════════════════════════════════════════════"
  printf '\n'
  printf '  平台版本：%s → %s\n' "${CURRENT_VERSION:-unknown}" "${NEW_VERSION:-unknown}"
  printf '  Runner   ：%s → %s\n' "${CURRENT_RUNNER:-unknown}" "${NEW_RUNNER:-unknown}"
  if [ -n "$CLEANUP_ID" ]; then
    printf '  旧环境清理任务：%s\n' "$CLEANUP_ID"
  fi
  printf '\n'
  printf '  建议自检（与升级后清理无关，确认真实可用）：\n'
  printf '    1) curl -s %s | 检查 ok=true 与三项 checks\n' "$HEALTH_URL"
  printf '    2) docker ps 确认 5 个容器均为 Up\n'
  printf '    3) 浏览器打开 http://<本机IP>:8080 能登录\n'
  printf '    4) 服务 → 升级中心 任务状态为成功、无失败任务\n'
  printf '    5) 旧环境目录已清理：/opt/smartx-storage-forecast、/data/upgrades 应不存在\n'
  printf '    6) 数据库完整：docker exec <web-api> python -c "import sqlite3;print(sqlite3.connect(\x27/data/smartx.db\x27).execute(\x27PRAGMA integrity_check\x27).fetchone())"\n'
  printf '    7) 业务数据计数未变（升级不应改动数据）\n'
  printf '    8) 升级后自动采集已触发或可手动触发一次\n'
  printf '\n'
else
  c_red "════════════════════════════════════════════════"
  c_red " 升级未成功（终态：${FINAL_STATUS:-超时未收敛}）"
  c_red "════════════════════════════════════════════════"
  printf '\n'
  printf '  任务 ID：%s\n' "$TASK_ID"
  printf '  现场信息：\n'
  printf '    1) 任务详情：curl -s %s/api/admin/upgrade/status/%s -H "Authorization: Bearer <token>"\n' "$BASE_URL" "$TASK_ID"
  printf '    2) Web 界面：服务 → 升级中心，查看该任务的步骤与日志\n'
  printf '    3) 容器日志：docker logs --tail=200 <web-api 容器>\n'
  printf '\n'
  case "$FINAL_STATUS" in
    recovery_required|runner_restarting)
      printf '  处理建议：任务需要人工确认。在 Web 界面选择「继续执行」或「标记失败」。\n'
      printf '  若升级已改动了环境但旧环境未清理，标记失败后请**重新上传并再跑一次完整升级**，\n'
      printf '  由升级后清理（post-cleanup）收尾（US-27）。\n'
      ;;
    rolled_back|rollback_failed)
      printf '  处理建议：平台已尝试自动回滚。请查看任务日志确认回滚结果；\n'
      printf '  若回滚失败，请在 Web 界面按现场情况处理，必要时保留备份后重装。\n'
      ;;
    failed)
      printf '  处理建议：早期动作失败通常**未改动环境**（如镜像校验失败）。\n'
      printf '  修正原因（包完整性、磁盘空间）后可直接重跑本脚本。\n'
      ;;
    *)
      printf '  处理建议：任务未在 %s 秒内收敛。请在 Web 界面确认任务是否仍在执行；\n' "$POLL_TIMEOUT"
      printf '  若 runner 已不再持有任务，用「标记失败」结束它，再重跑本脚本。\n'
      ;;
  esac
  printf '\n'
  exit 1
fi

# ── 可选：runner 组件升级（必须在平台升级成功之后）──
if [ -n "$RUNNER_PACKAGE" ]; then
  printf '\n'
  if [ ! -f "$RUNNER_PACKAGE" ]; then
    warn "runner 组件包不存在，跳过：$RUNNER_PACKAGE"
  else
    # US-04 硬拦截（pending #94）：平台 < v0.5.3 时做 runner 组件升级会**停掉刚启动的新 runner**
    # （实测 SIGKILL exit=137 → handoff 死循环 → 心跳停摆 → 之后所有平台升级被心跳预检查拒绝，
    # 且 docker start 救不回来）。交付 README 早有警告，但只有警告 = 现场照样踩；这里改成可执行拦截。
    # 正常路径（先升平台、再 --with-runner）此时平台已是新版本，不受影响。
    PLATFORM_NOW="$(curl -s --max-time 10 "${HEALTH_URL:-$BASE_URL/api/system/health}" 2>/dev/null \
      | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    case "$PLATFORM_NOW" in
      v0.5.0|v0.5.1|v0.5.1u1|v0.5.1u2|v0.5.2)
        fail "当前平台 $PLATFORM_NOW 不支持先做 runner 组件升级。"
        info "旧平台的 web-api 会无条件 stop 掉刚启动的新 runner（实测 SIGKILL、心跳停摆，"
        info "之后所有平台升级都会被「未检测到 upgrade-runner 心跳」拒绝）。"
        info "请先把平台升到 v0.5.3 及以上（本脚本默认只升平台），再单独执行组件升级。"
        exit 1 ;;
    esac
    # 等平台升级后的清理任务（post-cleanup）收敛，再发起 runner 组件升级。
    # 原因：单飞守卫（US-23）会拒绝"还有任务在跑"时发起的新任务。平台升级返回 succeeded 时，
    # post-cleanup 往往刚被创建、仍在 pending/running，此时直接升级 runner 必然 400。
    printf '  ── 等待升级后清理（post-cleanup）收敛 ──\n'
    SKIP_CLEANUP_WAIT=0
    if [ "$CONVERGED_VIA_HEALTH" -eq 1 ] && [ -z "$CLEANUP_ID" ]; then
      # #89：经 health 兜底判成功时任务快照已缺失，拿不到 post-cleanup 任务 ID，
      # 等下去只会空转到超时；如实说明并继续（被单飞守卫拒绝时按既有指引重试）。
      # CLEANUP_WAITED=-1 = 「已收敛/跳过」哨兵，避免下面误报「未在时限内收敛」。
      info "任务快照已被回收，无法观察升级后清理任务，跳过等待"
      SKIP_CLEANUP_WAIT=1
      CLEANUP_WAITED=-1
    else
      CLEANUP_WAITED=0
    fi
    while [ "$SKIP_CLEANUP_WAIT" -eq 0 ] && [ "$CLEANUP_WAITED" -lt "$POLL_TIMEOUT" ]; do
      PC_BODY="$(curl -s --max-time 20 "$BASE_URL/api/admin/upgrade/post-cleanup/$TASK_ID" "${AUTH[@]}" 2>/dev/null || true)"
      PC_STATUS="$(printf '%s' "$PC_BODY" | sed -nE 's/.*"status"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
      [ -n "$PC_STATUS" ] || PC_STATUS="unknown"
      case "$PC_STATUS" in
        not_required|succeeded|success)
          printf '\n'
          ok "升级后清理已收敛（$PC_STATUS）"
          CLEANUP_WAITED=-1
          break
          ;;
        failed|cancelled|rolled_back|rollback_failed|recovery_required)
          # 清理失败不影响 runner 组件升级（runner 是独立组件），继续但如实告知。
          printf '\n'
          warn "升级后清理终态为 $PC_STATUS（不影响 runner 组件升级，继续）"
          CLEANUP_WAITED=-1
          break
          ;;
      esac
      printf '.'
      sleep "$POLL_INTERVAL"
      CLEANUP_WAITED=$((CLEANUP_WAITED + POLL_INTERVAL))
    done
    if [ "$CLEANUP_WAITED" -ge 0 ]; then
      printf '\n'
      warn "升级后清理未在 ${POLL_TIMEOUT}s 内收敛，仍尝试 runner 组件升级；若被单飞守卫拒绝请稍后重试"
    fi

    printf '\n'
    printf '  ── 可选：runner 组件升级 ──\n'
    RU_BODY="$(curl -s --max-time 900 -X POST "$BASE_URL/api/admin/component-upgrade/upload" \
      "${AUTH[@]}" -F "file=@$RUNNER_PACKAGE" 2>/dev/null || true)"
    RU_TASK="$(printf '%s' "$RU_BODY" | sed -nE 's/.*"task_id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
    if [ -z "$RU_TASK" ]; then
      warn "runner 组件包上传失败，跳过：$(printf '%s' "$RU_BODY" | head -c 200)"
    else
      curl -s --max-time 300 -X POST "$BASE_URL/api/admin/component-upgrade/precheck/$RU_TASK" "${AUTH[@]}" >/dev/null 2>&1 || true
      RU_START="$(curl -s --max-time 180 -X POST "$BASE_URL/api/admin/component-upgrade/start/$RU_TASK" "${AUTH[@]}" 2>/dev/null || true)"
      case "$RU_START" in
        *'"status":"succeeded"'*|*'"status":"success"'*|*'"status":"running"'*)
          ok "runner 组件升级已提交（任务 $RU_TASK）"
          info "runner 重启期间 API 短暂不可用属正常，稍后用 health 接口确认："
          info "  curl -s $HEALTH_URL"
          ;;
        *)
          # US-23 单飞守卫拒绝是最常见原因，给出可操作的下一步而不是只报错。
          case "$RU_START" in
            *'正在执行'*|*'需要恢复'*)
              warn "runner 组件升级被单飞守卫拒绝（仍有升级/清理任务未收敛）：$(printf '%s' "$RU_START" | head -c 200)"
              info "先在 Web 界面「升级中心」确认无 running 任务（必要时对卡住任务「标记失败」），再单独执行："
              info "  bash upgrade/upgrade.sh --with-runner <组件包>"
              ;;
            *)
              warn "runner 组件升级未成功：$(printf '%s' "$RU_START" | head -c 200)"
              info "平台升级已完成，runner 保持 $NEW_RUNNER，不影响使用；可稍后单独重试。"
              ;;
          esac
          ;;
      esac
    fi
  fi
fi

exit 0
