#!/usr/bin/env bash
# CLI 入口 3：一键打包
#
# 用法：
#   git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git
#   cd SmartX-HCI-Capacity-Insight
#   bash ops/package.sh
#
# 做四件事：同步代码 → 体检依赖 → 构建平台包/runner 组件包/离线交付目录 → 归档到 ops/packages/
# 设计见 docs/superpowers/specs/2026-09-30-cli-toolkit-design.md
#
# 纪律：依赖缺失**只提示不自动装**（Q5）；失败**不在中途静默继续**，每步都有明确判据。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# ── 参数 ────────────────────────────────────────────────────
BRANCH="main"                 # Q1：默认 main（发布线）。dev2 是开发线，必须显式指定才会用。
OUTPUT_DIR=""                 # 默认 <repo>/ops/packages
SKIP_OFFLINE=0                # 缺基线 runner 镜像时可跳过离线交付目录
ASSUME_YES=0
DO_FETCH=1

usage() {
  cat <<'USAGE'
一键打包 SmartX HCI Capacity Insight 升级包

用法:
  bash ops/package.sh [选项]

选项:
  --branch <分支>     要打包的分支（默认 main = 发布线）
                      ⚠ 本项目 dev2 是开发线，打包发客户请务必确认分支
  --output-dir <目录> 产物输出根目录（默认 ops/packages）
  --skip-offline      跳过离线交付目录（只出平台包 + runner 组件包）
  --no-fetch          跳过 git fetch（用当前工作树）
  --yes               非交互模式，跳过破坏性操作确认
  -h, --help          显示本帮助

环境变量:
  OPS_PUBLISHED_RUNNER_PACKAGE  **必填** 已发布 runner 组件包（Release 资产 .tar.gz）路径。
                                动作词汇冻结门禁（Phase 68 W7.1）拿它当能力基线——
                                用本次构建的 runner 包当基线等于自己判自己。
  OPS_PUBLISHED_TAG             编译器变更对比基准 tag（默认 v0.5.3）
  OPS_RUNNER_BASELINE_TAG       离线交付目录的基线 runner tag（默认 v0.3.1）

示例:
  OPS_PUBLISHED_RUNNER_PACKAGE=~/dl/smartx-upgrade-runner-v0.3.1.tar.gz bash ops/package.sh
  bash ops/package.sh --branch dev2 --skip-offline   # 本机无基线 runner 镜像时

产物:
  <output-dir>/latest/       最新可用（平台包 + runner 组件包 + 离线交付目录）
  <output-dir>/archive/YYYYMMDD/  历史归档（保留最近 5 份）
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH="${2:?--branch 需要分支名}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?--output-dir 需要目录}"; shift 2 ;;
    --skip-offline) SKIP_OFFLINE=1; shift ;;
    --no-fetch) DO_FETCH=0; shift ;;
    --yes) ASSUME_YES=1; export ASSUME_YES; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "未知参数：$1"; echo; usage; exit 2 ;;
  esac
done

ROOT="$(ops_repo_root)" || die "无法定位仓库根目录（ops_repo_root 失败）。当前目录：$PWD"
[ -n "$ROOT" ] || die "仓库根目录解析为空。当前目录：$PWD"
[ -n "$OUTPUT_DIR" ] || OUTPUT_DIR="$ROOT/ops/packages"
LATEST_DIR="$OUTPUT_DIR/latest"
ARCHIVE_DIR="$OUTPUT_DIR/archive"
STAGE_DIR="$OUTPUT_DIR/.stage"
KEEP_ARCHIVES=5                 # Q3：保留最近 5 份

TODAY="$(date +%Y%m%d)"
RUN_TAG="$(date +%H%M%S)"

# ── 步骤 1/2：环境与依赖体检 ────────────────────────────────
step "步骤 1/9 · 依赖体检"
if ! bash "$SCRIPT_DIR/check-deps.sh"; then
  err "依赖体检未通过，已中止。"
  info "按上面提示逐条处理后重跑；只想看诊断可单独执行：bash ops/check-deps.sh"
  exit 2
fi

