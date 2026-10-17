#!/usr/bin/env bash
# 撕裂态救援：把旧布局数据目录搬到新布局宿主路径（pending #99，设计见
# docs/superpowers/specs/2026-10-17-v052-layout-tearing-remediation-design.md）
#
# 背景：v0.5.1u2 老布局现场升到 v0.5.2 后，compose 已把容器挂到新布局宿主目录
# （/data/smartx-storage-forecast/*），但数据仍在旧布局（/data/smartx-capacity-insight-data/*）。
# 此时平台读到的是新布局空库。**正解是继续升到 v0.5.3**（目录迁移会自动愈合）；
# 本脚本只用于「必须在 v0.5.2 停留」时的止血，把数据搬到容器能看见的位置。
#
# 安全约束：
#   · 默认干跑（只打印将做什么）；--apply 才真正执行；
#   · 先校验（旧目录存在、新目录为空或不存在、DB 完整），再复制，最后重启平台；
#   · 旧目录**不删除**（留作回退依据），只改名归档；
#   · 全程记录到 /data/layout-repair.log。
set -u

OLD_ROOT=/data/smartx-capacity-insight-data
NEW_ROOT=/data/smartx-storage-forecast
LOG=/data/layout-repair.log
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
info() { printf '     %s\n' "$*" | tee -a "$LOG"; }
ok()   { c_green "  [OK] $*"; }
warn() { c_yellow "  [!!] $*"; }

: >> "$LOG"

say "=== 撕裂态救援 $(date '+%Y-%m-%d %H:%M:%S')（APPLY=$APPLY）==="
say "正解提示：如果还能升级，请直接继续升到 v0.5.3（目录迁移会自动愈合），不需要本脚本。"

# ── 前置校验 ──────────────────────────────────────────────────────────
if [ ! -d "$OLD_ROOT" ]; then
  ok "旧布局目录不存在，无需迁移（可能已是新布局或已迁移）"
  exit 0
fi
if [ ! -f "$OLD_ROOT/app/smartx.db" ]; then
  c_red "  [XX] 旧布局库里没有 smartx.db，拒绝继续（避免把更坏的状态复制过去）"
  exit 1
fi
if [ -d "$NEW_ROOT" ] && [ -n "$(ls -A "$NEW_ROOT/app" 2>/dev/null)" ]; then
  c_red "  [XX] 新布局 app 目录非空，拒绝继续（避免覆盖既有数据）"
  info "如确认要强制迁移，请先手工备份并清空 $NEW_ROOT/app"
  exit 1
fi
ROWS=$(python3 -c "
import sqlite3
c = sqlite3.connect('file:$OLD_ROOT/app/smartx.db?mode=ro', uri=True)
print(c.execute('SELECT COUNT(*) FROM vm_latest').fetchone()[0])" 2>/dev/null || echo "?")
INTEG=$(python3 -c "
import sqlite3
c = sqlite3.connect('file:$OLD_ROOT/app/smartx.db?mode=ro', uri=True)
print(c.execute('PRAGMA integrity_check').fetchone()[0])" 2>/dev/null || echo "?")
say "  旧库：vm_latest=$ROWS integrity=$INTEG"
if [ "$INTEG" != "ok" ]; then
  c_red "  [XX] 旧库完整性检查未通过，先备份/抢救再谈迁移"
  exit 1
fi

say "  将执行：复制 $OLD_ROOT/{app,prometheus,upgrades,backups,exports,compose-runtime} → $NEW_ROOT/"
say "  旧目录将归档为 $OLD_ROOT.migrated-$(date +%Y%m%d%H%M%S)（不删除，留作回退）"

if [ "$APPLY" -ne 1 ]; then
  warn "干跑模式：未做任何改动。确认无误后加 --apply 执行。"
  exit 0
fi

# ── 执行 ──────────────────────────────────────────────────────────────
STAMP=$(date +%Y%m%d%H%M%S)
mkdir -p "$NEW_ROOT"
for sub in app prometheus upgrades backups exports compose-runtime; do
  if [ -d "$OLD_ROOT/$sub" ]; then
    mkdir -p "$NEW_ROOT/$sub"
    cp -a "$OLD_ROOT/$sub/." "$NEW_ROOT/$sub/" && ok "已复制 $sub" || { c_red "复制 $sub 失败，已停止"; exit 1; }
  fi
done
mv "$OLD_ROOT" "$OLD_ROOT.migrated-$STAMP" && ok "旧目录已归档为 $OLD_ROOT.migrated-$STAMP"

say "  重启平台容器（使用产品 compose）…"
cd "$NEW_ROOT/project" 2>/dev/null || { c_red "找不到 $NEW_ROOT/project（compose 目录）"; exit 1; }
docker compose -f docker-compose.offline.yml --project-name smartx-hci-capacity-insight \
  up -d --no-deps web-api collector-worker frontend prometheus 2>&1 | tail -5 | tee -a "$LOG"

say ""
say "=== 验证 $(date '+%H:%M:%S') ==="
sleep 20
HEALTH=$(curl -s --max-time 10 http://127.0.0.1:8000/api/system/health | head -c 200)
say "  health: $HEALTH"
docker ps --format '{{.Names}}|{{.Status}}' | grep smartx | tee -a "$LOG"
c_green "  完成。若 health 仍不 ok=true，请把上面输出发回给维护方。"
