#!/usr/bin/env bash
# 安装本仓库的 git hook（目前只有 pre-commit：拦内部开发文档）。
#
# 用法：
#   bash scripts/install_git_hooks.sh          # 安装
#   bash scripts/install_git_hooks.sh --check  # 只检查是否已安装
#
# 为什么要单独一步：`.git/hooks/` 不入版本库，clone 后必须显式安装。
# 设计：hook 脚本本身在 `scripts/hooks/pre-commit`（受版本控制、可评审），
# 安装动作只是建一个指向它的软链（或拷贝，视文件系统是否支持软链）。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/scripts/hooks/pre-commit"
TARGET="$ROOT/.git/hooks/pre-commit"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

if [ ! -d "$ROOT/.git" ]; then
  echo "不是 git 检出（可能是 git archive 解出的构建树），无需安装 hook。" >&2
  exit 0
fi

if [ ! -f "$SOURCE" ]; then
  echo "缺少 $SOURCE" >&2
  exit 1
fi

if [ "$CHECK_ONLY" = "1" ]; then
  if [ -e "$TARGET" ] && [ -x "$TARGET" ]; then
    echo "已安装：$TARGET"
    exit 0
  fi
  echo "未安装 pre-commit hook（运行 bash scripts/install_git_hooks.sh）" >&2
  exit 1
fi

mkdir -p "$ROOT/.git/hooks"
chmod +x "$SOURCE"
# 用**相对**软链（相对 .git/hooks/ 解析），这样仓库整体移动位置后仍不断。
if ! ln -sfn "../../scripts/hooks/pre-commit" "$TARGET" 2>/dev/null; then
  cp "$SOURCE" "$TARGET"
fi
chmod +x "$TARGET"
echo "已安装：$TARGET -> ../../scripts/hooks/pre-commit"
echo "作用：git commit 时拦下内部开发文档与开发自用脚本（只查本次提交）。"
