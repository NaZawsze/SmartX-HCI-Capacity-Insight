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
#   bash compose-guard.sh env-check <env_file> <compose_file> <service> [project] [ack]
#   bash compose-guard.sh env-ack  <env_file>
#   bash compose-guard.sh check <env_file> <compose_file> [project]
#   bash compose-guard.sh write <env_file> <compose_file>

# 标记键。与 offline/release compose 往**容器**注入的 SMARTX_COMPOSE_FILE
# 是两回事：那个是容器内可见的环境变量，本键只存在于宿主 .env。
COMPOSE_GUARD_MARKER_KEY="SMARTX_COMPOSE_FILE_ACTIVE"

# .env 内容指纹标记（US-42 / 2026-10-04）。与上面的变体标记是两回事：
# 变体标记防「同一 project 混用不同 compose 文件」；本键防「.env 改了之后
# 自己不知道重建会影响谁」。
#
# 为什么需要：Compose 的 config-hash 把 env_file 的**内容**算进去，.env 一改
# 所有引用它的服务哈希都变。再叠加 depends_on，`docker compose up -d <单个服务>`
# 会连带重建依赖链上的其他服务。`.14` 实测（2026-10-04）：只想重建
# collector-worker，prometheus 的容器 ID 也变了（f260269773da7 → 45db5a1273dc）。
# 当次无故障，但与 2026-09-30 `.3` 事故（意外 recreate 打死运行中容器）
# 同属一类——事前无人知晓才是真正的成本。
COMPOSE_GUARD_ENV_SHA_KEY="SMARTX_ENV_FILE_SHA256"

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

# ── .env 内容指纹：读 / 写 ──────────────────────────────────────

# 读 .env 里记录的 sha。绝不用 source/eval .env（同 compose_guard_marker 的理由）。
compose_guard_env_sha() {
  _env="${1:-}"
  [ -n "$_env" ] && [ -f "$_env" ] || return 0
  sed -n "s/^${COMPOSE_GUARD_ENV_SHA_KEY}=//p" "$_env" 2>/dev/null \
    | tail -n 1 \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/'
}

# 算 .env 当前 sha。**排除守卫自己的两个标记键**：否则每写一次标记就改一次 .env，
# sha 随之变化，下一次检查会误报「.env 变了」——自激循环。
compose_guard_env_current_sha() {
  _env="${1:-}"
  [ -n "$_env" ] && [ -f "$_env" ] || return 0
  if command -v sha256sum >/dev/null 2>&1; then
    grep -vE "^(${COMPOSE_GUARD_MARKER_KEY}|${COMPOSE_GUARD_ENV_SHA_KEY})=" "$_env" \
      | sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    grep -vE "^(${COMPOSE_GUARD_MARKER_KEY}|${COMPOSE_GUARD_ENV_SHA_KEY})=" "$_env" \
      | shasum -a 256 | cut -d' ' -f1
  else
    printf ''
  fi
}

# 把当前 sha 写回 .env（幂等；值未变则不写，避免无谓的 mtime 变动）。
compose_guard_env_sha_write() {
  _env="${1:-}"
  [ -n "$_env" ] || return 1
  [ -f "$_env" ] || return 1
  _cur="$(compose_guard_env_sha "$_env")"
  _now="$(compose_guard_env_current_sha "$_env")"
  [ -z "$_now" ] && return 0
  [ "$_cur" = "$_now" ] && return 0
  _tmp="$(mktemp "${TMPDIR:-/tmp}/compose-guard-env.XXXXXX")" || return 1
  if grep -q "^${COMPOSE_GUARD_ENV_SHA_KEY}=" "$_env" 2>/dev/null; then
    sed "s|^${COMPOSE_GUARD_ENV_SHA_KEY}=.*|${COMPOSE_GUARD_ENV_SHA_KEY}=${_now}|" "$_env" > "$_tmp"
  else
    cat "$_env" > "$_tmp"
    [ -s "$_tmp" ] && [ "$(tail -c 1 "$_tmp" | wc -l | tr -d ' ')" = "0" ] && printf '\n' >> "$_tmp"
    printf '%s=%s\n' "$COMPOSE_GUARD_ENV_SHA_KEY" "$_now" >> "$_tmp"
  fi
  _perm="$(stat -c '%a' "$_env" 2>/dev/null || stat -f '%Lp' "$_env" 2>/dev/null || echo '')"
  cat "$_tmp" > "$_env" || { rm -f "$_tmp"; return 1; }
  [ -n "$_perm" ] && chmod "$_perm" "$_env" 2>/dev/null
  rm -f "$_tmp"
}

