#!/usr/bin/env bash
# 修复 DockerHub `v0.5.1u2` tag 内容漂移（pending #88，2026-10-14）
#
# 背景：DockerHub `nazawsze/smartx-hci-capacity-insight-web-api:v0.5.1u2` 自
# 2026-07-09 CI 构建起就指向镜像 `556f69e4…`——该构建的 git 提交（baaffcd，即
# v0.5.1u2 tag）的 VERSION 文件已写成 `v0.5.2`，镜像 `/app/VERSION` 自报 v0.5.2。
# 以其为基线安装会被升级中心判为 v0.5.2，v0.5.2 官方升级包被源兼容检查拦下。
# GitHub Release v0.5.1u2 包内嵌镜像（`images/*.tar`，web-api 镜像 b5018a3c…）
# 才是原始内容。本脚本用 Release 包内原始镜像重打 DockerHub tag。
# 设计与证据：docs/superpowers/specs/2026-10-14-dockerhub-v051u2-tag-remediation-design.md
#
# 用法（在具备 docker + DockerHub 写入权限的机器上执行，如 .3）：
#   # 干跑（默认）：只加载、校验、打印将执行的 tag/push 命令
#   bash scripts/fix_dockerhub_v051u2_tag.sh --package /path/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
#   # 确认无误后真推（需先 docker login，或导出 DOCKERHUB_USER/DOCKERHUB_TOKEN）
#   bash scripts/fix_dockerhub_v051u2_tag.sh --package <包> --push
#
# 凭据边界：只读环境变量/本机 docker login 会话，不落盘、不打印；仓库任何位置
# 不得出现凭据（AGENTS §5）。
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PACKAGE=""
IMAGES_DIR=""
PUSH=0
NAMESPACE="nazawsze"
EXPECT_VERSION="v0.5.1u2"

c_red()    { printf '\033[31m%s\033[0m\n' "$*"; }
c_green()  { printf '\033[32m%s\033[0m\n' "$*"; }
c_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
info()     { printf '     %s\n' "$*"; }
phase()    { printf '\n═══ %s ═══\n' "$*"; }