# ── 步骤 3/9：同步代码 ─────────────────────────────────────
# Q1：分支必须显式；reset --hard 是破坏性操作，未确认则中止。
step "步骤 2/9 · 同步代码（分支 $BRANCH ）"
cd "$ROOT" || die "无法进入仓库根目录：$ROOT"

if [ "$DO_FETCH" = "1" ]; then
  if command -v git >/dev/null 2>&1 && [ -d "$ROOT/.git" ]; then
    dim "git fetch --prune origin"
    if ! git fetch --prune origin; then
      warn "git fetch 失败（可能无网络或无凭据）。将使用本地已有的 origin/$BRANCH 。"
    fi
  else
    warn "不是 git 仓库或无 git，跳过同步。"
  fi
fi

if [ -d "$ROOT/.git" ]; then
  # 无论是否 fetch，都先检查工作树是否干净。
  # 曾实测漏掉这一步：--no-fetch 会整块跳过脏检查，导致「有本地改动」也不提示，
  # 而产物来自这份被改过的树 —— 用户以为在打 origin，实际打的是自己的改动。
  DIRTY="$(git status --porcelain 2>/dev/null | head -20)"
  if [ -n "$DIRTY" ]; then
    warn "工作树有本地改动："
    printf '%s\n' "$DIRTY" | sed 's/^/    /'
    if [ "$DO_FETCH" = "1" ]; then
      dim "下一步的 git reset --hard 会丢弃它们。"
    else
      dim "你用了 --no-fetch，将**直接用这份被改过的工作树打包**（产物含本地改动）。"
    fi
    if ! confirm "确认在当前工作树（含这些改动）上继续打包？"; then
      err "已取消（未做任何修改）。"
      info "如需丢弃改动：去掉 --no-fetch 让脚本自动对齐 origin/$BRANCH"
      info "如需保留改动：git stash"
      exit 1
    fi
  fi
else
  warn "不是 git 仓库，跳过同步与脏检查。产物无法溯源到具体提交。"
fi

if [ -d "$ROOT/.git" ] && [ "$DO_FETCH" = "1" ]; then
  CURRENT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  if [ "$CURRENT" != "$BRANCH" ]; then
    dim "切换分支 $CURRENT -> $BRANCH"
    if ! git checkout "$BRANCH" 2>/dev/null; then
      err "本地没有分支 $BRANCH 。创建并跟踪远端：git checkout -b $BRANCH origin/$BRANCH"
      exit 2
    fi
  fi

  dim "git reset --hard origin/$BRANCH"
  if ! git reset --hard "origin/$BRANCH"; then
    err "无法对齐 origin/$BRANCH （远端可能没有该分支）"
    exit 2
  fi
  ok "代码已对齐 origin/$BRANCH （$(git rev-parse --short HEAD)）"

  # 步骤 3：checkout 后重跑体检（scripts/ 可能变了）
  step "步骤 3/9 · 同步后复检"
  if ! bash "$SCRIPT_DIR/check-deps.sh"; then
    err "同步后依赖体检未通过，已中止。"
    exit 2
  fi
elif [ "$DO_FETCH" = "0" ]; then
  warn "已指定 --no-fetch：跳过代码同步，使用当前工作树。产物可能与远端不一致。"
fi

# ── 步骤 4/9：版本一致性预检（早失败，省掉整轮门禁）────────
step "步骤 4/9 · 版本一致性预检"
cd "$ROOT" || die "无法进入仓库根目录"

VER_RAW="$(cat "$ROOT/VERSION" 2>/dev/null | tr -d '[:space:]')"
RVER_RAW="$(cat "$ROOT/RUNNER_VERSION" 2>/dev/null | tr -d '[:space:]')"
[ -n "$VER_RAW" ] || die "读不到 VERSION"
[ -n "$RVER_RAW" ] || die "读不到 RUNNER_VERSION"
# 归一化：VERSION 文件本身已带 v 前缀（实测 v0.5.3），不要再补一个 v
VER="${VER_RAW#v}"; VER="v$VER"
RVER="${RVER_RAW#v}"; RVER="v$RVER"
info "平台 VERSION=$VER （原始 $VER_RAW ）"
info "runner RUNNER_VERSION=$RVER （原始 $RVER_RAW ）"

