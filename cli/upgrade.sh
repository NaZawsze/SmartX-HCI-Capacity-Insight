#!/usr/bin/env bash
# CLI 入口 2：一键升级（薄封装）
#
# 逻辑全部在 delivery/upgrade/upgrade.sh（已在 .14 断网实测通过）。
# 本脚本只做三件事：定位 → 存在性检查 → exec 参数透传。**不加任何业务逻辑**。
#
# 升级只走本机 API（task_plan #56 用户已定 Q1 = 走 API）：
# 单飞守卫、post-cleanup、任务留痕、US-25 逃生门全部生效，不绕过产品流程。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

TARGET="$SCRIPT_DIR/../delivery/upgrade/upgrade.sh"

if [ ! -f "$TARGET" ]; then
  err "找不到升级脚本：$TARGET"
  info ""
  info "两种可能："
  info "  1) 你不在仓库里。升级请用**离线交付目录**中的 upgrade/upgrade.sh"
  info "     （交付目录自带 install/ + upgrade/ + 升级包，不依赖仓库）。"
  info "  2) 仓库不完整。重新克隆："
  info "     git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git"
  exit 2
fi

dim "转发到 $TARGET"
exec bash "$TARGET" "$@"
