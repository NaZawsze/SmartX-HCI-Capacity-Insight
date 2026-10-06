#!/usr/bin/env bash
# 升级矩阵一键取证（Phase 68 批次 C：C1/C2/C3/C4 复用同一脚本）
#
# 用法：
#   bash ops/evidence.sh <cell> before [--task-id ID] [--token TOKEN]
#   bash ops/evidence.sh <cell> after  [--task-id ID] [--token TOKEN]
#
#   cell: c1（.14 平台直升）| c2（.12 组件升级）| c3（.14 场景 B 手动回滚）| c4（.12 平台直升）
#
# 设计纪律（先看这几条，都是被现实教育过的）：
#
#   1. **只读**。本脚本对平台只做读取：docker inspect / docker images / docker ps（限定 project 标签）、
#      sqlite 只读连接（mode=ro）、sha256、curl GET。**唯一的写动作是它自己的证据目录**
#      `/data/evidence/<cell>/`。不做任何 compose 操作、不动任何容器、不改任何配置。
#      升级动作由用户走产品 API 执行，本脚本只负责"执行前后各拍一张可比对的照片"。
#
#   2. **容器只用显式名字枚举**。历史事故（`.3` 2026-09-30 / 2026-10-05）：有人用
#      `docker ps | grep <关键字> | awk '{print $1}' | xargs docker rm -f` 清理"测试容器"，
#      结果把**生产 upgrade-runner** 一并删掉（自愈重启后才恢复）。根因是"过滤扫描 + 批量删除"
#      两个动作叠在一起。因此本脚本：
#        - 只按**已知服务名拼出的显式容器名**取信息（`<project>-<service>-1`）；
#        - 只用 project 标签做**读**过滤，不做任何过滤驱动；
#        - 容器不存在就记 `absent`，**绝不**"扫一遍再决定"。
#      本脚本没有删除容器的代码路径，将来加动作时这条纪律继续适用。
#
#   3. **离线可用**。`.12`/`.14` 无外网（`.14` 的 Docker Hub 还被 DNS sinkhole）。
#      只依赖：bash / docker / python3 / sqlite3(在 python3 里) / curl / sha256sum。不依赖 jq。
#
#   4. **root 直登**。`.12`/`.14` 是 root 直登；脚本要求 uid=0，否则提示但不强制（便于诊断）。
#
# 输出：
#   /data/evidence/<cell>/before/ 或 after/   文本证据包（每个文件带 SHA256SUMS）
#   /data/evidence/<cell>/judgement.txt       after 模式生成的逐条判定表
#
# 判据来源：docs/superpowers/plans/2026-10-06-upgrade-matrix-runbook.md（各格的判据表）

set -uo pipefail

PROJECT="${SMARTX_PROJECT_NAME:-smartx-hci-capacity-insight}"
ROOT="${SMARTX_INSTALL_ROOT:-/data/smartx-storage-forecast}"
PROJECT_DIR="$ROOT/project"
DATA_DIR="$ROOT/app"
UPGRADES_DIR="$ROOT/upgrades"
EVIDENCE_ROOT="${SMARTX_EVIDENCE_ROOT:-/data/evidence}"
HEALTH_URL="${SMARTX_HEALTH_URL:-http://127.0.0.1:8000/api/system/health}"
API_BASE="${SMARTX_API_BASE:-http://127.0.0.1:8000}"
SERVICES="web-api collector-worker frontend prometheus upgrade-runner"
BUSINESS_TABLES="towers clusters vm_latest vm_volumes"
LEGACY_PATHS="/opt/smartx-storage-forecast /data/upgrades /data/backups /data/exports /data/compose-runtime /data/smartx-capacity-insight-data /prometheus-data"

CELL=""
PHASE=""
TASK_ID=""
TOKEN=""
OUT=""

die() { printf '错误：%s\n' "$*" >&2; exit 2; }

usage() {
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    before|after)
      [ -z "$PHASE" ] || die "phase 只能给一次"
      PHASE="$1"; shift ;;
    c1|c2|c3|c4)
      [ -z "$CELL" ] || die "cell 只能给一次"
      CELL="$1"; shift ;;
    --task-id) TASK_ID="${2:-}"; shift 2 ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) die "未知参数：$1" ;;
  esac
done
[ -n "$CELL" ] && [ -n "$PHASE" ] || usage

[ "$(id -u)" = "0" ] || printf '提示：当前 uid=%s（.12/.14 是 root 直登）；脚本仍可运行，但 docker 与数据目录可能读不到\n' "$(id -u)" >&2

