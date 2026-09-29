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

# ── 轮询 ──
printf '\n  升级进行中'
ELAPSED=0
FINAL_STATUS=""
while [ "$ELAPSED" -lt "$POLL_TIMEOUT" ]; do
  STATUS_BODY="$(curl -s --max-time 20 "$BASE_URL/api/admin/upgrade/status/$TASK_ID" "${AUTH[@]}" 2>/dev/null || true)"
  STATUS="$(printf '%s' "$STATUS_BODY" | sed -nE 's/.*"status"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  [ -n "$STATUS" ] || STATUS="unknown"
  printf '.'
  case "$STATUS" in
    succeeded|success)  FINAL_STATUS="$STATUS"; break ;;
    failed|rolled_back|rollback_failed|recovery_required|runner_restarting)
      # runner_restarting 是组件升级的正常中间态；平台升级遇到则继续等
      if [ "$STATUS" = "runner_restarting" ]; then FINAL_STATUS=""; else FINAL_STATUS="$STATUS"; break; fi
      ;;
  esac
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done
printf '\n\n'

# ── 结果 ──
if [ "$FINAL_STATUS" = "succeeded" ] || [ "$FINAL_STATUS" = "success" ]; then
  NEW_HEALTH="$(curl -s --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
  NEW_VERSION="$(printf '%s' "$NEW_HEALTH" | sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  NEW_RUNNER="$(printf '%s' "$NEW_HEALTH" | sed -nE 's/.*"runner_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  CLEANUP_ID="$(printf '%s' "$STATUS_BODY" | sed -nE 's/.*"post_upgrade_cleanup_task_id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
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
    # 等平台升级后的清理任务（post-cleanup）收敛，再发起 runner 组件升级。
    # 原因：单飞守卫（US-23）会拒绝"还有任务在跑"时发起的新任务。平台升级返回 succeeded 时，
    # post-cleanup 往往刚被创建、仍在 pending/running，此时直接升级 runner 必然 400。
    printf '  ── 等待升级后清理（post-cleanup）收敛 ──\n'
    CLEANUP_WAITED=0
    while [ "$CLEANUP_WAITED" -lt "$POLL_TIMEOUT" ]; do
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
