#!/usr/bin/env python3
"""仓库文档范围门禁：**仓库只放代码**，内部开发文档一律不提交（2026-10-21 用户定）。

**背景**：仓库历史上累积了 151 个 Markdown，其中 128 个是内部开发记录
（设计稿、实施计划、工作日志、问题台账、审计矩阵、路线图、交接文档、版本验证记录）。
用户 2026-10-21：「用于内部开发的文档都不要提交了吧，仓库本来就是只用来放代码的」。

**不是一刀切**——有些 .md 是**产品的一部分**或**门禁夹具**，缺了会断：
- 客户文档（`delivery/README.md`、`docs/deployment.md`…）：随交付包发给客户；
- 构建输入（`docs/releases/CHANGELOG.md` 会被打进包；`README.md` 被打包脚本改写版本号）；
- 门禁夹具（`docs/api.md` 被 `verify_api_docs.py` 解析、`docs/version-skew-matrix.md`
  被 US-01 门禁解析…）。

因此本门禁锁定两份清单：

1. **TRACKED_DOCS** — 允许进入版本控制的 .md（23 个）。任何**新增**的受控 .md
   必须显式加进这里，加之前先自问三条判据（见文件中部注释）。
2. **REQUIRED_DOCS** — 上面那份里被代码/门禁真实读取或打包必需的子集；
   缺任何一个 → FAIL（防止有人「清理文档」把夹具删了让门禁静默失效）。

检查项：

1. `required_docs_exist` — REQUIRED_DOCS 全部在磁盘上（缺了门禁会静默降级）。
2. `no_unlisted_tracked_docs` — `git ls-files '*.md'` 的结果必须 ⊆ TRACKED_DOCS。
   新增内部文档后忘记加 ignore → 这里报出来。
3. `no_internal_docs_tracked` — 目录/文件名黑名单（`docs/superpowers/`、`docs/archive/`、
   `progress.md`、`findings.md`、`task_plan.md`、各类台账）必须**零命中**。
   这条独立于第 2 条：即使有人把内部文档塞进 TRACKED_DOCS，这条也会拦。
4. `gitignore_covers_internal` — 上面的黑名单模式确实写在 `.gitignore` 里
   （否则 `git add -A` 会重新把它们加回来）。
5. `payload_has_no_docs` — 交付包 `project/` 载荷不含任何 .md（与
   `test_no_internal_docs_in_payload.py` 同源，这里做静态侧冗余）。
6. `no_dead_doc_links` — 受控文档里的相对 `.md` 链接**必须指向受控文档**。
   内部文档移出版本控制后，公开仓库里指向它们的链接会变成死链（客户按文档操作时踩空），
   这条把「移出文档时顺手清链接」变成机器检查。

用法：

    python3 scripts/verify_repo_doc_scope.py            # 人类可读，FAIL 时 exit 1
    python3 scripts/verify_repo_doc_scope.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = ROOT / ".gitignore"

#: 允许进入版本控制的 Markdown（穷举，新增必须显式登记）。
#: 加新条目之前先过三条判据：①客户会看到？②构建/打包把它当输入？
#: ③门禁或测试把它当夹具读（缺了会断）？三条都不满足 = 内部文档，不要提交。
TRACKED_DOCS: frozenset[str] = frozenset(
    {
        # —— ① 产品/交付文档（客户会看到） ——
        "README.md",
        "README.zh-CN.md",
        "delivery/README.md",
        "docs/deployment.md",
        "docs/usage.md",
        "docs/ova-delivery.md",
        "docs/architecture.md",
        "docs/architecture-v2.md",
        "docs/v2-api-contracts.md",
        "docs/v2-frontend-design.md",
        "docs/v2-upgrade-center-design.md",
        "docs/v1-data-compatibility.md",
        "docs/upgrade-runner-lifecycle.md",
        "docs/backup-recovery.md",  # 客户恢复五步与红线（根 README「Backup & Recovery」入口）
        "docs/upgrade-chain.md",  # 受支持链路与顺序铁律（deployment.md 引用 + 版本矩阵夹具）
        "docs/releases/v0.2.md",  # 历史版本说明（根 README 入口；版本节只增不删）
        # —— ②/③ 门禁夹具与构建输入（被代码读取，缺了门禁会断） ——
        "docs/api.md",  # verify_api_docs.py 双向解析
        "docs/version-skew-matrix.md",  # US-01 门禁解析状态符号与硬规则
        "docs/cloudtower-api-version-matrix.md",  # 与 profiles.py 强制一致
        "docs/troubleshooting.md",  # test_us37_compose_guard 读取（客户可直接执行的操作）
        "docs/release-build-guide.md",  # 发布编排器一致性测试
        "docs/upgrade-package-ledger.md",  # verify_changelog/verify_release_verification 核对 SHA
        "docs/releases/CHANGELOG.md",  # 面向使用者的更新说明 + 打包前 assert 已发布
        # —— 脚本目录使用说明 ——
        "ops/README.md",
    }
)

#: TRACKED_DOCS 里**被代码或门禁真实读取/打包必需**的子集：缺了会让门禁静默失效。
REQUIRED_DOCS: frozenset[str] = frozenset(
    {
        "README.md",  # build_upgrade_package 改写版本号
        "README.zh-CN.md",  # build_upgrade_package 改写版本号
        "delivery/README.md",  # 交付包 README（build_offline_delivery --readme）
        "docs/api.md",  # verify_api_docs.py
        "docs/version-skew-matrix.md",  # test_us01
        "docs/cloudtower-api-version-matrix.md",  # test_cloudtower_api_version_matrix
        "docs/troubleshooting.md",  # test_us37_compose_guard
        "docs/release-build-guide.md",  # test_release_delivery_orchestrator
        "docs/upgrade-package-ledger.md",  # verify_changelog / verify_release_verification
        "docs/releases/CHANGELOG.md",  # 打包 gate + 面向使用者
    }
)

#: 内部开发文档的特征：命中即「不该进版本库」，与 TRACKED_DOCS 无关地独立拦截。
INTERNAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^docs/superpowers/", "设计稿与实施计划（docs/superpowers/）"),
    (r"^docs/archive/", "历史归档"),
    (r"^(progress|findings|task_plan)\.md$", "工作日志/发现/计划（根目录）"),
    (r"^delivery/README\.verified\.md$", "交付命令验证状态清单（内部验证记录）"),
    (r"^docs/pending-tasks\.md$", "待办台账"),
    (r"^docs/doc-map\.md$", "文档总索引（内部导航）"),
    (r"^docs/upgrade-(issues|strategy-issues|audit-matrix|remediation-roadmap|architecture-options)\.md$", "问题台账/矩阵/路线图"),
    (r"^docs/version-governance\.md$", "版本治理内部规则"),
    (r"^docs/release-acceptance\.md$", "发布验收内部清单"),
    (r"^docs/test-(architecture|process-and-scope)\.md$", "测试架构与执行规范"),
    (r"^docs/project-guide-for-ai\.md$", "AI 协作背景文档"),
    (r"^docs/development-verification-process\.md$", "开发验证流程（含内部机器信息）"),
    (r"^docs/delivery-handover-guide\.md$", "交接指南"),
    (r"^docs/(functional-modules|module-inventory|task-worker-evaluation|frontend-style-guide)\.md$", "内部盘点/风格规范"),
    (r"^docs/project-progress-", "项目进展归档"),
    (r"^docs/v0\.5\.", "历史升级计划与工作日志"),
    (r"^docs/v2-(implementation-sequence|rebuild-task-plan)\.md$", "v2 内部实施序列"),
    (r"^docs/releases/(release-verification-|version-archives)", "内部版本验证记录与历史归档"),
    (r"^docs/ai-handoff-", "AI 交接文档"),
    (r"^docs/test-handover-", "测试交接文档"),
)

#: 允许进入版本控制的**脚本**（`scripts/`、`ops/`、根目录 `*.sh`）。
#: 判据同文档：①客户会执行（随交付包分发或文档让用户跑）②构建/打包必需
#: ③门禁/测试夹具。**开发自用工具一律不提交**——一次性探针、数据集生成、
#: 数据完整性比对、链路演练、矩阵取证、历史版本校验脚本等，用完只留本地。
TRACKED_SCRIPTS: frozenset[str] = frozenset(
    {
        # —— 交付给客户的运维脚本（会打进升级包 project/ 载荷）——
        "scripts/bind-mount-recover.sh",
        "scripts/verify_site_acceptance.sh",
        "ops/install.sh",
        "ops/upgrade.sh",
        "ops/repair-layout-migration.sh",
        # —— 文档让用户执行的基线工具 ——
        "scripts/capture_baseline.py",
        # —— 构建与打包链（ops/package.sh 直接调用）——
        "ops/package.sh",
        "ops/check-deps.sh",
        "ops/lib/common.sh",
        "pre_install.sh",
        "scripts/build_upgrade_package.py",
        "scripts/build_runner_component_package.py",
        "scripts/build_offline_delivery.py",
        "scripts/build_bundle_upgrade_package.py",
        "scripts/build_prometheus_component_package.py",
        "scripts/build_release_delivery.sh",
        # —— 门禁（缺一即构建链断）——
        "scripts/verify_upgrade_package_identity.py",
        "scripts/verify_runner_delivery_consistency.py",
        "scripts/verify_migrations_expand_only.py",
        "scripts/verify_upgrade_plan_vocabulary.py",
        "scripts/verify_api_docs.py",
        "scripts/verify_changelog.py",
        "scripts/verify_release_docs_safe.py",
        "scripts/verify_release_verification.py",
        "scripts/verify_repo_doc_scope.py",
        # —— 交付物本体（随离线交付目录发给客户）——
        "delivery/install/install.sh",
        "delivery/upgrade/upgrade.sh",
        "delivery/compose-guard.sh",
        # —— 本门禁自身的执行机制 ——
        "scripts/hooks/pre-commit",
        "scripts/install_git_hooks.sh",
    }
)

#: 开发自用脚本的特征：命中即拦截（独立于 TRACKED_SCRIPTS 白名单）。
INTERNAL_SCRIPT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^scripts/probe_", "一次性探针（探查外部 API 字段，非产品功能）"),
    (r"^scripts/seed_", "测试数据集生成（仅验证机）"),
    (r"^scripts/verify_data_integrity\.py$", "数据完整性比对的演练工具（仅验证机）"),
    (r"^scripts/verify_full_upgrade_chain\.py$", "整链路演练（仅验证机）"),
    (r"^scripts/verify_upgrade_center_v\d+.*\.py$", "历史版本一次性校验"),
    (r"^scripts/verify_remote_", "远程环境一次性取证"),
    (r"^scripts/release_smoke_check\.py$", "发布冒烟（人工一次性）"),
    (r"^scripts/fix_dockerhub_", "线上 tag 一次性补救"),
    (r"^ops/evidence\.sh$", "升级矩阵取证（内部 QA）"),
)

#: .gitignore 必须覆盖的模式（防止 `git add -A` 把内部文档加回来）。
GITIGNORE_REQUIRED: tuple[str, ...] = (
    "docs/superpowers/",
    "docs/archive/",
    "progress.md",
    "findings.md",
    "task_plan.md",
    "docs/pending-tasks.md",
    "docs/doc-map.md",
    "delivery/README.verified.md",
    "docs/ai-handoff-*.md",
    "docs/test-handover-*.md",
    "docs/releases/release-verification-*.md",
    "scripts/probe_*.py",
    "scripts/seed_*.py",
    "scripts/verify_data_integrity.py",
    "scripts/verify_full_upgrade_chain.py",
    "scripts/verify_upgrade_center_v*.py",
    "scripts/verify_remote_*.py",
    "scripts/release_smoke_check.py",
    "scripts/fix_dockerhub_*.sh",
    "ops/evidence.sh",
)


def _sample(items: list[str], limit: int = 6) -> str:
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f" … 等 {len(items)} 个"


def _tracked_markdown() -> list[str] | None:
    """版本控制里的 .md 清单。非 git 树（`.3` 的 archive 构建树）返回 None。"""
    result = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _staged_markdown() -> list[str] | None:
    """暂存区（本次提交将新增/修改）的 .md 清单。pre-commit 用。"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "--", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _fs_internal_docs() -> list[str]:
    """没有 git 时（archive 构建树）兜底：直接扫文件系统里有没有内部文档。"""
    found: list[str] = []
    for pattern, label in INTERNAL_PATTERNS:
        if pattern.startswith("^docs/") and pattern.endswith("/"):
            base = pattern[1:].rstrip("/")
            for hit in sorted((ROOT / base).rglob("*.md")):
                found.append(f"{hit.relative_to(ROOT).as_posix()}（{label}）")
    for name in ("progress.md", "findings.md", "task_plan.md"):
        if (ROOT / name).is_file():
            found.append(f"{name}（工作日志/发现/计划，只留本地）")
    return found


