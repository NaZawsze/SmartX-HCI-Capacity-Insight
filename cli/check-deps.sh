#!/usr/bin/env bash
# 依赖体检：缺什么给什么可执行的修复指引。
#
# 纪律（设计 §6 / Q5）：**只检测 + 给命令，不自动安装**。在客户机器上自动装系统包是危险动作，
# AGENTS §5 亦禁止未经确认的宿主变更。
#
# 退出码：0 = 全部通过（可能有 WARN）；2 = 有 MISSING（阻断）

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

MISSING=0
WARNS=0

# 检测项模板：名称|检测命令|缺失提示
# 提示文案规范：中文、给可直接粘贴的命令、不用行话、不说"请确保"这类无法执行的表述

check_cmd() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    ok "$name"
  else
    MISSING=$((MISSING + 1))
    err "$name 缺失"
  fi
}

# ── 1. 操作系统 ─────────────────────────────────────────────
check_os() {
  local os=""
  os="$(uname -s 2>/dev/null || echo unknown)"
  if [ "$os" = "Linux" ]; then
    ok "操作系统 Linux"
  else
    MISSING=$((MISSING + 1))
    err "操作系统 $os — 构建镜像需要 Linux"
    info "  macOS/Windows 请改用 Linux 机器，或在 Docker Desktop 的 Linux 容器内执行。"
  fi
}

# ── 2. Docker 命令 ──────────────────────────────────────────
check_docker_cli() {
  if command -v docker >/dev/null 2>&1; then
    ok "docker 命令（$(docker --version 2>/dev/null | head -1)）"
  else
    MISSING=$((MISSING + 1))
    err "未检测到 docker 命令"
    info "  安装（CentOS/RHEL/openEuler）：sudo yum install -y docker"
    info "  安装（Ubuntu/Debian）：sudo apt-get install -y docker.io"
    info "  官方脚本安装：curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh"
  fi
}

# ── 3. docker compose 插件 ──────────────────────────────────
check_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    ok "docker compose（$(docker compose version --short 2>/dev/null | head -1)）"
  else
    MISSING=$((MISSING + 1))
    err "未检测到 docker compose（v2 插件）"
    info "  本项目脚本用 'docker compose'（v2），不是已废弃的 docker-compose（v1）。"
    info "  安装：sudo yum install -y docker-compose-plugin"
    info "  或按官方文档：https://docs.docker.com/compose/install/"
  fi
}

# ── 4. Docker 守护进程 ──────────────────────────────────────
check_docker_daemon() {
  if docker info >/dev/null 2>&1; then
    ok "Docker 守护进程运行中"
  elif ! command -v docker >/dev/null 2>&1; then
    dim "  （跳过：docker 命令本身不存在）"
  else
    MISSING=$((MISSING + 1))
    err "Docker 守护进程未运行或当前用户无权访问"
    info "  启动：sudo systemctl start docker"
    info "  免 sudo 使用：sudo usermod -aG docker \$USER  （之后需重新登录）"
  fi
}

# ── 5. Python 3 ─────────────────────────────────────────────
# 版本比较不依赖 `sort -V`：macOS/BSD 的 sort 不支持 -V，精简环境也可能缺 GNU coreutils，
# 那样会让本函数在 set -u 下直接中断（曾实测报 "unbound variable" 并退成 exit 1 而非 2）。
python_ok() {
  local v="$1" major minor
  major="${v%%.*}"
  minor="${v#*.}"
  [ -n "$major" ] && [ -n "$minor" ] || return 1
  [ "$major" -gt 3 ] 2>/dev/null && return 0
  [ "$major" -eq 3 ] 2>/dev/null && [ "$minor" -ge 11 ] 2>/dev/null
}