# 三个源码 compose 的 runner tag 必须与 RUNNER_VERSION 一致
COMPOSE_TAGS="$(grep -hE '^\s*image:.*upgrade-runner:' \
  "$ROOT/docker-compose.yml" "$ROOT/docker-compose.offline.yml" "$ROOT/docker-compose.release.yml" 2>/dev/null \
  | grep -oE 'upgrade-runner:v[0-9A-Za-z._-]+' | sort -u | sed 's/.*://' | tr '\n' ' ')"
dim "源码 compose runner tag: $COMPOSE_TAGS"
MISMATCH=0
for t in $COMPOSE_TAGS; do
  if [ "$t" != "$RVER" ]; then
    MISMATCH=1
  fi
done
if [ "$MISMATCH" = "1" ]; then
  err "源码 compose 的 runner tag 与 RUNNER_VERSION（$RVER ）不一致。"
  info "这会让交付物与源码脱节（历史上出过一版 runner tag 不一致的包）。"
  info "请先修正：scripts/verify_runner_delivery_consistency.py 会指出具体文件。"
  exit 2
fi
ok "版本一致性通过（compose tag = $RVER ）"

# ── 步骤 5/9：清理暂存区 ───────────────────────────────────
step "步骤 5/9 · 准备暂存目录"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
ok "暂存目录 $STAGE_DIR"

# ── 步骤 6/9：构建平台包 + runner 组件包 ───────────────────
step "步骤 6/9 · 构建升级包"
cd "$ROOT" || die "无法进入仓库根目录"

info "构建平台包 $VER …"
if ! python3 scripts/build_upgrade_package.py --output-dir "$STAGE_DIR"; then
  err "平台包构建失败（详见上方输出）。"
  exit 2
fi
PLATFORM_PKG="$STAGE_DIR/smartx-capacity-insight-upgrade-$VER.tar.gz"
[ -f "$PLATFORM_PKG" ] || die "平台包未生成：$PLATFORM_PKG"
ok "平台包 $(basename "$PLATFORM_PKG")"

info "构建 runner 组件包 $RVER …"
if ! python3 scripts/build_runner_component_package.py --output-dir "$STAGE_DIR"; then
  err "runner 组件包构建失败（详见上方输出）。"
  exit 2
fi
RUNNER_PKG="$STAGE_DIR/smartx-upgrade-runner-$RVER.tar.gz"
[ -f "$RUNNER_PKG" ] || die "runner 组件包未生成：$RUNNER_PKG"
ok "runner 组件包 $(basename "$RUNNER_PKG")"

# ── 步骤 7/9：门禁 ─────────────────────────────────────────
step "步骤 7/9 · 交付门禁"

if ! python3 scripts/verify_upgrade_package_identity.py "$PLATFORM_PKG"; then
  err "平台包身份门禁未通过（版本文件/镜像 tag/manifest 不一致）。"
  exit 2
fi
ok "平台包身份门禁通过"

if ! python3 scripts/verify_runner_delivery_consistency.py --package "$RUNNER_PKG"; then
  err "runner 交付一致性门禁未通过（同版本号不同能力 / 包与源码不同源）。"
  exit 2
fi
ok "runner 交付一致性门禁通过"

# W7.2 迁移 expand-only 门禁（Phase 68）：破坏性 schema 变更会让回滚保数据当场失效。
if ! python3 scripts/verify_migrations_expand_only.py; then
  err "迁移 expand-only 门禁未通过（新增条目含破坏性模式）。"
  exit 2
fi
ok "迁移 expand-only 门禁通过"