usage() {
  cat <<'USAGE'
修复 DockerHub v0.5.1u2 tag 内容漂移（用 GitHub Release 包内原始镜像重打 tag）

用法:
  bash scripts/fix_dockerhub_v051u2_tag.sh --package <Release 平台包.tar.gz> [--push]
  bash scripts/fix_dockerhub_v051u2_tag.sh --images <已解包的 images 目录> [--push]

选项:
  --package <tar.gz>   GitHub Release v0.5.1u2 平台升级包（内含 images/*.tar）
  --images <目录>      已解包的 images/ 目录（与 --package 二选一）
  --namespace <ns>     DockerHub 命名空间（默认 nazawsze）
  --push               真正执行 docker push；不加则只干跑（加载/校验/打印命令）
  -h, --help           显示本帮助

安全设计:
  · 默认干跑——不推任何东西；
  · web-api 镜像的 /app/VERSION 必须解出 v0.5.1u2，否则拒绝推送（防推错内容）；
  · frontend/collector-worker 无 /app/VERSION 属正常，如实打印并继续。
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --package)  PACKAGE="${2:?}"; shift 2 ;;
    --images)   IMAGES_DIR="${2:?}"; shift 2 ;;
    --namespace) NAMESPACE="${2:?}"; shift 2 ;;
    --push)     PUSH=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) c_red "未知选项：$1"; usage; exit 1 ;;
  esac
done

if [ -z "$PACKAGE" ] && [ -z "$IMAGES_DIR" ]; then
  c_red "必须指定 --package 或 --images 之一"
  usage
  exit 1
fi
if [ -n "$PACKAGE" ] && [ -n "$IMAGES_DIR" ]; then
  c_red "--package 与 --images 只能选一个"
  exit 1
fi

command -v docker >/dev/null 2>&1 || { c_red "未找到 docker"; exit 1; }
docker info >/dev/null 2>&1 || { c_red "docker 守护进程不可用"; exit 1; }

WORK_DIR="$(mktemp -d)"
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

# ── 1. 取得 images/ 目录 ──
phase "步骤 1/4 · 解包 / 定位镜像归档"
if [ -n "$PACKAGE" ]; then
  [ -f "$PACKAGE" ] || { c_red "包不存在：$PACKAGE"; exit 1; }
  mkdir -p "$WORK_DIR/pkg"
  tar -xzf "$PACKAGE" -C "$WORK_DIR/pkg" images/
  IMAGES_DIR="$WORK_DIR/pkg/images"
fi
[ -d "$IMAGES_DIR" ] || { c_red "images 目录不存在：$IMAGES_DIR"; exit 1; }
# 平台包内固定三个归档（scripts/build_upgrade_package.py PLATFORM_IMAGES）
for name in web-api collector-worker frontend; do
  [ -f "$IMAGES_DIR/$name.tar" ] || { c_red "缺少镜像归档：$IMAGES_DIR/$name.tar"; exit 1; }
done
c_green "  [OK] 镜像归档齐备：web-api / collector-worker / frontend"

# ── 2. 加载并逐镜像校验 ──
phase "步骤 2/4 · docker load + /app/VERSION 校验"
declare -a LOADED_IDS=()
for name in web-api collector-worker frontend; do
  load_out="$(docker load -i "$IMAGES_DIR/$name.tar")"
  # docker load 输出形如 "Loaded image: <repo>:<tag>" 或 "Loaded image ID: sha256:..."
  ref="$(printf '%s' "$load_out" | sed -nE 's/.*Loaded image: ([^ ]+).*/\1/p')"
  if [ -z "$ref" ]; then
    ref="$(printf '%s' "$load_out" | sed -nE 's/.*Loaded image ID: (sha256:[0-9a-f]+).*/\1/p')"
  fi
  [ -n "$ref" ] || { c_red "无法解析 docker load 输出（$name）：$load_out"; exit 1; }
  img_id="$(docker inspect --format '{{.Id}}' "$ref")"
  LOADED_IDS+=("$name:$img_id")
  # web-api 必须能读出 v0.5.1u2；其余两个无 /app/VERSION 属正常（记录后继续）
  file_version="$(docker run --rm --entrypoint cat "$img_id" /app/VERSION 2>/dev/null || true)"
  if [ "$name" = "web-api" ]; then
    if [ "$file_version" != "$EXPECT_VERSION" ]; then
      c_red "web-api 镜像 /app/VERSION = '${file_version:-<读不到>}'，期望 $EXPECT_VERSION"
      c_red "内容不符，拒绝打 tag/推送（防把错误内容推成『修复』）"
      exit 1
    fi
    c_green "  [OK] web-api /app/VERSION = $file_version"
  else
    c_yellow "  [--] $name 无 /app/VERSION（${file_version:-正常}），按 Release 清单放行"
  fi
done

# ── 3. 重打 tag ──
phase "步骤 3/4 · 重打 DockerHub tag"
for entry in "${LOADED_IDS[@]}"; do
  name="${entry%%:*}"
  img_id="${entry#*:}"
  remote="$NAMESPACE/smartx-hci-capacity-insight-$name:$EXPECT_VERSION"
  docker tag "$img_id" "$remote"
  c_green "  [OK] $remote -> $img_id"
done

# ── 4. 推送（默认干跑） ──
phase "步骤 4/4 · 推送（$([ "$PUSH" -eq 1 ] && echo 实推 || echo 干跑)）"
if [ "$PUSH" -eq 0 ]; then
  c_yellow "干跑模式：未执行任何 docker push。确认上面输出无误后加 --push 重跑。"
  for entry in "${LOADED_IDS[@]}"; do
    name="${entry%%:*}"
    info "将执行：docker push $NAMESPACE/smartx-hci-capacity-insight-$name:$EXPECT_VERSION"
  done
  exit 0
fi

# docker login 会话或 DOCKERHUB_USER/DOCKERHUB_TOKEN 二选一（都不落盘）
if [ -n "${DOCKERHUB_USER:-}" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
  printf '%s' "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USER" --password-stdin >/dev/null
  c_green "  [OK] 已用环境变量凭据登录"
else
  docker info 2>/dev/null | grep -q 'Username' || {
    c_red "未登录 DockerHub 且未提供 DOCKERHUB_USER/DOCKERHUB_TOKEN"
    c_yellow "  先 docker login，或导出两个环境变量后重试（凭据不会落盘）"
    exit 1
  }
fi

for entry in "${LOADED_IDS[@]}"; do
  name="${entry%%:*}"
  img_id="${entry#*:}"
  remote="$NAMESPACE/smartx-hci-capacity-insight-$name:$EXPECT_VERSION"
  docker push "$remote" | tail -1
  # 回读校验：registry 上的 digest 必须与本地镜像一致
  local_digest="$(docker inspect --format '{{join .RepoDigests ","}}' "$img_id" 2>/dev/null || true)"
  remote_digest="$(docker manifest inspect "$remote" 2>/dev/null | sed -nE 's/.*sha256:([0-9a-f]{64}).*/sha256:\1/p' | head -1 || true)"
  if [ -n "$remote_digest" ] && printf '%s' "$local_digest" | grep -q "$remote_digest"; then
    c_green "  [OK] $remote digest 回读一致（${remote_digest:0:19}…）"
  else
    c_yellow "  [!!] $remote digest 回读未能自动比对（local=${local_digest:-?} remote=${remote_digest:-?}）"
    c_yellow "       请人工核对：docker manifest inspect $remote"
  fi
done

c_green "修复完成。建议再做一次端到端确认："
info "docker rmi $NAMESPACE/smartx-hci-capacity-insight-web-api:$EXPECT_VERSION"
info "docker pull $NAMESPACE/smartx-hci-capacity-insight-web-api:$EXPECT_VERSION"
info "docker run --rm --entrypoint cat $NAMESPACE/smartx-hci-capacity-insight-web-api:$EXPECT_VERSION /app/VERSION"
info "期望输出：$EXPECT_VERSION"
