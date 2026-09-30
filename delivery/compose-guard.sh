#!/usr/bin/env bash
# US-37 守卫：阻止同一 compose project 混用不同 compose 变体。
#
# 背景：仓库有 4 个 compose 变体（docker-compose.yml / .offline.yml /
# .release.yml / .upgrade.yml），共享同一个 project 名，但服务定义不同 →
# config-hash 必然不同 → 用错变体执行 up/down/restart 会触发 Docker
# recreate，旧容器被 SIGKILL（exit 137、OOMKilled=false），造成服务中断。
# 2026-09-30 .3 事故即此因。
#
# 本脚本**自包含**：不 source 任何 lib/（交付目录没有 lib/），
# 同一份内容会被复制进 install/ 与 upgrade/ 两个目录。
#
# 用法（source 后调用函数）：
#   source compose-guard.sh
#   compose_guard_resolve   "$ENV_FILE" "$PROJECT" "$COMPOSE_FILE"   # 地面真相回填标记
#   compose_guard_check     "$ENV_FILE" "$COMPOSE_FILE" "$PROJECT"   # 0 放行 / 2 拒绝
#   compose_guard_down_then_switch "$ENV_FILE" "$PROJECT_DIR" "$PROJECT" "$COMPOSE_FILE"
#
# 独立执行（诊断用）：
#   bash compose-guard.sh show  <env_file>
#   bash compose-guard.sh check <env_file> <compose_file> [project]
#   bash compose-guard.sh write <env_file> <compose_file>

# 标记键。与 offline/release compose 往**容器**注入的 SMARTX_COMPOSE_FILE
# 是两回事：那个是容器内可见的环境变量，本键只存在于宿主 .env。
COMPOSE_GUARD_MARKER_KEY="SMARTX_COMPOSE_FILE_ACTIVE"

# 哨兵服务：优先用 web-api，不存在时退化到 project 标签查询。
COMPOSE_GUARD_SENTINEL_SERVICE="web-api"

_cg_red()   { printf '%s\n' "$*" >&2; }
_cg_yellow() { printf '%s\n' "$*" >&2; }

