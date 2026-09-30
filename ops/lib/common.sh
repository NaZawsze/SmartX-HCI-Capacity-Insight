#!/usr/bin/env bash
# 运维操作工具共用库：日志、错误处理、交互确认。
# 由 ops/install.sh、ops/upgrade.sh、ops/package.sh、ops/check-deps.sh 引用。
# 设计见 docs/superpowers/specs/2026-09-30-cli-toolkit-design.md

# 非交互环境（CI、管道）自动关闭颜色
if [ ! -t 1 ] || [ -n "${NO_COLOR:-}" ]; then
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_DIM=""; C_OFF=""
else
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
fi

info() { printf '%s\n' "$*"; }
ok()   { printf '%s  OK %s %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn() { printf '%s警告%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
err()  { printf '%s错误%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
step() { printf '\n%s==>%s %s\n' "$C_BLUE" "$C_OFF" "$*"; }
dim()  { printf '%s%s%s\n' "$C_DIM" "$*" "$C_OFF"; }

# 统一退出码：2 = 前置条件不满足（与 check-deps.sh 约定一致）
die() {
  err "$*"
  exit 2
}

# 需要 root 权限的操作（安装会写 /data、改 docker 组等）
require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "$1 需要 root 权限。请用：sudo $0 $2"
  fi
}

# 交互确认。ASSUME_YES=1 或 --yes 时跳过。
# 用法：confirm "提示语" || exit 1
confirm() {
  local prompt="$1"
  if [ "${ASSUME_YES:-0}" = "1" ]; then
    return 0
  fi
  if [ ! -t 0 ]; then
    # 非交互且未给 --yes：拒绝执行破坏性操作，不擅自决定
    err "需要确认但当前不是交互式终端：$prompt"
    err "确认无误后加 --yes 重跑。"
    return 1
  fi
  local reply=""
  printf '%s%s [y/N] %s' "$C_YELLOW" "$prompt" "$C_OFF" >&2
  read -r reply
  case "$reply" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# 定位仓库根目录（本文件在 <root>/ops/lib/common.sh）
# 不改动调用方的 cwd；失败时返回非 0 而不是崩在 set -u 上。
ops_repo_root() {
  local here=""
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || return 1
  ( cd "$here/../.." 2>/dev/null && pwd )
}
