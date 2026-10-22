#!/usr/bin/env bash
# CLI 入口 1：一键安装
#
# ⚠ 这个脚本**不是**给客户用的。客户拿到的离线交付目录里自带
#    `install/install.sh`（含 images/ 与 project/），直接跑那个即可，不需要仓库。
#
# 本脚本给**本项目开发者/运维**用，转发给**统一安装器**（Phase 86）：
#   · 仓库根 install.sh 是唯一真身（离线/在线双模式），交付包内的
#     install/install.sh 是它打包时的复制。
#   · 仓库形态（无交付物料）也能直接装：默认 --mode auto 会判为在线
#     （docker pull compose 声明的 tag）；要离线就 --mode offline --images <tar 目录>。
#
# 为什么不能直接转发旧的 delivery/install：
#   仓库里的 delivery/ **只有脚本本体**，没有 images/ 与 project/（1.1G 打包产物，
#   不进 git）。现在交付物料的定位逻辑集中在根 install.sh 的 detect_resources()，
#   这里不再重复实现（2026-09-30 核查发现的设计缺陷已由统一安装器吸收）。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# 1) 优先用已有交付目录（离线物料形态优先，客户交付一致的路径）
for CANDIDATE in \
    "$SCRIPT_DIR/../delivery/install" \
    "$SCRIPT_DIR/../ops/packages/latest/offline-delivery/install" \
    "$SCRIPT_DIR/../ops/packages/latest/install" ; do
  if [ -d "$CANDIDATE/images" ] && [ -d "$CANDIDATE/project" ]; then
    dim "使用交付物料：$CANDIDATE"
    dim "（如需自定义数据目录，加 --install-root <路径>）"
    step "转发到 $CANDIDATE/install.sh"
    exec bash "$CANDIDATE/install.sh" "$@"
  fi
done

# 2) 无交付物料 → 转发统一安装器（仓库根真身；在线模式默认可用）
UNIFIED_INSTALLER="$SCRIPT_DIR/../install.sh"
if [ -f "$UNIFIED_INSTALLER" ]; then
  dim "未找到离线交付物料：改用统一安装器（在线模式默认）"
  step "转发到 $UNIFIED_INSTALLER"
  exec bash "$UNIFIED_INSTALLER" "$@"
fi

# 3) 都没有 → 明确告诉用户怎么办，不静默失败
cat >&2 <<'EOF'
错误：既找不到可用的离线交付物料（需含 images/ 与 project/ 的目录），
也没有根统一安装器 install.sh。

已查找的位置:
  ../delivery/install
  ../ops/packages/latest/offline-delivery/install
  ../ops/packages/latest/install
  ../install.sh

说明：交付物料（images/ 与 project/）是 ops/package.sh 打包时生成的产物
（1.1 GB），**不进 git**；仓库里的交付目录只有脚本本体。

怎么办（按你的目的选一个）:

  A) 你要在本机装一套环境
     从仓库根直接装（在线，自动 pull 镜像）:
          bash install.sh --yes
     或先打包出交付物料再离线装（需要 Docker，耗时约 10 分钟）:
          bash ops/package.sh --yes

  B) 客户安装 / 离线环境安装
     用**交付目录**里的脚本，不要用本仓库的:
          bash install/install.sh
     交付目录（offline-delivery/）自带 images/、project/、install.sh，是自包含的。

  C) 你手上已有交付压缩包
     解开后进入该目录跑 install/install.sh。

  D) 只有镜像 tar、没有交付目录
      bash install.sh --mode offline --images <tar 目录> --yes
EOF
exit 2