check_python() {
  local ver=""
  if command -v python3 >/dev/null 2>&1; then
    ver="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  fi
  if [ -z "$ver" ]; then
    MISSING=$((MISSING + 1))
    err "未检测到 python3"
    info "  安装：sudo yum install -y python3   /   sudo apt-get install -y python3"
  elif ! python_ok "$ver"; then
    MISSING=$((MISSING + 1))
    err "Python 版本过低：${ver}（需要 3.11+）"
    info "  安装新版：sudo yum install -y python3.11   /   或用 pyenv 安装"
  else
    ok "python3 $ver"
  fi
}

# ── 6. git ──────────────────────────────────────────────────
check_git() {
  if command -v git >/dev/null 2>&1; then
    ok "git（$(git --version 2>/dev/null | head -1)）"
  else
    MISSING=$((MISSING + 1))
    err "未检测到 git"
    info "  安装：sudo yum install -y git   /   sudo apt-get install -y git"
  fi
}

# ── 7. 磁盘空间 ─────────────────────────────────────────────
# 不用 `df -BG`（GNU 专有，BSD/精简环境不支持）：退回 POSIX 的 df -k 再换算。
check_disk() {
  local need_gb="${CLI_MIN_DISK_GB:-20}"
  local avail_kb avail_gb
  avail_kb="$(df -Pk "$PWD" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [ -z "$avail_kb" ] || ! [ "$avail_kb" -eq "$avail_kb" ] 2>/dev/null; then
    WARNS=$((WARNS + 1))
    warn "无法读取磁盘可用空间（跳过检查）"
    return
  fi
  avail_gb=$((avail_kb / 1024 / 1024))
  if [ "$avail_gb" -ge "$need_gb" ]; then
    ok "磁盘可用 ${avail_gb} GB（需 ≥ ${need_gb} GB）"
  else
    MISSING=$((MISSING + 1))
    err "磁盘可用仅 ${avail_gb} GB，构建需 ≥ ${need_gb} GB"
    info "  查看占用：docker system df   /   du -sh /data/*"
    info "  清理（会删除未使用的镜像与缓存，需确认）：docker system prune"
  fi
}

# ── 8. 仓库状态 ─────────────────────────────────────────────
check_repo() {
  # 局部变量先赋空值：set -u 下若命令失败会引用未赋值变量而中断（退成 exit 1 而非 2）
  local root=""
  root="$(cli_repo_root 2>/dev/null || true)"
  if [ -n "$root" ] && [ -d "$root/.git" ]; then
    ok "git 仓库 $root"
  else
    MISSING=$((MISSING + 1))
    err "当前目录不是 git 仓库"
    info "  克隆：git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git"
  fi
}

# ── 9. 基线 runner 镜像（发布产物，不在仓库里）──────────────
# 只提示，不阻断打包平台包/组件包；仅在需要构建离线交付目录时才是硬前置。
check_runner_baseline() {
  local image="${CLI_RUNNER_BASELINE_IMAGE:-nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1}"
  if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -qx "$image"; then
    ok "基线 runner 镜像 $image"
  else
    WARNS=$((WARNS + 1))
    warn "本机没有基线 runner 镜像：$image"
    dim "  它是**已发布**产物、不在仓库里。只影响「离线交付目录」这一步；"
    dim "  打包平台包与 runner 组件包不需要它。三条可选路径："
    dim "    1) 从 GitHub Release 下载已发布组件包后 docker load"
    dim "    2) 从已有导出目录复制（.3:/data/upgrade-packages/baseline-*/images/）"
    dim "    3) 跳过离线交付目录，只出平台包与 runner 组件包（--skip-offline）"
  fi
}

main() {
  step "依赖体检"
  check_os
  check_docker_cli
  check_docker_compose
  check_docker_daemon
  check_python
  check_git
  check_disk
  check_repo
  check_runner_baseline

  echo
  if [ "$MISSING" -gt 0 ]; then
    err "有 $MISSING 项前置条件不满足，无法继续。"
    info "按上面的命令逐条处理后重新运行本检查。"
    exit 2
  fi
  if [ "$WARNS" -gt 0 ]; then
    warn "有 $WARNS 项提示（不阻断），请留意上文说明。"
  fi
  ok "前置条件全部满足。"
  exit 0
}

main "$@"
