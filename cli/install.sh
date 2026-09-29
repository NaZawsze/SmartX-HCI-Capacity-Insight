#!/usr/bin/env bash
# CLI 入口 1：一键安装（薄封装）
#
# 逻辑全部在 delivery/install/install.sh（已在 .14 断网实测通过）。
# 本脚本只做三件事：定位 → 存在性检查 → exec 参数透传。**不加任何业务逻辑**。
#
# 设计依据 docs/superpowers/specs/2026-09-30-cli-toolkit-design.md §4 Q4：
# delivery/install/install.sh 是被 build_offline_delivery.py 复制进交付目录的源文件，
# 交付目录必须自包含，所以逻辑必须留在 delivery/。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

TARGET="$SCRIPT_DIR/../delivery/install/install.sh"

if [ ! -f "$TARGET" ]; then
  err "找不到安装脚本：$TARGET"
  info ""
  info "两种可能："
  info "  1) 你不在仓库里。安装请用**离线交付目录**中的 install/install.sh"
  info "     （交付目录自带 install/ + upgrade/ + 镜像，不依赖仓库）。"
  info "  2) 仓库不完整。重新克隆："
  info "     git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git"
  exit 2
fi

dim "转发到 $TARGET"
exec bash "$TARGET" "$@"
