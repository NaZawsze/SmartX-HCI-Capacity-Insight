#!/usr/bin/env bash
# CLI 入口 1：一键安装
#
# ⚠ 这个脚本**不是**给客户用的。客户拿到的离线交付目录里自带
#    `install/install.sh`（含 images/ 与 project/），直接跑那个即可，不需要仓库。
#
# 本脚本给**本项目开发者/运维**用：从仓库 clone 后想在本机装一套环境时用。
# 它先确保有可用的离线交付物料（没有就调用 ops/package.sh 生成），再转发给交付态脚本。
#
# 为什么不直接 exec ../delivery/install/install.sh：
#   仓库里的 delivery/install/ **只有 install.sh 一个文件**，没有 images/ 与 project/
#   ——那是 build_offline_delivery.py 打包时才生成的产物（1.1G），不可能进 git。
#   直接转发必然在「找不到镜像目录」处失败（2026-09-30 核查发现的设计缺陷）。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# 1) 优先用已有交付目录
for CANDIDATE in \
    "$SCRIPT_DIR/../delivery/install" \
    "$SCRIPT_DIR/../ops/packages/latest/offline-delivery/install" \
    "$SCRIPT_DIR/../ops/packages/latest/install" ; do
  if [ -d "$CANDIDATE/images" ] && [ -d "$CANDIDATE/project" ]; then
    dim "使用交付物料：$CANDIDATE"
    dim "（若要装到别处，加 --install-dir <交付目录>）"
    step "转发到 $CANDIDATE/install.sh"
    exec bash "$CANDIDATE/install.sh" "$@"
  fi
done

# 2) 都没有 → 明确告诉用户怎么办，不静默失败
cat >&2 <<'EOF'
错误：找不到可用的离线交付物料（需要含 images/ 与 project/ 的目录）。

已查找的位置:
  ../delivery/install
  ../ops/packages/latest/offline-delivery/install
  ../ops/packages/latest/install

仓库里的 delivery/install/ 只有 install.sh 本体，没有镜像与部署文件——
它们是 ops/package.sh 打包时生成的产物（1.1 GB），不进 git。

怎么办（按你的目的选一个）:

  A) 你要在本机装一套环境
     先打包出交付物料（需要 Docker，耗时约 10 分钟）:
         bash ops/package.sh --skip-offline --yes
     然后重跑本脚本。注意 --skip-offline 时需自己准备 install/images/，
     最省事的做法是不加该参数，让 package.sh 产出完整 offline-delivery/。

  B) 客户安装 / 离线环境安装
     用**交付目录**里的脚本，不要用本仓库的:
         bash install/install.sh
     交付目录（offline-delivery/）自带 images/、project/、install.sh，是自包含的。

  C) 你手上已有交付压缩包
     解开后进入该目录跑 install/install.sh。
EOF
exit 2