# 从 .env 读标记值。绝不用 source/eval .env —— 那是任意内容执行面。
# 输出：标记值；未设置则输出空串。
compose_guard_marker() {
  _env="${1:-}"
  [ -n "$_env" ] && [ -f "$_env" ] || return 0
  sed -n "s/^${COMPOSE_GUARD_MARKER_KEY}=//p" "$_env" 2>/dev/null \
    | tail -n 1 \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# 只取 basename，使「相对文件名」与「绝对路径」可以比较。
_cg_basename() { basename -- "${1:-}"; }

# ── 地面真相：运行中容器实际使用的 compose 文件 ──────────────────
# Docker 把它写在 com.docker.compose.project.config_files 标签里（绝对路径）。
# 项目已有读 compose 标签的先例：backend/app/upgrade_runner/actions.py、
# backend/app/upgrade/service/verification.py。
#
# 输出：compose 文件 basename；判不出则空串。
compose_guard_detect_running() {
  _project="${1:-}"
  [ -n "$_project" ] || return 0
  command -v docker >/dev/null 2>&1 || return 0
  docker ps --quiet --filter "label=com.docker.compose.project=${_project}" \
      --filter "label=com.docker.compose.service=${COMPOSE_GUARD_SENTINEL_SERVICE}" \
    2>/dev/null | head -n 1 | while read -r _cid; do
      [ -n "$_cid" ] || continue
      docker inspect --format \
        '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$_cid" 2>/dev/null
    done | tr ',' '\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    | grep -v '^$' | head -n 1 | while read -r _p; do _cg_basename "$_p"; done
}

# 把标记写入 .env（存在则原地替换，不存在则追加）。保持原权限。
compose_guard_write() {
  _env="${1:-}"
  _compose="$(_cg_basename "${2:-}")"
  [ -n "$_env" ] || return 1
  [ -n "$_compose" ] || return 1
  if [ ! -f "$_env" ]; then
    _cg_red "compose 守卫：无法写入标记，.env 不存在：$_env"
    return 1
  fi
  _perm="$(stat -c '%a' "$_env" 2>/dev/null || stat -f '%Lp' "$_env" 2>/dev/null || echo '')"
  _tmp="$(mktemp "${TMPDIR:-/tmp}/compose-guard.XXXXXX")" || return 1
  if grep -q "^${COMPOSE_GUARD_MARKER_KEY}=" "$_env" 2>/dev/null; then
    sed "s|^${COMPOSE_GUARD_MARKER_KEY}=.*|${COMPOSE_GUARD_MARKER_KEY}=${_compose}|" "$_env" > "$_tmp"
  else
    cat "$_env" > "$_tmp"
    # 末尾补一个换行，避免与原文件最后一行粘连
    [ -s "$_tmp" ] && [ "$(tail -c 1 "$_tmp" | wc -l | tr -d ' ')" = "0" ] && printf '\n' >> "$_tmp"
    printf '%s=%s\n' "$COMPOSE_GUARD_MARKER_KEY" "$_compose" >> "$_tmp"
  fi
  cat "$_tmp" > "$_env" && rm -f "$_tmp"
  [ -n "$_perm" ] && chmod "$_perm" "$_env"
  return 0
}

# 标记解析 / 回填（§2.1.1）：
#   已有标记        → 保持不变
#   无标记 + 容器在跑 → 取容器 config_files 标签的 basename（地面真相）
#   无标记 + 无容器  → 取本次要用的 $COMPOSE_FILE
# 输出：最终标记值。
compose_guard_resolve() {
  _env="${1:-}"
  _project="${2:-}"
  _compose="$(_cg_basename "${3:-}")"
  _cur="$(compose_guard_marker "$_env")"
  if [ -n "$_cur" ]; then
    printf '%s\n' "$_cur"
    return 0
  fi
  if [ -z "$_compose" ]; then
    return 0
  fi
  _detected="$(compose_guard_detect_running "$_project")"
  if [ -n "$_detected" ]; then
    _cg_yellow "compose 守卫：.env 无 ${COMPOSE_GUARD_MARKER_KEY}，但检测到 project=${_project} 正在运行，"
    _cg_yellow "  地面真相（容器 compose 标签）= ${_detected} → 据此回填标记。"
  else
    _detected="$_compose"
  fi
  compose_guard_write "$_env" "$_detected" >/dev/null 2>&1 || true
  printf '%s\n' "$_detected"
}

# 守卫主判定。0 = 放行，2 = 拒绝。
compose_guard_check() {
  _env="${1:-}"
  _want="$(_cg_basename "${2:-}")"
  _project="${3:-smartx-hci-capacity-insight}"
  _active="$(compose_guard_marker "$_env")"

  if [ -z "$_active" ]; then
    _cg_yellow "compose 守卫：.env 中没有 ${COMPOSE_GUARD_MARKER_KEY}，无法判定当前实例用的哪份 compose，"
    _cg_yellow "  按本次传入的 ${_want} 执行。"
    _cg_yellow "  若该实例由本交付包安装，重跑 install/install.sh 即可补上标记。"
    return 0
  fi
  if [ "$_active" = "$_want" ]; then
    return 0
  fi

  _cg_red "════════════════════════════════════════════════════════════════"
  _cg_red "compose 守卫：拒绝执行 —— compose 变体不一致"
  _cg_red "════════════════════════════════════════════════════════════════"
  _cg_red "  project        : ${_project}"
  _cg_red "  当前实例实际使用: ${_active}   （来自 .env 的 ${COMPOSE_GUARD_MARKER_KEY}）"
  _cg_red "  本次你要求使用  : ${_want}"
  _cg_red ""
  _cg_red "  为什么必须拦：同一个 project 名下混用不同 compose 文件，Docker 判定「配置变了」"
  _cg_red "  会 recreate 容器，旧容器被 SIGKILL（exit 137、OOMKilled=false），服务中断。"
  _cg_red ""
  _cg_red "  三条可选路径："
  _cg_red "  1) 改用正确的 compose（推荐）："
  _cg_red "       docker compose -f ${_active} -p ${_project} <你的操作>"
  _cg_red "  2) 确实要换成 ${_want}：加 --force-compose-switch 显式确认。"
  _cg_red "     它会**先完整停机再换**（down --remove-orphans → up），不会 recreate 冲突，"
  _cg_red "     但**会造成计划内服务中断**。请先确认无业务影响。"
  _cg_red "  3) 先手工完整停机，再换变体："
  _cg_red "       docker compose -f ${_active} -p ${_project} down --remove-orphans"
  _cg_red "  如确认第 ${_active} 份才是误标记、应改成 ${_want}，请编辑 .env 中"
  _cg_red "  ${COMPOSE_GUARD_MARKER_KEY}= 一行后重跑。"
  _cg_red ""
  return 2
}

# --force-compose-switch 的实现：**先完整 down 再 up**，避免 recreate 冲突。
# 用**旧**（active）compose 执行 down，确保停的是当前真正在跑的那套。
compose_guard_down_then_switch() {
  _env="${1:-}"
  _project_dir="${2:-}"
  _project="${3:-}"
  _want="$(_cg_basename "${4:-}")"
  _active="$(compose_guard_marker "$_env")"
  [ -n "$_active" ] || _active="$_want"
  _cg_yellow "compose 守卫：--force-compose-switch —— 完整停机后切换 compose 变体"
  _cg_yellow "  1/2 用当前生效的 ${_active} 停机（不做 recreate）"
  if ! docker compose -f "${_project_dir}/${_active}" -p "$_project" down --remove-orphans; then
    _cg_red "  停机失败，已中止，未做任何变更。"
    return 1
  fi
  _cg_yellow "  2/2 更新标记为 ${_want} 并由调用方启动"
  compose_guard_write "$_env" "$_want" || return 1
  return 0
}

# ── 独立执行模式 ───────────────────────────────────────────────
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  _action="${1:-show}"; shift || true
  case "$_action" in
    show)
      _v="$(compose_guard_marker "${1:-}")"
      [ -n "$_v" ] && printf '%s\n' "$_v" || { printf '(未设置 %s)\n' "$COMPOSE_GUARD_MARKER_KEY"; exit 1; }
      ;;
    check) compose_guard_check "${1:-}" "${2:-}" "${3:-smartx-hci-capacity-insight}" ;;
    write) compose_guard_write "${1:-}" "${2:-}" ;;
    *) printf '用法: %s {show <env>|check <env> <compose> [project]|write <env> <compose>}\n' "$0" >&2; exit 1 ;;
  esac
fi
