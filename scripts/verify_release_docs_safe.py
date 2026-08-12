#!/usr/bin/env python3
"""发布前对外文档安全扫描门禁。

检查所有对外发布文档中是否残留:
    - 内网/测试机 IP 地址
    - 硬编码凭据或密码
    - 私有网络子网（手动确认）

退出码 0 = 通过，1 = 发现违规。

用法:
    python3 scripts/verify_release_docs_safe.py [--repo-root /path/to/repo]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 只检查对外发布文档（README/CHANGELOG/deployment/architecture 等），
# 不检查内部工作记录（progress/findings/worklog/UPG 计划）。
PUBLIC_DOCS: list[str] = [
    "README.md",
    "README.zh-CN.md",
    "docs/releases/CHANGELOG.md",
    "docs/deployment.md",
    "docs/usage.md",
    "docs/architecture.md",
    "docs/architecture-v2.md",
    "docs/functional-modules.md",
    "docs/v2-api-contracts.md",
    "docs/v2-frontend-design.md",
    "docs/v2-implementation-sequence.md",
    "docs/v2-rebuild-task-plan.md",
    "docs/v2-upgrade-center-design.md",
    "docs/v1-data-compatibility.md",
    "docs/ova-delivery.md",
    "docs/upgrade-runner-lifecycle.md",
    "docs/upgrade-issues.md",
]

# 明确允许的子网（docker 网络、Docker 默认 bridge）
ALLOWED_SUBNET_CONTEXTS = {
    "10.249.249",
    "10.249.250",
    "10.249.251",
    "172.16",
    "172.17",
}


def _is_allowed_ip(text: str) -> bool:
    """判断 IP 片段是否属于已知允许的 docker 网络/文档示例。"""
    for prefix in ALLOWED_SUBNET_CONTEXTS:
        if text.startswith(prefix):
            return True
    return False


# 私有 IP 精确匹配（4 段完整，排除 docker 子网）
IP_UNSAFE = re.compile(
    r"\b(10\.(?!249\.)\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.(?!1[6-9]\.|2\d\.|3[01]\.)\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)
# 公网/业务地址（不含 10.249.x docker 网络）
URL_UNSAFE = re.compile(
    r"https?://(?:10\.(?!249\.)\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.(?!1[6-9]\.|2\d\.|3[01]\.)\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)
# 疑似硬编码凭据（测试/模板值除外）
CREDENTIAL_RE = re.compile(
    r"\b(p@ssw0rd|AKIA[0-9A-Z]{16}|sk-[0-9a-fA-F]{32}|ghp_[0-9a-zA-Z]{36})\b"
)


def scan_file(path: Path) -> list[str]:
    violations: list[str] = []
    text = path.read_text(errors="ignore")
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in IP_UNSAFE.finditer(line):
            if _is_allowed_ip(m.group(0)):
                continue
            violations.append(f"{path}:{lineno}  IP地址 {m.group(0)}")
        for m in URL_UNSAFE.finditer(line):
            violations.append(f"{path}:{lineno}  业务URL {m.group(0)}")
        for m in CREDENTIAL_RE.finditer(line):
            violations.append(f"{path}:{lineno}  疑似凭据 {m.group(0)[:12]}...")
    return violations


def main() -> None:
    # 如果有 --repo-root 参数，切换根目录
    args = [a for a in sys.argv if a.startswith("--repo-root=")]
    root = ROOT
    if args:
        root = Path(args[0].split("=", 1)[1])

    all_violations: list[str] = []
    for rel in PUBLIC_DOCS:
        p = root / rel
        if p.is_file():
            all_violations.extend(scan_file(p))

    if all_violations:
        print(f"[FAIL] 发现 {len(all_violations)} 处违规:")
        for v in all_violations:
            print(f"  {v}")
        print("\n规则:")
        print("  - 对外发布文档不得含内网/测试机 IP 或业务地址。")
        print("  - Docker 网络子网 (10.249.x) 除外。")
        print("  - 内部排障文档 (progress/findings/worklog) 不在扫描范围。")
        sys.exit(1)

    print("[PASS] 对外发布文档安全扫描通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
