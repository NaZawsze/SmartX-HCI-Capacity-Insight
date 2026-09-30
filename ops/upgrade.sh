#!/usr/bin/env bash
# CLI 入口 2：一键升级
#
# ⚠ 这个脚本**不是**给客户用的。客户拿到的离线交付目录里自带
#    `upgrade/upgrade.sh`（含 packages/ 里的升级包），直接跑那个即可，不需要仓库。
#
# 本脚本给**本项目开发者/运维**用：手上没有交付目录、只有仓库时，
# 自动定位/生成升级物料后转发给交付态脚本。
#
# 同 install.sh：不直接 exec ../delivery/upgrade/upgrade.sh，因为仓库里那个目录
# 只有 upgrade.sh 本体，没有 packages/（2026-09-30 核查发现的设计缺陷）。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# 1) 优先用已有交付目录
for CANDIDATE in \
    "$SCRIPT_DIR/../delivery/upgrade" \
    "$SCRIPT_DIR/../ops/packages/latest/offline-delivery/upgrade" \
    "$SCRIPT_DIR/../ops/packages/latest/upgrade" ; do
  if [ -d "$CANDIDATE/packages" ]; then
    dim "使用交付物料：$CANDIDATE"
    step "转发到 $CANDIDATE/upgrade.sh"
    exec bash "$CANDIDATE/upgrade.sh" "$@"
  fi
done

# 2) 都没有 → 明确告诉用户怎么办
cat >&2 <<'EOF'
错误：找不到可用的离线升级物料（需要含 packages/ 的目录）。

已查找的位置:
  ../delivery/upgrade
  ../ops/packages/latest/offline-delivery/upgrade
  ../ops/packages/latest/upgrade

仓库里的 delivery/upgrade/ 只有 upgrade.sh 本体，没有 packages/——
升级包是 ops/package.sh 打包时生成的产物（313 MB），不进 git。

怎么办（按你的目的选一个）:

  A) 仓库态升级（开发者/运维，本机已装好平台）
     先生成升级物料:
         bash ops/package.sh --skip-offline --yes
     再重跑本脚本。升级包会落在 ops/packages/latest/。

  B) 客户升级 / 离线环境升级
     用**交付目录**里的脚本，不要用本仓库的:
         bash upgrade/upgrade.sh --yes
         bash upgrade/upgrade.sh --yes --with-runner packages/smartx-upgrade-runner-v0.3.2.tar.gz
     交付目录（offline-delivery/upgrade/）自带 packages/ 与 upgrade.sh，是自包含的。

  C) 你手上已有交付压缩包
     解开后进入 offline-delivery/upgrade/ 跑 upgrade.sh。
EOF
exit 2
