#!/usr/bin/env bash
# 站点验收 9 项（默认只读）：安装/升级后的既成事实复核。
#
# 用途：任何一台已安装本产品的机器（.12 发布机 / .14 干净机 / 客户现场）升级或安装后，
#       用它确认「服务在跑、版本对、布局对、数据没丢、旧路径已清、新代码在场」。
#
# 用法：
#   bash scripts/verify_site_acceptance.sh
#   bash scripts/verify_site_acceptance.sh --expected-version v0.5.3 --expected-runner v0.3.1
#   bash scripts/verify_site_acceptance.sh --install-root /data/smartx-storage-forecast --project smartx-hci-capacity-insight
#
# 9 项：① health+三项 checks ② 容器数 5 ③ 镜像内版本文件 ④ compose project/network
#      ⑤ .env（0600 + SMARTX_COMPOSE_FILE_ACTIVE） ⑥ SQLite 完整性与业务计数
#      ⑦ 旧路径清理 ⑧ 前端/Prometheus 可达 ⑨ 升级任务历史
#
# 退出码：0 全部通过；1 有检查项不通过（逐项打印 FAIL 原因）。
# 纪律：脚本**只读**（除登录换取 token 外不改任何状态）；凭据只从 .env 读、绝不回显。
set -uo pipefail

INSTALL_ROOT="/data/smartx-storage-forecast"
PROJECT="smartx-hci-capacity-insight"
API_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:8080"
PROMETHEUS_URL="http://127.0.0.1:9090"
EXPECTED_VERSION=""
EXPECTED_RUNNER=""
EXPECTED_COMPOSE_MARKER=""
LEGACY_PATHS=(/opt/smartx-storage-forecast /data/upgrades /data/backups /data/exports /data/compose-runtime /prometheus-data)

usage() {
  sed -n '2,16p' "$0"
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --install-root) INSTALL_ROOT="${2:?}"; shift 2 ;;
    --project) PROJECT="${2:?}"; shift 2 ;;
    --api-url) API_URL="${2:?}"; shift 2 ;;
    --frontend-url) FRONTEND_URL="${2:?}"; shift 2 ;;
    --prometheus-url) PROMETHEUS_URL="${2:?}"; shift 2 ;;
    --expected-version) EXPECTED_VERSION="${2:?}"; shift 2 ;;
    --expected-runner) EXPECTED_RUNNER="${2:?}"; shift 2 ;;
    --expected-compose-marker) EXPECTED_COMPOSE_MARKER="${2:?}"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "未知参数：$1" >&2; usage 1 ;;
  esac
done

ENV_FILE="$INSTALL_ROOT/project/.env"
FAILED=0
fail() { printf '  [FAIL] %s\n' "$*"; FAILED=1; }
pass() { printf '  [OK]   %s\n' "$*"; }
info() { printf '  [info] %s\n' "$*"; }

echo "== ① health =="
HEALTH="$(curl -s --max-time 10 "$API_URL/api/system/health" || true)"
if printf '%s' "$HEALTH" | grep -q '"ok":true'; then
  pass "$HEALTH"
else
  fail "health 不可用：$HEALTH"
fi
printf '%s' "$HEALTH" | grep -q '"directories":true' && pass "checks.directories=true" || fail "checks.directories!=true"
printf '%s' "$HEALTH" | grep -q '"database":true' && pass "checks.database=true" || fail "checks.database!=true"
printf '%s' "$HEALTH" | grep -q '"prometheus":true' && pass "checks.prometheus=true" || fail "checks.prometheus!=true"
if [ -n "$EXPECTED_VERSION" ] && ! printf '%s' "$HEALTH" | grep -q "\"version\":\"$EXPECTED_VERSION\""; then
  fail "平台版本不是 $EXPECTED_VERSION"
fi
if [ -n "$EXPECTED_RUNNER" ] && ! printf '%s' "$HEALTH" | grep -q "\"runner_version\":\"$EXPECTED_RUNNER\""; then
  fail "runner 版本不是 $EXPECTED_RUNNER"
fi

echo "== ② 容器（期望 5 个 Up）=="
UP_COUNT="$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' | wc -l | tr -d ' ')"
docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '  {{.Names}}|{{.Image}}|{{.Status}}'
[ "$UP_COUNT" = "5" ] && pass "容器数 = 5" || fail "容器数 = $UP_COUNT（期望 5）"

