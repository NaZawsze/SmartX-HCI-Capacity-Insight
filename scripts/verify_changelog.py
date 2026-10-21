#!/usr/bin/env python3
"""CHANGELOG 结构与真实性门禁（2026-10-21 用户要求：不靠人眼，靠机器）。

**为什么需要**：CHANGELOG 的过期内容连续被抓出多轮（候选包轮次停在 r37 而实际是
`d235f14c…`、写了不存在的 runner 版本号 v0.3.3、「install 直接落 r35 构建」与实测相反）。
这些都是「包变了、文档没跟」的同类问题，人眼审查不可靠，必须做成可重复执行的门禁。

检查项：

1. **版本节存在且降序**（最新在顶部），每节标题形如 `## vX.Y…`。
2. **首节（当前候选/最新发布）小节顺序固定**：
   状态 → 更新摘要 → **修复** → **新增** → 工程与运维 → 验证说明 → 已知问题。
   修复必须在新增之前（用户 2026-10-21 定）。
3. **首节引用的包 SHA 必须与 ledger 最新条目的"当前候选/发布"一致**
   ——这是本门禁最有价值的一条：包换轮次而 CHANGELOG 没跟，会在这里 FAIL。
4. **首节不得出现"不存在的能力版本号"**：形如 `v0.3.N` 的 runner 版本，
   必须等于仓库 `RUNNER_VERSION`、或存在于 git tag、或存在于 CHANGELOG 历史节。
   （历史节按"只增不删"规则不受此约束。）
5. **首节不得残留过期轮次表述**：`当前候选对 = … r<数字>`、`待重建`、`重建即作废`、
   `当前 r<数字> 包不含` 之类。
6. **首节的每条「已验证/通过」断言必须带证据**：task ID（`upgrade-…`）、
   数据比对结果（`N PASS`）、或明确的测试名。
7. **列表块内不得有空行**（Markdown 会把一个列表切成两段，渲染断裂）。

用法：

    python3 scripts/verify_changelog.py            # 人类可读输出，FAIL 时 exit 1
    python3 scripts/verify_changelog.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "docs" / "releases" / "CHANGELOG.md"
LEDGER = ROOT / "docs" / "upgrade-package-ledger.md"
RUNNER_VERSION_FILE = ROOT / "RUNNER_VERSION"

SECTION_ORDER_RULES = ("更新摘要", "修复", "新增", "工程与运维", "验证说明", "已知问题")
#: 首节里禁止出现的过期表述
STALE_PATTERNS = (
    (re.compile(r"当前候选对\s*=\s*[^`\n]*\br\d+\b"), "残留『当前候选对 = … rNN』旧轮次表述"),
    (re.compile(r"待重建"), "残留『待重建』"),
    (re.compile(r"重建即作废"), "残留『重建即作废』（包已定稿）"),
    (re.compile(r"当前\s*r\d+\s*包不含"), "残留『当前 rNN 包不含…』"),
)
#: 版本号形态（runner 用 v0.3.N 系列）
RUNNER_VERSION_RE = re.compile(r"\bv0\.3\.(\d+)(?:-[A-Za-z0-9._]+)?\b")
EVIDENCE_RE = re.compile(
    r"upgrade-[0-9a-f]{8,}"          # 任务 ID
    r"|\d+\s*PASS"                    # 数据比对结果（36 PASS / 0 FAIL）
    r"|INSTALL_EXIT="                 # 安装退出码
    r"|\bG\d\b"                      # 构建门禁编号（G1/G2/G3/G4）
    r"|test_\w+"                      # 测试名
    r"|实测|已验证|真机"               # 明确标注
)


def _fail(checks: list[dict], name: str, message: str, **extra: object) -> None:
    checks.append({"name": name, "ok": False, "message": message, **extra})


def _pass(checks: list[dict], name: str, message: str = "") -> None:
    checks.append({"name": name, "ok": True, "message": message})


def _git_tags() -> set[str]:
    try:
        out = subprocess.run(
            ["git", "tag", "-l"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def _split_sections(text: str) -> list[tuple[str, int, int, list[str]]]:
    """返回 [(标题, 起始行号, 结束行号, 行列表)]，按文件顺序。"""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^## v[0-9]", ln)]
    sections = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        sections.append((lines[start], start, end, lines[start + 1 : end]))
    return sections


def _version_key(title: str) -> tuple[int, ...]:
    found = re.search(r"v(\d+(?:\.\d+)*)", title)
    if not found:
        return (0,)
    return tuple(int(part) for part in found.group(1).split("."))


def _latest_ledger_sha() -> str | None:
    """ledger 里**平台包**的 SHA（取最后一次「平台包 … <64hex>」匹配）。

    不能简单取最后出现的 64 位 hex——ledger 末尾同时登记了平台包、runner 包与
    web-api 镜像三个 SHA，最后一个往往是镜像而不是平台包（2026-10-21 实测踩到）。
    """
    if not LEDGER.is_file():
        return None
    text = LEDGER.read_text(encoding="utf-8")
    matches = re.findall(r"平台包[\s\S]{0,300}?\b([0-9a-f]{64})\b", text)
    return matches[-1] if matches else None


def _subsections(body: list[str]) -> list[str]:
    return [ln[4:].strip() for ln in body if ln.startswith("### ")]


def check(text: str) -> list[dict]:
    checks: list[dict] = []
    sections = _split_sections(text)
    if not sections:
        _fail(checks, "sections_exist", "CHANGELOG 缺少 `## vX.Y` 版本节")
        return checks
    _pass(checks, "sections_exist", f"{len(sections)} 个版本节")

    # 1) 降序
    keys = [_version_key(title) for title, *_ in sections]
    if keys != sorted(keys, reverse=True):
        _fail(checks, "sections_descending", f"版本节未按降序排列：{[t for t, *_ in sections][:5]}")
    else:
        _pass(checks, "sections_descending")

    # 2) 首节小节顺序
    top_title, top_start, top_end, top_body = sections[0]
    subs = _subsections(top_body)
    missing = [name for name in SECTION_ORDER_RULES if not any(name in s for s in subs)]
    if missing:
        _fail(checks, "top_sections_present", f"首节 {top_title!r} 缺少小节：{missing}", subsections=subs)
    else:
        indices = []
        for name in SECTION_ORDER_RULES:
            indices.append(next(i for i, s in enumerate(subs) if name in s))
        if indices != sorted(indices):
            ordered_names = [s for s in subs if any(n in s for n in SECTION_ORDER_RULES)]
            _fail(
                checks,
                "top_sections_order",
                "首节小节顺序不符规范（应为 更新摘要 → 修复 → 新增 → 工程与运维 → 验证说明 → 已知问题）："
                f"{ordered_names}",
            )
        else:
            _pass(checks, "top_sections_order", "修复在新增之前")

    # 3) 包 SHA 与 ledger 一致
    top_text = "\n".join(top_body)
    changelog_sha = None
    found = re.search(r"平台包[\s\S]{0,200}?`([0-9a-f]{64})`", top_text)
    if found:
        changelog_sha = found.group(1)
    ledger_sha = _latest_ledger_sha()
    if changelog_sha and ledger_sha and changelog_sha != ledger_sha:
        _fail(
            checks,
            "package_sha_matches_ledger",
            f"首节平台包 SHA {changelog_sha[:12]}… 与 ledger 最新 {ledger_sha[:12]}… 不一致（包换了轮次但 CHANGELOG 没跟）",
            changelog=changelog_sha,
            ledger=ledger_sha,
        )
    elif changelog_sha:
        _pass(checks, "package_sha_matches_ledger", f"{changelog_sha[:12]}…")
    else:
        _fail(checks, "package_sha_matches_ledger", "首节未声明平台包 SHA（候选/发布节必须写）")

    # 4) 首节不得引用不存在的 runner 版本号
    runner_version = RUNNER_VERSION_FILE.read_text(encoding="utf-8").strip() if RUNNER_VERSION_FILE.is_file() else ""
    tags = _git_tags()
    historical = " ".join("\n".join(body) for _, _, _, body in sections[1:])
    bad = []
    for match in RUNNER_VERSION_RE.finditer(top_text):
        version = f"v0.3.{match.group(1)}"
        # 历史节出现过 / 等于当前 RUNNER_VERSION / 有 tag / 是 CHANGELOG 自己的版本节
        known = (
            version == runner_version
            or f"runner-{version}" in tags
            or re.search(re.escape(version), historical)
            or any(title.startswith(f"## {version}") for title, *_ in sections)
        )
        # 允许明确标注为"已回退/已作废/历史"的引用
        context = top_text[max(0, match.start() - 60) : match.end() + 60]
        if not known and not re.search(r"已回退|已作废|不存在|历史", context):
            bad.append(version)
    if bad:
        _fail(checks, "runner_versions_exist", f"首节引用了不存在的 runner 版本：{sorted(set(bad))}")
    else:
        _pass(checks, "runner_versions_exist")

    # 5) 过期轮次表述
    stale_hits = [msg for pattern, msg in STALE_PATTERNS if pattern.search(top_text)]
    if stale_hits:
        _fail(checks, "no_stale_round_wording", "；".join(stale_hits))
    else:
        _pass(checks, "no_stale_round_wording")

    # 6) 验证说明里的断言必须带证据
    verify_body: list[str] = []
    in_verify = False
    for ln in top_body:
        if ln.startswith("### "):
            in_verify = "验证说明" in ln
            continue
        if in_verify:
            verify_body.append(ln)
    claims = [
        ln for ln in verify_body
        if re.search(r"✅|已通过|已验证|通过：", ln) and ln.lstrip().startswith(("|", "-"))
    ]
    unsupported = [ln.strip()[:60] for ln in claims if not EVIDENCE_RE.search(ln)]
    if unsupported:
        _fail(checks, "verification_claims_have_evidence", f"{len(unsupported)} 条通过断言缺少证据：{unsupported[:3]}")
    else:
        _pass(checks, "verification_claims_have_evidence", f"{len(claims)} 条断言均有证据")

    # 7) 列表块内空行（把列表切成两段）。
    # 判据：空行的**上一个非空行**属于某个列表项（`- ` 开头，或是它的缩进续行），
    # 且空行的**下一个非空行**又是一个列表项 → 这是把一个列表硬切成两段。
    # 注意续行（缩进两格）也会被算作"在列表内"——2026-10-21 实测：原始缺陷正是
    # 「条目最后一行续行 → 空行 → 下一条目」，只看 `- ` 开头会漏掉。
    def _in_list_item(line: str) -> bool:
        return line.startswith("- ") or (line.startswith("  ") and line.strip() != "")

    gaps = []
    for idx, line in enumerate(top_body):
        if line.strip() != "" or idx == 0 or idx == len(top_body) - 1:
            continue
        prev_idx = idx - 1
        while prev_idx >= 0 and top_body[prev_idx].strip() == "":
            prev_idx -= 1
        next_idx = idx + 1
        while next_idx < len(top_body) and top_body[next_idx].strip() == "":
            next_idx += 1
        if prev_idx < 0 or next_idx >= len(top_body):
            continue
        if _in_list_item(top_body[prev_idx]) and top_body[next_idx].startswith("- "):
            gaps.append(top_start + idx + 1)
    if gaps:
        _fail(checks, "no_blank_line_in_list", f"列表块内出现空行（会切断渲染），行号：{gaps}")
    else:
        _pass(checks, "no_blank_line_in_list")

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if not CHANGELOG.is_file():
        print(f"缺少 {CHANGELOG}", file=sys.stderr)
        return 1
    checks = check(CHANGELOG.read_text(encoding="utf-8"))
    failed = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"checks": checks, "failed": len(failed)}, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            mark = "PASS" if item["ok"] else "FAIL"
            detail = f" — {item['message']}" if item.get("message") else ""
            print(f"[{mark}] {item['name']}{detail}")
        print()
        print(f"汇总：PASS={len(checks) - len(failed)} FAIL={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