def _tracked_scripts() -> list[str] | None:
    """版本控制里的脚本清单（scripts/、ops/、根目录 *.sh）。非 git 树返回 None。"""
    result = subprocess.run(
        ["git", "ls-files", "scripts", "ops", "delivery", "*.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [
        line
        for line in result.stdout.splitlines()
        if line.strip() and not line.endswith(".md")
    ]


def _staged_scripts() -> list[str] | None:
    """本次提交将新增的脚本（排除删除；改已受控脚本不算新增）。"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "--", "scripts", "ops", "delivery", "*.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [
        line
        for line in result.stdout.splitlines()
        if line.strip() and not line.endswith(".md")
    ]


def _script_blockers(paths: list[str]) -> list[str]:
    blocked: list[str] = []
    for path in paths:
        reason = None
        if path not in TRACKED_SCRIPTS:
            reason = "不在允许提交的脚本白名单内（开发自用工具只留本地）"
        else:
            for pattern, label in INTERNAL_SCRIPT_PATTERNS:
                if re.search(pattern, path):
                    reason = f"命中开发脚本特征：{label}"
                    break
        if reason:
            blocked.append(f"{path} —— {reason}")
    return blocked


def _check_scripts(checks: list[dict]) -> None:
    tracked = _tracked_scripts()
    if tracked is None:
        checks.append(
            {
                "name": "no_unlisted_tracked_scripts",
                "ok": True,
                "skipped": True,
                "message": "SKIP：非 git 树无索引可查",
            }
        )
        return
    blocked = _script_blockers(tracked)
    checks.append(
        {
            "name": "no_unlisted_tracked_scripts",
            "ok": not blocked,
            "message": (
                f"{len(tracked)} 个受控脚本全部是产品/构建/交付所需"
                if not blocked
                else f"{len(blocked)} 个开发自用脚本在版本控制里：{_sample(blocked)}"
            ),
        }
    )


def check_staged() -> list[dict]:
    """pre-commit 专用：只看**本次提交要加进去的 .md**，不要求全仓夹具齐备。

    为什么单独一条路径：pre-commit 需要在 `git commit` 时跑得又快又准，
    而且此时工作树里可能还有未暂存的改动（不该被判定）。
    """
    checks: list[dict] = []
    staged = _staged_markdown()
    if staged is None:
        checks.append(
            {
                "name": "staged_doc_scope",
                "ok": True,
                "skipped": True,
                "message": "SKIP：无法读取暂存区（非 git 环境）",
            }
        )
        return checks

    blocked: list[str] = []
    for path in staged:
        reason = None
        if path not in TRACKED_DOCS:
            reason = "不在允许提交的 .md 白名单内（内部开发文档应加 .gitignore）"
        else:
            for pattern, label in INTERNAL_PATTERNS:
                if re.search(pattern, path):
                    reason = f"命中内部文档特征：{label}"
                    break
        if reason:
            blocked.append(f"{path} —— {reason}")

    checks.append(
        {
            "name": "staged_doc_scope",
            "ok": not blocked,
            "message": (
                f"{len(staged)} 个待提交 .md 全部是允许的（客户文档 / 门禁夹具）"
                if not blocked
                else f"{len(blocked)} 个不该提交的文档被拦下：{_sample(blocked)}"
            ),
        }
    )

    # 脚本同样只放业务相关：开发自用工具（探针、数据集生成、链路演练、
    # 一次性取证/补救）不进仓库。
    staged_scripts = _staged_scripts()
    if staged_scripts is None:
        checks.append(
            {
                "name": "staged_script_scope",
                "ok": True,
                "skipped": True,
                "message": "SKIP：无法读取暂存区（非 git 环境）",
            }
        )
    else:
        blocked_scripts = _script_blockers(staged_scripts)
        checks.append(
            {
                "name": "staged_script_scope",
                "ok": not blocked_scripts,
                "message": (
                    f"{len(staged_scripts)} 个待提交脚本全部是产品/构建/交付所需"
                    if not blocked_scripts
                    else f"{len(blocked_scripts)} 个开发自用脚本被拦下：{_sample(blocked_scripts)}"
                ),
            }
        )
    return checks


def check() -> list[dict]:
    checks: list[dict] = []

    missing = sorted(p for p in REQUIRED_DOCS if not (ROOT / p).is_file())
    checks.append(
        {
            "name": "required_docs_exist",
            "ok": not missing,
            "message": "全部在位" if not missing else f"缺失（门禁会静默失效）：{missing}",
        }
    )

    tracked = _tracked_markdown()
    if tracked is None:
        # 非 git 树（`.3` 用 git archive 构建的形态）：没有索引可查，
        # 改为扫文件系统里的内部文档——这正是「已提交内容」的镜像。
        leaked = _fs_internal_docs()
        checks.append(
            {
                "name": "no_internal_docs_tracked",
                "ok": not leaked,
                "message": (
                    "非 git 树：文件系统扫描未见内部开发文档"
                    if not leaked
                    else f"build 树里混入了内部文档：{_sample(leaked)}"
                ),
            }
        )
        checks.append(
            {
                "name": "no_unlisted_tracked_docs",
                "ok": True,
                "skipped": True,
                "message": "SKIP：非 git 树无索引可比；白名单校验由 no_internal_docs_tracked 兜底",
            }
        )
        _check_gitignore(checks)
        _check_dead_links(checks)
        _check_internal_refs(checks)
        _check_scripts(checks)
        return checks

    unlisted = sorted(set(tracked) - TRACKED_DOCS)
    checks.append(
        {
            "name": "no_unlisted_tracked_docs",
            "ok": not unlisted,
            "message": (
                f"{len(tracked)} 个受控 .md 全部在清单内"
                if not unlisted
                else f"{len(unlisted)} 个未登记的 .md（内部文档应加 .gitignore；确是夹具才登记进 TRACKED_DOCS）：{_sample(unlisted)}"
            ),
        }
    )

    internal: list[tuple[str, str]] = []
    for path in tracked:
        for pattern, label in INTERNAL_PATTERNS:
            if re.search(pattern, path):
                internal.append((path, label))
                break
    checks.append(
        {
            "name": "no_internal_docs_tracked",
            "ok": not internal,
            "message": (
                "零个内部开发文档在版本控制中"
                if not internal
                else f"{len(internal)} 个内部文档仍在版本控制：{_sample([p for p, _ in internal])}"
            ),
        }
    )

    _check_gitignore(checks)
    _check_dead_links(checks)
    _check_internal_refs(checks)
    _check_scripts(checks)

    return checks


def _check_gitignore(checks: list[dict]) -> None:
    ignore_text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.is_file() else ""
    ignore_lines = {line.strip() for line in ignore_text.splitlines() if line.strip()}
    uncovered = [p for p in GITIGNORE_REQUIRED if p not in ignore_lines]
    checks.append(
        {
            "name": "gitignore_covers_internal",
            "ok": not uncovered,
            "message": ".gitignore 已覆盖全部内部文档模式" if not uncovered else f".gitignore 缺少：{uncovered}",
        }
    )


def _check_dead_links(checks: list[dict]) -> None:
    dead: list[str] = []
    for path in sorted(TRACKED_DOCS):
        local = ROOT / path
        if not local.is_file():
            continue
        for target in _relative_md_links(local):
            resolved = (local.parent / target).resolve()
            try:
                rel = resolved.relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                continue
            if rel not in TRACKED_DOCS:
                dead.append(f"{path} → {rel}")
    checks.append(
        {
            "name": "no_dead_doc_links",
            "ok": not dead,
            "message": (
                f"{len(TRACKED_DOCS)} 个受控文档的相对链接全部落在受控集合内"
                if not dead
                else f"{len(dead)} 条链接指向未受控文档（公开仓库里是死链）：{_sample(dead)}"
            ),
        }
    )


#: 「提到了内部文档路径」的引用形态（Markdown 链接、反引号路径、裸路径都算）。
#: 与 `_relative_md_links` 互补：后者只看合法 Markdown 链接，这里抓纯文本提及。
_INTERNAL_REF_RE = re.compile(
    r"(?:docs/(?:superpowers|archive)/[\w./-]+"
    r"|docs/(?:pending-tasks|doc-map|version-governance|release-acceptance)\.md"
    r"|docs/upgrade-(?:issues|strategy-issues|audit-matrix|remediation-roadmap|architecture-options)\.md"
    r"|docs/(?:test-architecture|test-process-and-scope|project-guide-for-ai)\.md"
    r"|docs/(?:development-verification-process|delivery-handover-guide)\.md"
    r"|docs/releases/(?:release-verification-[\w.-]+|version-archives)\.md"
    r"|(?<![\w/])(?:progress|findings|task_plan)\.md)"
)

#: 允许出现内部引用的受控文档——历史记录类，**只增不删不改写**（用户 2026-10-21 定）。
_INTERNAL_REF_ALLOWED: frozenset[str] = frozenset(
    {
        "docs/releases/CHANGELOG.md",  # 历史版本节只增不删
        "docs/upgrade-package-ledger.md",  # 包台账是历史审计链
        "docs/version-skew-matrix.md",  # 被 US-01 门禁解析，改动需同步测试
    }
)


def _internal_refs(path: Path) -> list[str]:
    """抽出受控文档里**纯文本**提到的内部文档路径（不含 Markdown 链接，那个由上一条查）。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    hits: list[str] = []
    for match in _INTERNAL_REF_RE.finditer(text):
        token = match.group(0)
        # 跳过本来就是链接目标的（交给 no_dead_doc_links 报更准的错误）
        if f"]({token}" in text or f"]({token}#" in text:
            continue
        hits.append(token)
    return hits


def _check_internal_refs(checks: list[dict]) -> None:
    leaks: list[str] = []
    for path in sorted(TRACKED_DOCS):
        if path in _INTERNAL_REF_ALLOWED:
            continue
        local = ROOT / path
        if not local.is_file():
            continue
        for token in _internal_refs(local):
            leaks.append(f"{path} 提到 {token}")
    checks.append(
        {
            "name": "no_internal_paths_in_public_docs",
            "ok": not leaks,
            "message": (
                f"{len(TRACKED_DOCS - _INTERNAL_REF_ALLOWED)} 个对外文档不再引用内部文档路径"
                if not leaks
                else f"{len(leaks)} 处引用了公开仓库不存在的内部路径（客户 clone 后看不到）：{_sample(leaks)}"
            ),
        }
    )


_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+?\.md)(?:#[^)\s]*)?\)")


def _relative_md_links(path: Path) -> list[str]:
    """抽出 Markdown 里指向本地 .md 的相对链接（跳过 http/https/锚点）。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    targets: list[str] = []
    for match in _LINK_RE.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        targets.append(target)
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="仓库文档范围门禁")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="只校验**本次提交要加进去的 .md**（pre-commit 用，快且不受未暂存改动影响）",
    )
    args = parser.parse_args(argv)

    checks = check_staged() if args.staged else check()
    failed = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"checks": checks, "failed": len(failed)}, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            if item.get("skipped"):
                mark = "SKIP"
            else:
                mark = "PASS" if item["ok"] else "FAIL"
            print(f"[{mark}] {item['name']} — {item['message']}")
        print()
        print(f"汇总：PASS={len(checks) - len(failed)} FAIL={len(failed)}")
        if not failed and not args.staged:
            print(f"仓库文档范围：{len(TRACKED_DOCS)} 个允许提交（客户文档 + 门禁夹具），其余只留本地")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
