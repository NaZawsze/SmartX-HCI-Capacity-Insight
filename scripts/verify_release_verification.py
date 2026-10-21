#!/usr/bin/env python3
"""发布验证记录（内部文档）门禁。

**分工**（用户 2026-10-21 定）：

| 文档 | 读者 | 内容 |
| --- | --- | --- |
| `docs/releases/CHANGELOG.md` | **使用者** | 只写修复 / 新增 / 优化 / 已知问题（禁内部细节） |
| `docs/releases/release-verification-<version>.md` | 研发与交付负责人 | 包 SHA、任务 ID、验证机器、门禁明细、数据比对 |

本门禁检查**内部记录**是否与当前候选包一致、是否留下可复核的证据：

1. 当前 `VERSION` 对应的 `release-verification-<version>.md` 必须存在；
2. 文档里的平台包 SHA 必须与 `docs/upgrade-package-ledger.md` 最新「平台包」SHA 一致
   （包换轮次而内部记录没跟 → FAIL）；
3. 必须记录 runner 组件包 SHA；
4. 必须出现真实的升级任务 ID（`upgrade-…`）与数据比对结论（`N PASS`）作为证据；
5. 必须写明验证机器（`.12` / `.14`）——本文件允许出现机器标识（CHANGELOG 里禁止）；
6. 必须有一行如实的发布状态（未发布 / 已发布）。

用法：

    python3 scripts/verify_release_verification.py [--version v0.5.4] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "docs" / "releases"
LEDGER = ROOT / "docs" / "upgrade-package-ledger.md"
VERSION_FILE = ROOT / "VERSION"
SHA_RE = re.compile(r"\b([0-9a-f]{64})\b")
TASK_RE = re.compile(r"upgrade-[0-9a-f]{8,}")
PASS_RE = re.compile(r"\d+\s*PASS")


def _sha_on_line_containing(text: str, marker: str) -> str | None:
    """在**同一行**里同时含 marker 与完整 64 位 hex 的行上取该 SHA。

    不能用 `平台包[\\s\\S]{0,300}?<sha>` 这类跨行正则——它会吃掉后面无关的 SHA
    （2026-10-21 实测：`runner 组件包 \`短 SHA…\`` 那行之后的平台包 SHA 被误当成 runner 的）。
    """
    for line in text.splitlines():
        if marker not in line:
            continue
        found = SHA_RE.search(line)
        if found:
            return found.group(1)
    return None


def _latest_ledger_platform_sha() -> str | None:
    """ledger 里"当前有效"的**平台包** SHA。

    取值优先级（2026-10-21 同日重发 v2 时连踩两次）：
    1. 同时含「当前有效」与「平台包」且带 64 位 hex 的行（台账显式标记有效条目）；
    2. 否则取最后一次「平台包 … <64hex>」匹配。
    **注意**：不能只看「当前」——ledger 里 runner 组件包的行也带"当前"/"USE" 字样，
    会把 runner 包的 SHA 误当成平台包的（实测踩到 `dd096bf2…`）。
    """
    if not LEDGER.is_file():
        return None
    text = LEDGER.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "当前有效" in line and "平台包" in line:
            found = SHA_RE.search(line)
            if found:
                return found.group(1)
    matches = re.findall(r"平台包[\s\S]{0,300}?\b([0-9a-f]{64})\b", text)
    return matches[-1] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", help="版本号（默认读仓库 VERSION）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    version = (args.version or VERSION_FILE.read_text(encoding="utf-8").strip()).strip()
    doc = RELEASES / f"release-verification-{version}.md"
    checks: list[dict] = []

    def ok(name: str, message: str = "") -> None:
        checks.append({"name": name, "ok": True, "message": message})

    def fail(name: str, message: str) -> None:
        checks.append({"name": name, "ok": False, "message": message})

    if not doc.is_file():
        # 内部验证记录**不随公开仓库分发**（2026-10-21「仓库只放代码」）。
        # 判据：若 releases 目录下一条内部验证记录都没有，说明这是公开/归档树
        # （`.3` 用 `git archive` 构建的就是这种形态），门禁无记录可校 → SKIP。
        # 不能 FAIL——否则发布编排器在任何基于 archive 的构建树上都会中止。
        # 反之，若存在别的版本记录却缺本期，说明是**该写没写** → FAIL。
        others = sorted(RELEASES.glob("release-verification-*.md"))
        if not others:
            checks.append(
                {
                    "name": "verification_doc_exists",
                    "ok": True,
                    "skipped": True,
                    "message": (
                        "SKIP：本树不含任何内部验证记录（内部记录不随公开仓库分发）；"
                        "该门禁需在持有内部记录的开发/发布树上运行"
                    ),
                }
            )
        else:
            fail("verification_doc_exists", f"缺少本期内部验证记录：{doc.relative_to(ROOT)}")
        text = ""
    else:
        ok("verification_doc_exists", str(doc.relative_to(ROOT)))
        text = doc.read_text(encoding="utf-8")

    if text:
        # 2) 平台包 SHA 与 ledger 最新一致
        platform_sha = _sha_on_line_containing(text, "平台包")
        ledger_sha = _latest_ledger_platform_sha()
        if not platform_sha:
            fail("platform_sha_present", "未记录平台包 SHA")
        elif ledger_sha is None:
            # 包台账属内部开发记录，不随公开仓库分发；本地开发机上仍在时做交叉校验。
            checks.append(
                {
                    "name": "platform_sha_matches_ledger",
                    "ok": True,
                    "skipped": True,
                    "message": "SKIP：本树不含包台账（内部记录），无法交叉校验 SHA",
                }
            )
        elif platform_sha != ledger_sha:
            fail(
                "platform_sha_matches_ledger",
                f"平台包 SHA {platform_sha[:12]}… 与 ledger 最新 {ledger_sha[:12]}… 不一致",
            )
        else:
            ok("platform_sha_matches_ledger", platform_sha[:12] + "…")

        # 3) runner 组件包 SHA
        if _sha_on_line_containing(text, "runner 组件包"):
            ok("runner_sha_present")
        else:
            fail("runner_sha_present", "未记录 runner 组件包 SHA")

        # 4) 证据：任务 ID + 数据比对
        tasks = sorted(set(TASK_RE.findall(text)))
        if tasks:
            ok("task_ids_present", f"{len(tasks)} 个任务 ID")
        else:
            fail("task_ids_present", "未记录升级任务 ID（无法复核）")
        if PASS_RE.search(text):
            ok("data_comparison_present")
        else:
            fail("data_comparison_present", "未记录数据比对结果（N PASS）")

        # 5) 验证机器
        machines = sorted({m for m in (".12", ".14") if m in text})
        if len(machines) >= 1:
            ok("verification_machines_present", ", ".join(machines))
        else:
            fail("verification_machines_present", "未写明验证机器")

        # 6) 发布状态
        if re.search(r"未发布|已发布", text):
            ok("release_status_stated")
        else:
            fail("release_status_stated", "未写明发布状态（未发布/已发布）")

    failed = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"version": version, "checks": checks, "failed": len(failed)}, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            if item.get("skipped"):
                mark = "SKIP"
            else:
                mark = "PASS" if item["ok"] else "FAIL"
            detail = f" — {item['message']}" if item.get("message") else ""
            print(f"[{mark}] {item['name']}{detail}")
        print()
        print(f"汇总：PASS={len(checks) - len(failed)} FAIL={len(failed)}（{version}）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
