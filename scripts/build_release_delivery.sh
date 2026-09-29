#!/usr/bin/env bash
# 一键构建「升级包 + 离线交付目录」（49-56 补充）
#
# 解决的问题：此前"从源码到可交付物"的链条分散在 5 个脚本里，路径与顺序全靠人工记忆，
# 容易漏跑门禁（runner 交付一致性门禁就差点漏过）。本脚本把它固化成**一条命令**，
# 任一门禁失败立即中止，绝不产出"看起来完整"的交付物。
#
# 链条：
#   0. 版本门禁（VERSION / RUNNER_VERSION / 三个源码 compose 的字面量 tag 一致）
#   1. 平台升级包            build_upgrade_package.py
#   2. 平台包身份门禁        verify_upgrade_package_identity.py
#   3. runner 组件包         build_runner_component_package.py
#   4. runner 交付一致性门禁 verify_runner_delivery_consistency.py（源码树指纹 + 包内镜像）
#   5. 离线交付目录          build_offline_delivery.py（内含禁含文件扫描）
#   6. 产物清单 + SHA256
#
# 用法：
#   bash scripts/build_release_delivery.sh --output-root /data/upgrade-packages
#   bash scripts/build_release_delivery.sh --runner-baseline v0.3.1 --check-dockerhub
#
# 说明：
#   · --runner-baseline 是**交付物里安装用 compose** 的 runner 基线（已发布版本），
#     与本次构建的 runner 包版本无关：安装先落到已发布基线，之后再用 upgrade/ 升到新版本。
#   · 默认不查 DockerHub（tag 往往在发版时才推）；发版前加 --check-dockerhub。
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

OUTPUT_ROOT="/data/upgrade-packages"
RUNNER_BASELINE=""
PROMETHEUS_IMAGE="prom/prometheus:v2.55.1"
PROMETHEUS_ARCHIVE=""
CHECK_DOCKERHUB=0
REUSE_IMAGES=0
README="delivery/README.md"
PLATFORM_PACKAGE=""
RUNNER_PACKAGE=""
RUNNER_VERSION_ARG=""
SKIP_DELIVERY=0

c_red()    { printf '\033[31m%s\033[0m\n' "$*"; }
c_green()  { printf '\033[32m%s\033[0m\n' "$*"; }
c_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
info()     { printf '     %s\n' "$*"; }
phase()    { printf '\n%s\n' "═══ $* ═══"; }

usage() {
  cat <<'USAGE'
一键构建升级包与离线交付目录

用法:
  bash scripts/build_release_delivery.sh [选项]

选项:
  --output-root <目录>      产物根目录（默认 /data/upgrade-packages）
  --runner-baseline <tag>   交付物安装 compose 里的 runner 基线（必填，如 v0.3.1）
  --platform-package <包>   复用已有平台包（跳过步骤 1-2）
  --runner-package <包>     复用已有 runner 包（跳过步骤 3-4）
  --runner-version <tag>    runner 组件包版本（默认取仓库 RUNNER_VERSION）
  --prometheus-image <img>  prometheus 镜像（默认 prom/prometheus:v2.55.1）
  --prometheus-archive <tar>  已备好的 prometheus 归档；给了则不 docker save，字节级可复现
  --readme <路径>           交付 README（默认 delivery/README.md）
  --reuse-images            复用已有镜像，不重新 docker build（需已构建过）
  --check-dockerhub         额外校验 DockerHub tag（发版前加）
  --skip-delivery           只出升级包，不组装交付目录
  -h, --help                显示本帮助
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --output-root)     OUTPUT_ROOT="${2:?}"; shift 2 ;;
    --runner-baseline) RUNNER_BASELINE="${2:?}"; shift 2 ;;
    --platform-package) PLATFORM_PACKAGE="${2:?}"; shift 2 ;;
    --runner-package)   RUNNER_PACKAGE="${2:?}"; shift 2 ;;
    --runner-version)   RUNNER_VERSION_ARG="${2:?}"; shift 2 ;;
    --prometheus-image) PROMETHEUS_IMAGE="${2:?}"; shift 2 ;;
    --prometheus-archive) PROMETHEUS_ARCHIVE="${2:?}"; shift 2 ;;
    --readme)           README="${2:?}"; shift 2 ;;
    --reuse-images)     REUSE_IMAGES=1; shift ;;
    --check-dockerhub)  CHECK_DOCKERHUB=1; shift ;;
    --skip-delivery)    SKIP_DELIVERY=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    *) c_red "未知选项：$1"; usage; exit 1 ;;
  esac