echo "== ③ 镜像内版本文件 =="
for svc in web-api upgrade-runner; do
  V="$(docker exec "${PROJECT}-${svc}-1" cat /app/$( [ "$svc" = "web-api" ] && echo VERSION || echo RUNNER_VERSION ) 2>/dev/null || echo unknown)"
  info "$svc = $V"
done

echo "== ④ compose project / network =="
LABEL="$(docker inspect "${PROJECT}-web-api-1" --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || echo "")"
[ "$LABEL" = "$PROJECT" ] && pass "project label = $LABEL" || fail "project label = '$LABEL'（期望 $PROJECT）"
NETS="$(docker network ls --filter name=smartx --format '{{.Name}}' | grep -c . || true)"
NET_LIST="$(docker network ls --filter name=smartx --format '{{.Name}}' | tr '\n' ' ')"
[ "$NETS" = "1" ] && pass "唯一网络：$NET_LIST" || fail "网络数量 = $NETS：$NET_LIST"

echo "== ⑤ .env（0600 + compose 标记，US-37）=="
if [ -f "$ENV_FILE" ]; then
  PERM="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE")"
  [ "$PERM" = "600" ] && pass ".env 权限 0600" || fail ".env 权限 $PERM（期望 600）"
  MARKER="$(sed -n 's/^SMARTX_COMPOSE_FILE_ACTIVE=//p' "$ENV_FILE" | tail -1)"
  if [ -n "$MARKER" ]; then
    pass "SMARTX_COMPOSE_FILE_ACTIVE=$MARKER"
    if [ -n "$EXPECTED_COMPOSE_MARKER" ] && [ "$MARKER" != "$EXPECTED_COMPOSE_MARKER" ]; then
      fail "compose 标记不是 $EXPECTED_COMPOSE_MARKER"
    fi
  else
    fail ".env 缺少 SMARTX_COMPOSE_FILE_ACTIVE（US-37 守卫无法判定变体）"
  fi
  info ".env sha256 前 16 位：$(sha256sum "$ENV_FILE" 2>/dev/null | cut -c1-16)"
else
  fail "$ENV_FILE 不存在"
fi

echo "== ⑥ SQLite 完整性与业务计数 =="
docker exec "${PROJECT}-web-api-1" python -c "
import sqlite3
c = sqlite3.connect('/data/smartx.db')
print('  integrity', c.execute('PRAGMA integrity_check').fetchone()[0])
for t in ('users','towers','clusters','vm_latest','vm_volumes','metric_snapshots','collection_runs'):
    try:
        print(' ', t, c.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0])
    except Exception as exc:
        print(' ', t, 'ERR', exc)
" 2>/dev/null || fail "无法读取容器内 SQLite"

echo "== ⑦ 旧路径清理 =="
for p in "${LEGACY_PATHS[@]}"; do
  if [ -e "$p" ]; then fail "旧路径仍存在：$p"; else info "absent $p"; fi
done

echo "== ⑧ 前端 / Prometheus 可达 =="
FE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$FRONTEND_URL/" || echo 000)"
[ "$FE" = "200" ] && pass "frontend 200" || fail "frontend $FE"
PR="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$PROMETHEUS_URL/-/healthy" || echo 000)"
[ "$PR" = "200" ] && pass "prometheus 200" || fail "prometheus $PR"

echo "== ⑨ 升级任务历史（只读，需 .env 内管理员凭据）=="
if [ -f "$ENV_FILE" ]; then
  ADMIN_USER="$(sed -n 's/^SMARTX_ADMIN_USER=//p' "$ENV_FILE" | tail -1)"
  ADMIN_PASS="$(sed -n 's/^SMARTX_ADMIN_PASSWORD=//p' "$ENV_FILE" | tail -1)"
  TOKEN="$(curl -s --max-time 15 -X POST "$API_URL/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null || true)"
  if [ -n "$TOKEN" ]; then
    curl -s --max-time 20 "$API_URL/api/admin/upgrade/history" -H "Authorization: Bearer $TOKEN" \
      | python3 -c '
import json,sys
rows = json.load(sys.stdin)
for t in rows[:5]:
    print("  ", t.get("task_id"), t.get("status"), (t.get("message") or "")[:70])
' 2>/dev/null || fail "升级历史解析失败"
  else
    info "登录失败（凭据可能已改），跳过任务历史"
  fi
fi

echo
if [ "$FAILED" = "0" ]; then
  echo "验收结论：全部通过"
  exit 0
fi
echo "验收结论：存在不通过项（见上面 FAIL）"
exit 1