# W7.1 动作词汇冻结门禁（Phase 68）：平台包编译出的计划动作集必须落在已发布 runner 能力内。
# 已发布 runner 包 = **客户手里那份**（Release 资产），不是本次构建产物——
# 用本次构建的 runner 包当基线等于自己判自己（AGENTS §10 交付一致性门禁的同一纪律）。
PUBLISHED_RUNNER_PKG="${OPS_PUBLISHED_RUNNER_PACKAGE:-}"
PUBLISHED_TAG="${OPS_PUBLISHED_TAG:-v0.5.3}"
if [ -z "$PUBLISHED_RUNNER_PKG" ] || [ ! -f "$PUBLISHED_RUNNER_PKG" ]; then
  err "动作词汇冻结门禁需要**已发布** runner 组件包（Release 资产）作为能力基线。"
  err "  未找到：${PUBLISHED_RUNNER_PKG:-（未设置 OPS_PUBLISHED_RUNNER_PACKAGE）}"
  err "  从 Release 下载 smartx-upgrade-runner-v0.3.1.tar.gz 后："
  err "    OPS_PUBLISHED_RUNNER_PACKAGE=<路径> bash ops/package.sh ..."
  exit 2
fi
if ! python3 scripts/verify_upgrade_plan_vocabulary.py "$PLATFORM_PKG" \
      --runner-package "$PUBLISHED_RUNNER_PKG" --published-tag "$PUBLISHED_TAG"; then
  err "动作词汇冻结门禁未通过（计划用了已发布 runner 不支持的动作 / schema_version 偏离已发布线）。"
  exit 2
fi
ok "动作词汇冻结门禁通过（基线 runner 包：$(basename "$PUBLISHED_RUNNER_PKG")）"

# 敏感文件扫描
info "扫描包内敏感文件 …"
SENSITIVE_RE='(^|/)(\.env|.*\.sqlite3?|.*\.db|smartx-storage-forecast\.db|id_rsa|.*\.pem|.*\.key|credentials.*)$'
for pkg in "$PLATFORM_PKG" "$RUNNER_PKG"; do
  HITS="$(tar -tzf "$pkg" 2>/dev/null | grep -icE "$SENSITIVE_RE" || true)"
  if [ "${HITS:-0}" -gt 0 ]; then
    err "$(basename "$pkg") 内含 $HITS 个敏感文件条目："
    tar -tzf "$pkg" 2>/dev/null | grep -iE "$SENSITIVE_RE" | head -10 | sed 's/^/    /'
    exit 2
  fi
done
ok "敏感文件扫描 0 命中"

# ── 步骤 8/9：离线交付目录 ─────────────────────────────────
step "步骤 8/9 · 离线交付目录"
# --runner-baseline 收的是**已发布基线 tag**（如 v0.3.1），不是镜像 tar 路径；
# 镜像导出由 build_offline_delivery.py 自己做（它会 docker save 该 tag）。
# 曾实测误传 tar 路径，脚本会拼成 upgrade-runner:/path/to.tar 而找不到镜像。
BASELINE_TAG="${OPS_RUNNER_BASELINE_TAG:-v0.3.1}"
BASELINE_IMAGE="nazawsze/smartx-hci-capacity-insight-upgrade-runner:$BASELINE_TAG"

if [ "$SKIP_OFFLINE" = "1" ]; then
  warn "已指定 --skip-offline：不出离线交付目录。"
  OFFLINE_DIR=""
elif docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -qx "$BASELINE_IMAGE"; then
  info "构建离线交付目录，基线 runner $BASELINE_TAG …"
  if python3 scripts/build_offline_delivery.py \
        --platform-package "$PLATFORM_PKG" \
        --runner-package "$RUNNER_PKG" \
        --runner-baseline "$BASELINE_TAG" \
        --readme "$ROOT/delivery/README.md" \
        --output-dir "$STAGE_DIR/offline-delivery" \
        --platform-version "$VER"; then
    OFFLINE_DIR="$STAGE_DIR/offline-delivery"
    ok "离线交付目录已生成"
  else
    err "离线交付目录构建失败。"
    exit 2
  fi
else
  warn "本机没有基线 runner 镜像：$BASELINE_IMAGE"
  dim "它是**已发布**产物、不在仓库里，无法凭空生成。三条可选路径："
  dim "  1) 从 GitHub Release 下载已发布组件包后 docker load"
  dim "  2) 从已有导出目录复制（.3:/data/upgrade-packages/baseline-*/images/）"
  dim "  3) 加 --skip-offline，只出平台包与 runner 组件包"
  dim "  另：基线 tag 可用 OPS_RUNNER_BASELINE_TAG 覆盖（默认 v0.3.1）"
  OFFLINE_DIR=""