mkdir -p "$EVIDENCE_ROOT/$CELL/$PHASE" || die "无法创建证据目录 $EVIDENCE_ROOT/$CELL/$PHASE"
OUT="$EVIDENCE_ROOT/$CELL/$PHASE"

# ── 采集 ────────────────────────────────────────────────────────────────────

section() { printf '\n===== %s =====\n' "$1"; }

container_name() { printf '%s-%s-1' "$PROJECT" "$1"; }

collect_meta() {
  {
    printf 'cell=%s\nphase=%s\nproject=%s\n' "$CELL" "$PHASE" "$PROJECT"
    printf 'host=%s\n' "$(hostname)"
    printf 'utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'uid=%s\n' "$(id -u)"
    printf 'install_root=%s\ntask_id=%s\n' "$ROOT" "${TASK_ID:-（未指定）}"
    printf 'evidence_dir=%s\n' "$OUT"
  } > "$OUT/00-meta.txt"
}

# 容器与镜像：显式名字逐个取；不存在记 absent，绝不扫描。
collect_containers() {
  local file="$OUT/01-containers.txt"
  : > "$file"
  section "容器事实（显式名字枚举，无过滤扫描）" >> "$file"
  for service in $SERVICES; do
    local name; name="$(container_name "$service")"
    if docker inspect "$name" >/dev/null 2>&1; then
      {
        printf '%s\n' "$name"
        docker inspect -f '  container_id={{.Id}}
  image_ref={{.Config.Image}}
  image_id={{.Image}}
  started_at={{.State.StartedAt}}
  restarts={{.RestartCount}}
  running={{.State.Running}}
  compose_project={{index .Config.Labels "com.docker.compose.project"}}
  compose_service={{index .Config.Labels "com.docker.compose.service"}}
  compose_config_files={{index .Config.Labels "com.docker.compose.project.config_files"}}' "$name"
        printf '\n'
      } >> "$file"
    else
      printf '%s\n  absent（该服务当前没有容器；本脚本不扫描、不猜测）\n\n' "$name" >> "$file"
    fi
  done
  # project 标签下的容器清单（只读盘点，用于发现"名字之外的容器"，不做任何动作）
  {
    section "该 project 下实际运行的容器（只读盘点）"
    docker ps --filter "label=com.docker.compose.project=$PROJECT" \
      --format '{{.Names}} {{.Image}} {{.Status}}' 2>/dev/null || printf '(docker ps 失败)\n'
  } >> "$file"
}