done

[ "$SKIP_DELIVERY" -eq 0 ] && [ -z "$RUNNER_BASELINE" ] && {
  c_red "组装交付目录必须显式指定 --runner-baseline（如 v0.3.1）"
  c_yellow "  交付物里的安装 compose 必须落**已发布**的 runner 基线，而不是源码 compose 的开发线 tag。"
  c_yellow "  只想出升级包可以加 --skip-delivery。"
  exit 1
}

command -v docker >/dev/null 2>&1 || { c_red "未找到 docker"; exit 1; }
docker info >/dev/null 2>&1 || { c_red "docker 守护进程不可用"; exit 1; }
python3 -c 'import sys' 2>/dev/null || { c_red "未找到 python3"; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { c_red "未找到 sha256sum"; exit 1; }

VERSION="$(tr -d ' \n' < VERSION)"
REPO_RUNNER_VERSION="$(tr -d ' \n' < RUNNER_VERSION)"
RUNNER_VERSION="${RUNNER_VERSION_ARG:-$REPO_RUNNER_VERSION}"
STAMP="$(date +%Y%m%d)"
PKG_DIR="$OUTPUT_ROOT"
mkdir -p "$PKG_DIR"

c_green "════════════════════════════════════════════════"
c_green " 构建升级包与离线交付目录"
c_green "════════════════════════════════════════════════"
printf '  平台版本：%s\n' "$VERSION"
printf '  Runner   ：%s（仓库 RUNNER_VERSION）\n' "$REPO_RUNNER_VERSION"
[ -n "$RUNNER_BASELINE" ] && printf '  交付安装基线：%s\n' "$RUNNER_BASELINE"
printf '  产物目录：%s\n' "$PKG_DIR"
printf '\n'

# ── 0. 版本门禁 ──
phase "步骤 0/6 · 版本门禁"
python3 scripts/build_upgrade_package.py --check-version || {
  c_red "版本门禁未通过：VERSION / RUNNER_VERSION / 源码 compose 的 runner tag 不一致"
  c_yellow "  改版本后请同步检查：VERSION、RUNNER_VERSION、docker-compose.yml、"
  c_yellow "  docker-compose.offline.yml、docker-compose.release.yml、"
  c_yellow "  backend/app/core/config.py 与 backend/app/v2/config.py 的 DEFAULT_RUNNER_VERSION。"
  exit 1
}
c_green "  [OK] 版本元数据一致"

# ── 1-2. 平台升级包 + 身份门禁 ──
if [ -n "$PLATFORM_PACKAGE" ]; then
  phase "步骤 1-2/6 · 复用已有平台包（跳过构建）"
  [ -f "$PLATFORM_PACKAGE" ] || { c_red "平台包不存在：$PLATFORM_PACKAGE"; exit 1; }
  c_yellow "  复用：$PLATFORM_PACKAGE"
else
  phase "步骤 1/6 · 构建平台升级包"
  BUILD_ARGS=(--output-dir "$PKG_DIR")
  [ "$REUSE_IMAGES" -eq 1 ] && BUILD_ARGS+=(--no-build --allow-existing-images)
  python3 scripts/build_upgrade_package.py "${BUILD_ARGS[@]}" | tail -5
  PLATFORM_PACKAGE="$PKG_DIR/smartx-capacity-insight-upgrade-$VERSION.tar.gz"
  [ -f "$PLATFORM_PACKAGE" ] || { c_red "平台包未生成：$PLATFORM_PACKAGE"; exit 1; }

  phase "步骤 2/6 · 平台包身份门禁"
  python3 scripts/verify_upgrade_package_identity.py "$PLATFORM_PACKAGE" --expected-version "$VERSION" >/dev/null \
    || { c_red "平台包身份门禁未通过（manifest / 版本文件 / 镜像 tag / SHA256 不一致）"; exit 1; }
  c_green "  [OK] 平台包身份一致"
fi

# ── 3-4. runner 组件包 + 交付一致性门禁 ──
if [ -n "$RUNNER_PACKAGE" ]; then
  phase "步骤 3-4/6 · 复用已有 runner 包（跳过构建）"
  [ -f "$RUNNER_PACKAGE" ] || { c_red "runner 包不存在：$RUNNER_PACKAGE"; exit 1; }
  c_yellow "  复用：$RUNNER_PACKAGE"
else
  phase "步骤 3/6 · 构建 runner 组件包"
  R_ARGS=(--output-dir "$PKG_DIR" --version "$RUNNER_VERSION")
  [ "$REUSE_IMAGES" -eq 1 ] && R_ARGS+=(--no-build)
  python3 scripts/build_runner_component_package.py "${R_ARGS[@]}" | tail -4
  RUNNER_PACKAGE="$PKG_DIR/smartx-upgrade-runner-$RUNNER_VERSION.tar.gz"
  [ -f "$RUNNER_PACKAGE" ] || { c_red "runner 包未生成：$RUNNER_PACKAGE"; exit 1; }

  phase "步骤 4/6 · runner 交付一致性门禁"
  GATE_ARGS=(--package "$RUNNER_PACKAGE")
  [ "$CHECK_DOCKERHUB" -eq 1 ] && GATE_ARGS+=(--check-dockerhub)
  # 一次调用：既打印明细又取退出码（门禁以非零退出表示 FAIL，PASS/SKIP 不改变退出码）
  if ! python3 scripts/verify_runner_delivery_consistency.py "${GATE_ARGS[@]}" | tail -14; then
    c_red "runner 交付一致性门禁未通过"
    exit 1
  fi
  c_green "  [OK] runner 交付一致性通过"
fi

# ── 5. 离线交付目录 ──
if [ "$SKIP_DELIVERY" -eq 1 ]; then
  c_yellow "已指定 --skip-delivery，不组装交付目录"
else
  phase "步骤 5/6 · 组装离线交付目录"
  DELIVERY_DIR="$OUTPUT_ROOT/smartx-capacity-insight-$VERSION-offline"
  D_ARGS=(
    --platform-package "$PLATFORM_PACKAGE"
    --runner-package "$RUNNER_PACKAGE"
    --prometheus-image "$PROMETHEUS_IMAGE"
    --runner-baseline "$RUNNER_BASELINE"
    --readme "$README"
    --output-dir "$DELIVERY_DIR"
    --platform-version "$VERSION"
    --allow-existing
  )
  [ -n "$PROMETHEUS_ARCHIVE" ] && D_ARGS+=(--prometheus-archive "$PROMETHEUS_ARCHIVE")
  python3 scripts/build_offline_delivery.py "${D_ARGS[@]}" | tail -14 \
    || { c_red "交付目录组装失败"; exit 1; }
fi

# ── 6. 产物清单 ──
phase "步骤 6/6 · 产物清单与 SHA256"
SUMMARY="$PKG_DIR/SHA256SUMS-$(date +%Y%m%d%H%M%S)"
: > "$SUMMARY"
for artifact in "$PLATFORM_PACKAGE" "$RUNNER_PACKAGE"; do
  [ -f "$artifact" ] || continue
  line="$(sha256sum "$artifact")"
  printf '%s\n' "$line" >> "$SUMMARY"
  c_green "  $(basename "$artifact")"
  printf '    %s\n' "$line"
done
[ "$SKIP_DELIVERY" -eq 0 ] && {
  D="$OUTPUT_ROOT/smartx-capacity-insight-$VERSION-offline"
  c_green "  交付目录：$D  ($(du -sh "$D" | cut -f1))"
  info "安装：bash install/install.sh --yes"
  info "升级：bash upgrade/upgrade.sh --yes"
}
c_yellow "  清单：$SUMMARY（请登记到 docs/upgrade-package-ledger.md）"

printf '\n'
c_green "构建完成。所有门禁已通过。"
c_yellow "提醒：prometheus.tar 因 docker save 写时间戳而每次 SHA 不同（固有行为）。"
printf '\n'