# 从 compose 文件解析「谁 depends_on 谁」，输出 service:dep1,dep2 列表。
# 用法：compose_guard_depends_on <compose_file> <service>
compose_guard_depends_on() {
  _file="${1:-}"
  _svc="${2:-}"
  [ -n "$_file" ] && [ -f "$_file" ] && [ -n "$_svc" ] || return 0
  awk -v target="$_svc" '
    /^  [A-Za-z0-9_-]+:[[:space:]]*$/ {
      svc=$1; sub(/:$/, "", svc); inSvc = (svc == target); next
    }
    inSvc && /^[[:space:]]+depends_on:/ { inDep=1; next }
    inDep && /^[[:space:]]+-[[:space:]]*/ {
      d=$0; sub(/^[[:space:]]*-[[:space:]]*/, "", d); gsub(/["\047]/, "", d)
      if (d != "") { if (out != "") out = out ","; out = out d }
      next
    }
    inDep && /^[[:space:]]+[A-Za-z0-9_-]+:/ { inDep=0 }
    END { print out }
  ' "$_file"
}

# .env 变更事前告警（US-42）。
# 0 = 放行（含「首次记录」），3 = 检出 .env 已变更且未确认。
#
# 为什么是「告警」而不是「拒绝」：.env 变更本身是合法运维动作（换 Tower 地址、
# 改管理员密码、调告警阈值）。真正要拦的是「不知道会连带重建谁」。
# 故默认打印受影响的依赖闭包 + 确认方式；确实要执行时用 --env-change-ack 放行。
compose_guard_env_change_check() {
  _env="${1:-}"
  _compose_file="${2:-}"
  _target_service="${3:-}"
  _project="${4:-smartx-hci-capacity-insight}"
  _ack="${5:-}"

  [ -n "$_env" ] && [ -f "$_env" ] || return 0
  _recorded="$(compose_guard_env_sha "$_env")"
  _current="$(compose_guard_env_current_sha "$_env")"
  [ -z "$_current" ] && return 0

  # 首次运行（既有安装没有这个键）：记录并放行，不阻断任何存量环境。
  if [ -z "$_recorded" ]; then
    compose_guard_env_sha_write "$_env" || true
    _cg_yellow "compose 守卫：已记录 .env 内容指纹（${COMPOSE_GUARD_ENV_SHA_KEY}），后续 .env 变更会在重建前提示。"
    return 0
  fi

  [ "$_recorded" = "$_current" ] && return 0

  # 变了但调用方没给目标服务（拿不到依赖闭包）：只提示存在变更。
  _cg_yellow "════════════════════════════════════════════════════════════════"
  _cg_yellow "compose 守卫：.env 已变更 —— 重建前请确认影响范围"
  _cg_yellow "════════════════════════════════════════════════════════"
  _cg_yellow "  project      : ${_project}"
  _cg_yellow "  记录时的指纹 : ${_recorded}"
  _cg_yellow "  当前指纹     : ${_current}"
  _cg_yellow ""
  _cg_yellow "  为什么必须提醒：Compose 的 config-hash 计入 env_file 的**内容**，"
  _cg_yellow "  .env 一改，所有引用它的服务哈希都变；再叠加 depends_on，"
  _cg_yellow "  'up -d <单个服务>' 会连带重建依赖链上的其他服务。"

  if [ -n "$_target_service" ] && [ -f "$_compose_file" ]; then
    _cg_yellow ""
    _cg_yellow "  本次目标服务: ${_target_service}"
    _cg_yellow "  依赖闭包（这些会被连带重建）:"
    _front="$_target_service"
    _seen=" $_front "
    while [ -n "$_front" ]; do
      _cur="$_front"; _front=""
      for _d in $(compose_guard_depends_on "$_compose_file" "$_cur"); do
        case " $_seen " in *" $_d "*) continue;; esac
        _seen="$_seen $_d "
        _front="$_front $_d"
      done
    done
    for _s in $_seen; do
      if [ "$_s" = "$_target_service" ]; then
        _cg_yellow "    - ${_s}（你指定的）"
      else
        _cg_yellow "    - ${_s} ← 连带重建"
      fi
    done
  else
    _cg_yellow ""
    _cg_yellow "  （未传入目标服务，无法列出依赖闭包；任何引用 .env 的服务都可能被重建）"
  fi

  _cg_yellow ""
  _cg_yellow "  两条可选路径："
  _cg_yellow "  1) 确认无误、就是要重建：加 --env-change-ack 显式确认后重跑。"
  _cg_yellow "  2) 不想重建：把 .env 改回原内容，或只用 'docker compose up -d' 之外的"
  _cg_yellow "     手段（如 docker restart <容器>，不触发 recreate）。"
  _cg_yellow "  确认后可用 'bash compose-guard.sh env-ack <env>' 刷新指纹基线。"
  _cg_yellow ""

  if [ "$_ack" = "1" ] || [ "$_ack" = "true" ]; then
    compose_guard_env_sha_write "$_env" || true
    _cg_yellow "  已确认 --env-change-ack，指纹基线已刷新为当前内容。"
    return 0
  fi
  return 3
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
    env-sha)
      _v="$(compose_guard_env_sha "${1:-}")"
      _c="$(compose_guard_env_current_sha "${1:-}")"
      printf '记录=%s\n当前=%s\n' "${_v:-(未设置)}" "${_c:-(无法计算)}"
      ;;
    env-check)
      # 显式确认用**具名 flag**而不是第 5 个位置参数——原先把 ack 放在 project 之后，
      # 调用方照着告警文案传参会落到 project 位上，ack 永远为空（2026-10-04 自测发现）。
      _ack=""
      _rest=""
      for _a in "$@"; do
        case "$_a" in
          --env-change-ack) _ack=1 ;;
          *) _rest="${_rest} ${_a}" ;;
        esac
      done
      # shellcheck disable=SC2086
      set -- $_rest
      compose_guard_env_change_check "${1:-}" "${2:-}" "${3:-}" "${4:-smartx-hci-capacity-insight}" "$_ack"
      ;;
    env-ack) compose_guard_env_sha_write "${1:-}" ;;
    *) printf '用法: %s {show <env>|check <env> <compose> [project]|write <env> <compose>|env-sha <env>|env-check <env> <compose_file> <service> [project] [--env-change-ack]|env-ack <env>}\n' "$0" >&2; exit 1 ;;
  esac
fi