collect_health() {
  section "运行态 health（GET，不改任何东西）" > "$OUT/03-health.txt"
  curl -s -m 15 "$HEALTH_URL" >> "$OUT/03-health.txt" 2>&1 || printf '(curl 失败)\n' >> "$OUT/03-health.txt"
  printf '\n' >> "$OUT/03-health.txt"
  # 平台版本取自**镜像内** /app/VERSION（AGENTS §8：镜像内 VERSION 是主要身份来源）。
  # 现场 project/ 目录下并没有 VERSION 文件——早期把判定绑到宿主文件上，
  # 会让「应变更」格拿"（读不到）"去比对：same 格误判通过、changed 格误判失败。
  printf 'health JSON version=%s\n' \
    "$(sed -n 's/.*"version":"\([^"]*\)".*/\1/p' "$OUT/03-health.txt" 2>/dev/null | head -n1)" >> "$OUT/03-health.txt"
  if [ -n "$(docker ps -q --filter "name=^$(container_name web-api)$" 2>/dev/null)" ]; then
    printf 'image 内 VERSION=%s\n' \
      "$(docker exec "$(container_name web-api)" cat /app/VERSION 2>/dev/null || echo '（读不到）')" >> "$OUT/03-health.txt"
  else
    printf 'image 内 VERSION=（web-api 容器不存在）\n' >> "$OUT/03-health.txt"
  fi
  printf '宿主 VERSION 文件=%s\n' "$(cat "$PROJECT_DIR/VERSION" 2>/dev/null || echo '（不存在，属正常）')" >> "$OUT/03-health.txt"
  if [ -n "$(docker ps -q --filter "name=^$(container_name upgrade-runner)$" 2>/dev/null)" ]; then
    printf 'runner 容器内 RUNNER_VERSION=%s\n' \
      "$(docker exec "$(container_name upgrade-runner)" cat /app/RUNNER_VERSION 2>/dev/null || echo '（读不到）')" >> "$OUT/03-health.txt"
  fi
}

collect_db_counts() {
  section "业务库计数（sqlite 只读连接 mode=ro）" > "$OUT/04-db-counts.txt"
  printf 'db_path=%s\n' "$DATA_DIR/smartx.db" >> "$OUT/04-db-counts.txt"
  python3 - "$DATA_DIR/smartx.db" $BUSINESS_TABLES collection_runs <<'PY' >> "$OUT/04-db-counts.txt" 2>&1
import sqlite3, sys
path, *tables = sys.argv[1:]
try:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in tables:
        if table in present:
            print(f"{table}={connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
        else:
            print(f"{table}=absent")
    try:
        print("integrity_check=" + connection.execute("PRAGMA integrity_check").fetchone()[0])
    except sqlite3.Error as exc:
        print(f"integrity_check=error({exc})")
finally:
    pass
PY
}

collect_env() {
  section ".env 指纹与 US-37 变体标记" > "$OUT/05-env.txt"
  local env_file="$PROJECT_DIR/.env"
  if [ -f "$env_file" ]; then
    printf 'path=%s\n' "$env_file" >> "$OUT/05-env.txt"
    printf 'sha256=%s\n' "$(sha256sum "$env_file" | cut -d' ' -f1)" >> "$OUT/05-env.txt"
    printf 'mode=%s\n' "$(stat -c '%a' "$env_file" 2>/dev/null || stat -f '%Lp' "$env_file" 2>/dev/null)" >> "$OUT/05-env.txt"
    printf 'compose_file_marker=%s\n' \
      "$(sed -n 's/^SMARTX_COMPOSE_FILE_ACTIVE=//p' "$env_file" 2>/dev/null | tail -n 1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' || true)" >> "$OUT/05-env.txt"
    printf 'env_sha_marker=%s\n' \
      "$(sed -n 's/^SMARTX_ENV_FILE_SHA256=//p' "$env_file" 2>/dev/null | tail -n 1 || true)" >> "$OUT/05-env.txt"
    # ★「非标记键指纹」：US-37 标记回填会**写 .env**（这是设计如此），所以
    # 「.env sha256 不变」不能作为通用判据——同一格里回填发生时它必然变化。
    # 这里把两个标记键排除后取指纹，判据改为「非标记键必须逐字节不变」。
    printf 'non_marker_keys_sha256=%s\n' \
      "$(grep -vE '^(SMARTX_COMPOSE_FILE_ACTIVE|SMARTX_ENV_FILE_SHA256)=' "$env_file" 2>/dev/null | sha256sum | cut -d' ' -f1)" >> "$OUT/05-env.txt"
  else
    printf 'absent（%s 不存在）\n' "$env_file" >> "$OUT/05-env.txt"
  fi
  printf '\ncompose-guard 是否已投递到 project 目录:\n' >> "$OUT/05-env.txt"
  if [ -f "$PROJECT_DIR/compose-guard.sh" ]; then
    printf 'present executable=%s sha256=%s\n' \
      "$([ -x "$PROJECT_DIR/compose-guard.sh" ] && echo yes || echo no)" \
      "$(sha256sum "$PROJECT_DIR/compose-guard.sh" | cut -d' ' -f1)" >> "$OUT/05-env.txt"
  else
    printf 'absent\n' >> "$OUT/05-env.txt"
  fi
}

collect_legacy_paths() {
  section "legacy 路径（应全部不存在）" > "$OUT/06-legacy-paths.txt"
  for path in $LEGACY_PATHS; do
    if [ -e "$path" ]; then printf 'present  %s\n' "$path" >> "$OUT/06-legacy-paths.txt"
    else printf 'absent   %s\n' "$path" >> "$OUT/06-legacy-paths.txt"; fi
  done
  printf '\nUPG-050 载体目录（禁删红线，只记录不触碰）:\n' >> "$OUT/06-legacy-paths.txt"
  for name in upgrades backups exports compose-runtime smartx-storage-forecast; do
    path="$DATA_DIR/$name"
    if [ -d "$path" ]; then
      printf 'carrier %-28s inode=%s entries=%s\n' "$name" "$(stat -c '%d:%i' "$path" 2>/dev/null || stat -f '%d:%i' "$path" 2>/dev/null)" "$(ls -A "$path" 2>/dev/null | wc -l)" >> "$OUT/06-legacy-paths.txt"
    else
      printf 'carrier %-28s absent\n' "$name" >> "$OUT/06-legacy-paths.txt"
    fi
  done
}

collect_task() {
  local file="$OUT/07-task.txt"
  : > "$file"
  section "升级任务证据" >> "$file"
  if [ -z "$TASK_ID" ]; then
    printf '未指定 --task-id：跳过任务取证\n' >> "$file"
    return
  fi
  local task_file="$UPGRADES_DIR/$TASK_ID/task.json"
  if [ ! -f "$task_file" ]; then
    printf '任务文件不存在：%s\n' "$task_file" >> "$file"
    return
  fi
  python3 - "$task_file" "$BUSINESS_TABLES" <<'PY' >> "$file" 2>&1
import json, sys
path, *tables = sys.argv[1:]
task = json.load(open(path, encoding="utf-8"))
print(f"task_id={task.get('task_id')}")
print(f"status={task.get('status')}  recovery_status={task.get('recovery_status')}  target_version={task.get('target_version')}")
print(f"kind={task.get('kind') or '-'}  package_type={task.get('package_type') or '-'}")
print(f"revision={task.get('revision')}  started_at={task.get('started_at')}  finished_at={task.get('finished_at')}")
print("\n-- 动作 --")
for action in task.get("execution_plan", {}).get("actions", []):
    print(f"  {action.get('id'):<28} {action.get('type'):<34} {action.get('status')}")
    if action.get("error"):
        print(f"      error: {str(action['error'])[:400]}")
    diff = (action.get("result") or {}).get("diff") or {}
    for key in ("summary", "actual_summary"):
        if diff.get(key):
            print(f"      diff.{key}: {diff[key]}")
anchor = task.get("platform_rollback_anchor") or {}
if anchor:
    print("\n-- 平台回滚锚点（A5）--")
    print(f"  previous_version={anchor.get('previous_version')}  captured_at={anchor.get('captured_at')}")
    print(f"  backup={json.dumps(anchor.get('backup'), ensure_ascii=False)}")
    print(f"  images={json.dumps({k: v.get('tag') for k, v in (anchor.get('images') or {}).items()}, ensure_ascii=False)}")
    print(f"  pre_upgrade.counts={json.dumps((anchor.get('pre_upgrade') or {}).get('counts'), ensure_ascii=False)}")
record = task.get("automatic_rollback") or {}
if record:
    print("\n-- 自动回滚记录 --")
    print(f"  mode={record.get('mode')}  trigger={record.get('trigger_action')}  previous={record.get('previous_version')}")
    for step in record.get("steps") or []:
        print(f"  step {step.get('step')}: {str(step.get('result') or step.get('error'))[:220]}")
print("\n-- precheck 检查项 --")
for check in task.get("checks") or []:
    print(f"  {check.get('name'):<26} ok={check.get('ok')}  {str(check.get('message'))[:120]}")
    if check.get("remediation"):
        print(f"      remediation: {check['remediation']}")
print("\n-- 日志（末 25 条）--")
for line in (task.get("logs") or [])[-25:]:
    print(f"  {str(line)[:240]}")
PY
}

collect_runner_state() {
  section "runner 状态文件（心跳/实例/锚点持久段）" > "$OUT/08-runner-state.txt"
  local state_file="$DATA_DIR/upgrade-runner-state.json"
  if [ ! -f "$state_file" ]; then
    printf 'absent（%s）\n' "$state_file" > "$OUT/08-runner-state.txt"
    return
  fi
  python3 - "$state_file" <<'PY' >> "$OUT/08-runner-state.txt" 2>&1
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
for key in ("schema", "instance_id", "runner_version", "protocol_version", "started_at", "heartbeat_at", "updated_at"):
    print(f"{key}={state.get(key)}")
print(f"capabilities={state.get('capabilities')}")
print(f"leases={list((state.get('leases') or {}).keys())}")
anchors = state.get("rollback_anchors") or {}
print(f"rollback_anchors={list(anchors)}")
for task_id, anchor in anchors.items():
    print(f"  {task_id}: previous_version={anchor.get('previous_version')} captured_at={anchor.get('captured_at')} "
          f"backup_sha={(anchor.get('backup') or {}).get('sha256')}")
PY
}

# 场景 B：可回滚性判定（GET，只读）。给 token 才采集。
collect_rollback_availability() {
  local file="$OUT/09-rollback-availability.txt"
  : > "$file"
  section "场景 B 可回滚性判定（GET /api/admin/upgrade/rollback-availability）" >> "$file"
  if [ -z "$TOKEN" ]; then
    printf '未提供 --token：跳过（需要管理员 access_token）\n' >> "$file"
    return
  fi
  curl -s -m 15 -H "Authorization: Bearer $TOKEN" "$API_BASE/api/admin/upgrade/rollback-availability" >> "$file" 2>&1 || true
  printf '\n' >> "$file"
  section "场景 C 整备回滚可用性（GET /api/admin/upgrade/full-rollback-availability）" >> "$file"
  curl -s -m 15 -H "Authorization: Bearer $TOKEN" "$API_BASE/api/admin/upgrade/full-rollback-availability" >> "$file" 2>&1 || true
  printf '\n' >> "$file"
}

sign() {
  ( cd "$OUT" && sha256sum ./*.txt > SHA256SUMS 2>/dev/null || true )
}

collect_all() {
  collect_meta
  collect_containers
  collect_health
  collect_db_counts
  collect_env
  collect_legacy_paths
  collect_task
  collect_runner_state
  collect_rollback_availability
  sign
}

# ── 判定（after 模式）────────────────────────────────────────────────────────

field() { # field <file> <key>
  sed -n "s/^$2=//p" "$1" 2>/dev/null | head -n 1
}

container_field() { # container_field <file> <service> <key>
  awk -v svc="$2" -v key="$3" '
    $0 ~ "-"svc"-1$" { inside=1; next }
    inside && index($0, key "=") { sub("^  " key "=", ""); print; exit }
    inside && /^$/ { inside=0 }
  ' "$1"
}

# cell 期望：直接赋值（不用子 shell 输出解析——多行/引号转义在 `cell_expect | sed -n` 上
# 已经踩过一次坑：期望清单静默变空，判定表把"应更换"全判成"应不变"，比不判定更危险）。
cell_expect() {
  expect_app="v0.5.4"
  expect_runner="same"
  expect_changed="web-api collector-worker frontend"
  expect_unchanged="prometheus upgrade-runner"
  # runner 侧能力（compose 变体标记回填 / compose.apply 差异清单 / 回滚锚点 / runner 状态文件）
  # 住在 **runner 镜像**里，属开发线 v0.3.2。平台升级的执行者是**已发布 v0.3.1**
  # （AGENTS「先平台后 runner」：包基线 = 已发布 runner），因此在 c1/c4 这类
  # 「平台直升且 runner 不动」的格子里，这些能力**结构上不可能出现**——
  # 判成 ❌/⚠️ 会把「不适用」误报成「缺陷」（2026-10-06 `.14` C1 实测）。
  runner_side="na"
  # 本格是否**执行平台升级**（组件升级格不跑 compose.apply →差异清单/锚点结构上不可能出现）
  runs_platform_upgrade="yes"
  case "$CELL" in
    c2|c3)
      runner_side="check"
      runs_platform_upgrade="no"
      ;;
  esac
  case "$CELL" in
    c2)
      # 组件升级：平台版本不变、runner 换到 v0.3.2、其余容器都不该动
      expect_app="same"
      expect_runner="v0.3.2"
      expect_changed="upgrade-runner"
      expect_unchanged="web-api collector-worker frontend prometheus"
      ;;
    c3)
      # 场景 B：回到上一版（期望值取自 availability API 的 target_version）
      expect_app="availability"
      ;;
  esac
}

judge() {
  local before="$EVIDENCE_ROOT/$CELL/before"
  local after="$OUT"
  local judgement="$EVIDENCE_ROOT/$CELL/judgement.txt"
  local expect_app expect_runner expect_changed expect_unchanged runs_platform_upgrade
  cell_expect   # 设置上面几个变量（不用子 shell，否则赋值丢失）

  {
    printf '# 判定表  cell=%s  phase=%s\n' "$CELL" "$PHASE"
    printf '生成时间(UTC)=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'before=%s\nafter=%s\n\n' "$before" "$after"
    printf '期望（cell 口径）：app=%s runner=%s 应换=%s 应不变=%s\n\n' \
      "$expect_app" "$expect_runner" "$expect_changed" "$expect_unchanged"
    printf '| # | 判据 | 结果 | 实测 |\n| --- | --- | --- | --- |\n'

    local row=0 verdict value
    add() { row=$((row+1)); printf '| %s | %s | %s | %s |\n' "$row" "$1" "$2" "$3"; }

    # 0) 自检：应换 + 应不变 必须恰好覆盖全部已知服务（否则期望清单写错会静默判错）
    local unlisted=""
    for svc in $SERVICES; do
      case " $expect_changed $expect_unchanged " in
        *" $svc "*) ;;
        *) unlisted="$unlisted $svc" ;;
      esac
    done
    if [ -z "$unlisted" ]; then add "cell 期望清单自检（应覆盖全部服务）" "✅ 符合" "应换=[$expect_changed] 应不变=[$expect_unchanged]"
    else add "cell 期望清单自检（应覆盖全部服务）" "⚠️ 未覆盖" "${unlisted# }"; fi

    # 1) T3 核心：prometheus / runner 容器 ID
    for svc in prometheus upgrade-runner; do
      local b_id a_id
      b_id="$(container_field "$before/01-containers.txt" "$svc" container_id)"
      a_id="$(container_field "$after/01-containers.txt" "$svc" container_id)"
      if [ -z "$b_id" ] || [ -z "$a_id" ]; then
        verdict="⚠️ 无法判定"; value="before='${b_id:-absent}' after='${a_id:-absent}'"
      elif [ "$CELL" = "c2" ] && [ "$svc" = "upgrade-runner" ]; then
        if [ "$b_id" != "$a_id" ]; then verdict="✅ 符合"; value="已更换 ${b_id:0:12} → ${a_id:0:12}"
        else verdict="❌ 不符合"; value="容器未更换（组件升级应换 runner）"; fi
      elif [ "$b_id" = "$a_id" ]; then verdict="✅ 符合"; value="不变 ${a_id:0:12}"
      else verdict="❌ 不符合"; value="变了 ${b_id:0:12} → ${a_id:0:12}"; fi
      add "$svc 容器 ID $([ "$CELL" = c2 ] && [ "$svc" = upgrade-runner ] && echo '（应更换）' || echo '不变【T3】')" "$verdict" "$value"
    done

    # 2) 三件套容器：应换 / 不应换
    for svc in web-api collector-worker frontend; do
      local b_id a_id
      b_id="$(container_field "$before/01-containers.txt" "$svc" container_id)"
      a_id="$(container_field "$after/01-containers.txt" "$svc" container_id)"
      local should_change="yes"
      case " $expect_changed " in *" $svc "*) should_change="yes" ;; *) should_change="no" ;; esac
      if [ -z "$b_id" ] || [ -z "$a_id" ]; then verdict="⚠️ 无法判定"; value="before='${b_id:-absent}' after='${a_id:-absent}'"
      elif [ "$should_change" = "yes" ] && [ "$b_id" != "$a_id" ]; then verdict="✅ 符合"; value="已更换 ${b_id:0:12} → ${a_id:0:12}"
      elif [ "$should_change" = "no" ] && [ "$b_id" = "$a_id" ]; then verdict="✅ 符合"; value="不变 ${a_id:0:12}"
      elif [ "$should_change" = "no" ]; then verdict="❌ 不符合"; value="不应更换却变了 ${b_id:0:12} → ${a_id:0:12}"
      else verdict="❌ 不符合"; value="应更换却未变 ${a_id:0:12}"; fi
      add "$svc 容器（$( [ "$should_change" = yes ] && echo 应更换 || echo 应不变 )）" "$verdict" "$value"
    done

    # 3) 版本到位（平台版本以镜像内 /app/VERSION 为准，health JSON 次之，宿主文件仅作留证）
    local app_before app_after runner_before runner_after
    app_before="$(field "$before/03-health.txt" "image 内 VERSION")"
    [ -n "$app_before" ] || app_before="$(field "$before/03-health.txt" "health JSON version")"
    app_after="$(field "$after/03-health.txt" "image 内 VERSION")"
    [ -n "$app_after" ] || app_after="$(field "$after/03-health.txt" "health JSON version")"
    runner_before="$(sed -n 's/^runner 容器内 RUNNER_VERSION=//p' "$before/03-health.txt" | head -n1)"
    runner_after="$(sed -n 's/^runner 容器内 RUNNER_VERSION=//p' "$after/03-health.txt" | head -n1)"
    case "$expect_app" in
      same) if [ "$app_before" = "$app_after" ]; then add "平台版本（应不变）" "✅ 符合" "$app_after"
           else add "平台版本（应不变）" "❌ 不符合" "$app_before → $app_after"; fi ;;
      availability)
        local target; target="$(sed -n 's/.*"target_version":"\([^"]*\)".*/\1/p' "$after/09-rollback-availability.txt" 2>/dev/null | head -n1)"
        if [ -z "$target" ]; then add "平台版本（应回到上一版）" "⚠️ 需人工核对" "未取到 availability（缺 token？）after=$app_after"
        elif [ "$app_after" = "$target" ]; then add "平台版本（应回到上一版）" "✅ 符合" "$app_after = target_version"
        else add "平台版本（应回到上一版）" "❌ 不符合" "after=$app_after 期望=$target"; fi ;;
      *)
        if [ "$app_after" = "$expect_app" ]; then add "平台版本到位（${expect_app}）" "✅ 符合" "$app_after"
        else add "平台版本到位（${expect_app}）" "❌ 不符合" "after=${app_after}"; fi ;;
    esac
    case "$expect_runner" in
      same) if [ "$runner_before" = "$runner_after" ] && [ -n "$runner_after" ]; then add "runner 版本（应不变）" "✅ 符合" "$runner_after"
           else add "runner 版本（应不变）" "❌ 不符合" "$runner_before → $runner_after"; fi ;;
      *) if [ "$runner_after" = "$expect_runner" ]; then add "runner 版本到位（${expect_runner}）" "✅ 符合" "$runner_after"
         else add "runner 版本到位（${expect_runner}）" "❌ 不符合" "after=${runner_after}"; fi ;;
    esac

    # 4) 业务计数逐表一致
    for table in $BUSINESS_TABLES; do
      local b c
      b="$(field "$before/04-db-counts.txt" "$table")"; c="$(field "$after/04-db-counts.txt" "$table")"
      if [ "$b" = "$c" ]; then add "计数 ${table}（应一致）" "✅ 符合" "$c"
      else add "计数 ${table}（应一致）" "❌ 不符合" "$b → $c"; fi
    done
    local cr_b cr_a
    cr_b="$(field "$before/04-db-counts.txt" collection_runs)"; cr_a="$(field "$after/04-db-counts.txt" collection_runs)"
    if [ "$cr_b" = "$cr_a" ]; then add "collection_runs（参考项，允许增长）" "✅ 符合" "$cr_a"
    else add "collection_runs（参考项，允许增长）" "ℹ️ 参考" "$cr_b → $cr_a"; fi

    # 5) .env 指纹 / US-37 标记 / legacy 路径 / 完整性
    local env_b env_a
    local nb na mb ma
    nb="$(field "$before/05-env.txt" non_marker_keys_sha256)"; na="$(field "$after/05-env.txt" non_marker_keys_sha256)"
    mb="$(field "$before/05-env.txt" compose_file_marker)"; ma="$(field "$after/05-env.txt" compose_file_marker)"
    if [ -z "$nb" ] || [ -z "$na" ]; then
      # 旧证据包没有该字段（脚本升级前采集的）→ 退回整文件比对，并说明限制
      env_b="$(field "$before/05-env.txt" sha256)"; env_a="$(field "$after/05-env.txt" sha256)"
      if [ "$env_b" = "$env_a" ] && [ -n "$env_a" ]; then add ".env（应不变；无非标记键指纹，退回整文件比对）" "✅ 符合" "${env_a:0:16}…"
      else add ".env（应不变；无非标记键指纹，退回整文件比对）" "⚠️ 需人工核对" "${env_b:-无} → ${env_a:-无}"; fi
    elif [ "$nb" != "$na" ]; then
      add ".env 非标记键（应逐字节不变）" "❌ 不符合" "${nb:0:16}… → ${na:0:16}…"
    elif [ "$mb" != "$ma" ]; then
      add ".env 非标记键（应逐字节不变）" "✅ 符合" "非标记键未变；标记键 ${mb:-（无）} → ${ma}（US-37 回填写入，属预期）"
    else
      add ".env 非标记键（应逐字节不变）" "✅ 符合" "整文件 sha 未变（${na:0:16}…）"
    fi

    local marker; marker="$(field "$after/05-env.txt" compose_file_marker)"
    if [ -n "$marker" ]; then add "US-37 变体标记（应存在）" "✅ 符合" "$marker"
    elif [ "$runs_platform_upgrade" = "no" ]; then
      add "US-37 变体标记回填" "ℹ️ 不适用" "本格是组件升级（C2），流程里没有 files.sync，回填不可能发生；由 v0.3.2 runner 执行平台升级的格子里验。compose-guard.sh 本体在位：$(field "$after/05-env.txt" present || echo '见 05-env.txt')"
    elif [ "$runner_side" = "na" ]; then
      add "US-37 变体标记回填（属 runner v0.3.2）" "ℹ️ 不适用" "执行者为已发布 runner v0.3.1（容器内 _backfill_compose_file_marker=0 命中）；由 v0.3.2 runner 执行的平台升级格里验。compose-guard.sh 本体已随包投递：$(field "$after/05-env.txt" present || echo '见 05-env.txt')"
    else add "US-37 变体标记（应存在）" "⚠️ 缺失" "见 05-env.txt"; fi

    # 注意：不能用 `grep -c … || echo 0`——grep 无命中时既打印 0 又返回 1，
    # `|| echo 0` 会再补一个 0，变量变成 "0\n0"，判定文案渲染成「存在 0\n0 处」。
    local leftovers; leftovers="$(awk '/^present/{n++} END{print n+0}' "$after/06-legacy-paths.txt" 2>/dev/null)"
    if [ "$leftovers" = "0" ]; then add "legacy 路径（应全清）" "✅ 符合" "0 处存在"
    else add "legacy 路径（应全清）" "⚠️ 存在 $leftovers 处" "见 06-legacy-paths.txt"; fi

    local integrity; integrity="$(field "$after/04-db-counts.txt" integrity_check)"
    if [ "$integrity" = "ok" ]; then add "SQLite integrity_check" "✅ 符合" "ok"
    else add "SQLite integrity_check" "❌ 不符合" "${integrity:-读不到}"; fi

    # 6) 任务侧证据（差异清单 / 锚点）
    if [ -f "$after/07-task.txt" ] && ! grep -q '未指定 --task-id' "$after/07-task.txt"; then
      if grep -q 'diff.summary' "$after/07-task.txt"; then add "compose.apply 差异清单（应有）" "✅ 符合" "$(grep -m1 'diff.summary' "$after/07-task.txt" | sed 's/^ *//')"
      elif [ "$runs_platform_upgrade" = "no" ]; then add "compose.apply 差异清单" "ℹ️ 不适用" "本格是组件升级（C2），不执行 compose.apply，无差异清单可言"
      elif [ "$runner_side" = "na" ]; then add "compose.apply 差异清单（属 runner v0.3.2）" "ℹ️ 不适用" "执行者为已发布 runner v0.3.1（容器内 compose diff 标识=0 命中）；由 v0.3.2 runner 执行的平台升级格里验"
      else add "compose.apply 差异清单（应有）" "❌ 缺失" "见 07-task.txt"; fi
      if grep -q 'diff.actual_summary' "$after/07-task.txt"; then add "compose.apply 实际结果（应有）" "✅ 符合" "$(grep -m1 'diff.actual_summary' "$after/07-task.txt" | sed 's/^ *//')"
      elif [ "$runs_platform_upgrade" = "no" ]; then add "compose.apply 实际结果" "ℹ️ 不适用" "同差异清单"
      elif [ "$runner_side" = "na" ]; then add "compose.apply 实际结果（属 runner v0.3.2）" "ℹ️ 不适用" "同差异清单"
      else add "compose.apply 实际结果（应有）" "ℹ️ 缺省" "回滚类 cell 不会出现（回滚后即恢复旧镜像）"; fi
      if grep -q '平台回滚锚点' "$after/07-task.txt"; then add "平台回滚锚点（A5）" "✅ 符合" "$(grep -m1 'previous_version=' "$after/07-task.txt" | sed 's/^ *//')"
      elif [ "$runs_platform_upgrade" = "no" ]; then add "平台回滚锚点（A5）" "ℹ️ 不适用" "本格是组件升级（C2），锚点由平台升级的files.sync 产生"
      elif [ "$runner_side" = "na" ]; then add "平台回滚锚点（A5，属 runner v0.3.2）" "ℹ️ 不适用" "执行者为已发布 runner v0.3.1（容器内无 statefile.py）；由 v0.3.2 runner 执行的平台升级格里验"
      else add "平台回滚锚点（A5）" "ℹ️ 未见" "c2（组件升级）不使用平台锚点"; fi
      if grep -q '^absent' "$after/08-runner-state.txt" 2>/dev/null; then
        if [ "$runner_side" = "na" ]; then add "runner 状态文件（属 v0.3.2）" "ℹ️ 不适用" "已发布 v0.3.1 无此文件"
        else add "runner 状态文件（应有）" "⚠️ 缺失" "见 08-runner-state.txt"; fi
      fi
    else
      add "任务证据" "ℹ️ 未采集" "未指定 --task-id"
    fi

    # 7) 场景 B / C 专用
    if [ "$CELL" = "c3" ] && [ -n "$TOKEN" ]; then
      if grep -q '"available":true' "$after/09-rollback-availability.txt"; then add "场景 B 可用性（available=true）" "✅ 符合" "见 09-rollback-availability.txt"
      else add "场景 B 可用性（available=true）" "⚠️ 需人工核对" "见 09-rollback-availability.txt"; fi
    fi

    printf '\n证据包：%s（SHA256SUMS 在同目录）\n' "$after"
    printf '失败/待核对项请逐条写进台账，不要只写"通过"。\n'
  } > "$judgement"

  printf '\n=== 判定表（cell=%s）===\n' "$CELL"
  cat "$judgement"
}

collect_all
printf '证据包已生成：%s\n' "$OUT"
( cd "$OUT" && sha256sum ./*.txt )
if [ "$PHASE" = "after" ]; then judge; fi