fi

# ── 步骤 9/9：归档 ─────────────────────────────────────────
step "步骤 9/9 · 归档到 $OUTPUT_DIR"
TODAY_DIR="$ARCHIVE_DIR/$TODAY-$RUN_TAG"
mkdir -p "$TODAY_DIR"
cp "$PLATFORM_PKG" "$RUNNER_PKG" "$TODAY_DIR/"
[ -n "$OFFLINE_DIR" ] && cp -a "$OFFLINE_DIR" "$TODAY_DIR/offline-delivery"
( cd "$TODAY_DIR" && sha256sum ./*.tar.gz > SHA256SUMS 2>/dev/null || true )
ok "已归档到 $TODAY_DIR"

# latest 用副本而非软链（Q3：软链在拷贝目录/换机器时会断）
rm -rf "$LATEST_DIR"
mkdir -p "$LATEST_DIR"
cp "$PLATFORM_PKG" "$RUNNER_PKG" "$LATEST_DIR/"
[ -n "$OFFLINE_DIR" ] && cp -a "$OFFLINE_DIR" "$LATEST_DIR/offline-delivery"
( cd "$LATEST_DIR" && sha256sum ./*.tar.gz > SHA256SUMS 2>/dev/null || true )
ok "已更新 $LATEST_DIR"

# 历史归档保留最近 N 份
if [ -d "$ARCHIVE_DIR" ]; then
  OLD_COUNT="$(find "$ARCHIVE_DIR" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')"
  if [ "$OLD_COUNT" -gt "$KEEP_ARCHIVES" ]; then
    dim "清理超出 $KEEP_ARCHIVES 份的历史归档…"
    find "$ARCHIVE_DIR" -maxdepth 1 -mindepth 1 -type d | sort | head -n $((OLD_COUNT - KEEP_ARCHIVES)) \
      | while read -r d; do rm -rf "$d"; dim "  已删 $(basename "$d")"; done
  fi
fi

rm -rf "$STAGE_DIR"

# ── 汇总 ───────────────────────────────────────────────────
echo
ok "打包完成（分支 origin/$BRANCH ，commit $(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || echo n/a)）"
echo
info "产物清单："
for f in "$LATEST_DIR"/*.tar.gz; do
  [ -f "$f" ] || continue
  printf '  %-52s %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"
done
[ -d "$LATEST_DIR/offline-delivery" ] && printf '  %-52s %s\n' "offline-delivery/" "$(du -sh "$LATEST_DIR/offline-delivery" | cut -f1)"
echo
info "校验："
cat "$LATEST_DIR/SHA256SUMS" 2>/dev/null | sed 's/^/  /'
echo
info "下一步："
if [ -n "$OFFLINE_DIR" ]; then
  info "  · 交付：把 $LATEST_DIR/offline-delivery 整个目录给客户（含 install/ 与 upgrade/）"
  info "  · 客户安装：bash install/install.sh"
  info "  · 客户升级：bash upgrade/upgrade.sh --with-runner <runner 组件包>"
else
  info "  · 平台包：$LATEST_DIR/$(basename "$PLATFORM_PKG")"
  info "  · runner 组件包：$LATEST_DIR/$(basename "$RUNNER_PKG")"
  info "  · 本次未出离线交付目录（缺基线 runner 镜像或已 --skip-offline）"
fi
info "  · 注意：交付物 compose 的 runner 基线必须是**已发布**版本，不是源码的 $RVER 。"
echo
warn "发版检查单（W7.1 警告项必须人工核对）："
warn "  · 动作词汇冻结门禁若有 WARN（编译器相对 $PUBLISHED_TAG 有变更），"
warn "    必须人工核对偏斜矩阵：各源版本的计划形状与老编译器行为。"
warn "  · 源版本低于 v0.5.3 的格，其计划由源端已发布 web-api 的老编译器生成，"
warn "    门禁只证明候选包编译器编译同一 manifest 的动作集合规，需靠兼容矩阵与老链路回归覆盖。"
exit 0
