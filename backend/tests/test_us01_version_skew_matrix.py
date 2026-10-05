"""US-01：版本偏斜支持矩阵的**门禁**。

矩阵（`docs/version-skew-matrix.md`）是"把偏斜从隐患变成已知边界"的手段。但如果它
只是文档，很容易在下一次改动后悄悄失真——比如某个组合被写成"支持"却从未实测。

本门禁强制：
1. 矩阵里出现的每个源端/目标版本组合，状态必须取自允许集合；
2. 标 `✅`（实测支持）的组合，**必须在实测记录里有对应证据**（升级任务 ID 或
   "干净 VM 实测"记录），否则构建失败；
3. 标 `⚠️ 未实测` 的组合**必须显式带"未实测"字样**，不得被写成 ✅；
3.1 标 `⛔ 不支持` 的组合**必须写明到达路径**（含 `v0.5.3` 或「先升」）——拒绝必须带出路；
4. 三条硬规则必须在位（先平台后 runner / 不降级 / 单飞）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX = REPO_ROOT / "docs" / "version-skew-matrix.md"

# ⚠️ 里的变体选择符（U+FE0F）在不同工具链下可能被切掉，比较前先归一
# ⛔ = 明确不支持（2026-10-06 起：v0.5.4 只支持目标布局 v0.5.2+，
# ≤v0.5.1u2 必须先升 v0.5.3）。它与 ⚠️ 的区别是**语义不同**：
# ⚠️ = 声明支持但未实测；⛔ = 不支持并给出到达路径。两者都不得含糊，但要求也不同。
ALLOWED_STATES = {"✅", "⚠", "⛔"}


class VersionSkewMatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(MATRIX.is_file(), "缺少 docs/version-skew-matrix.md")
        self.text = MATRIX.read_text(encoding="utf-8")

    def _rows(self) -> list[tuple[str, str]]:
        """解析支持矩阵表格：| 源端 | → 目标 | 支持 | 源端逻辑 | 备注 |

        返回 [(源端, 支持状态及备注)]。注意"→ 目标"是**目标列**，
        支持状态在**第三列**——早期版本曾误取第二列，把 "v0.5.3" 当成状态。
        """
        rows = []
        for line in self.text.splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 3:
                continue
            if cells[0] in ("源端", "想要的加固") or set(cells[0]) <= {"-"}:
                continue
            if not cells[0].startswith("v0."):
                continue
            # 支持状态 + 其后备注合并为一格，便于同时校验"实测证据"与"未实测"标注
            rows.append((cells[0], " ".join(cells[2:]).strip()))
        return rows

    def test_matrix_has_rows(self) -> None:
        rows = self._rows()
        self.assertGreaterEqual(len(rows), 5, f"矩阵行数不足：{rows}")

    def test_every_row_state_is_allowed(self) -> None:
        for source, target in self._rows():
            state = (target[0] if target else "").replace("\ufe0f", "")
            self.assertIn(
                state, ALLOWED_STATES,
                f"组合「{source}」的支持状态 '{state}' 不在允许集合 {ALLOWED_STATES} 内",
            )

    def test_unverified_rows_are_explicitly_marked(self) -> None:
        """标 ⚠️ 的组合必须写明"未实测"，不得含糊。"""
        warned = [r for r in self._rows() if r[1].lstrip().startswith("⚠")]
        for source, target in warned:
            self.assertIn(
                "未实测", target,
                f"组合「{source}」标了 ⚠️ 却没写明'未实测'——不得让客户误以为已验证",
            )
        self.assertTrue(warned, "矩阵应至少保留一个'声明支持但未实测'的行（诚实标注的体现）")

    def test_unsupported_rows_state_the_path_to_reach(self) -> None:
        """标 ⛔ 的组合必须写明**到达路径**（含 v0.5.3 或「先升」字样）。

        这是「不静默降级」的文档版：拒绝必须带出路。只写"不支持"的行等于把
        客户挡在门外却不告诉他怎么走——下一个人只会当成 bug。
        """
        blocked = [r for r in self._rows() if r[1].lstrip().startswith("⛔")]
        self.assertTrue(blocked, "矩阵应保留至少一个明确不支持的行（收窄支持矩阵的体现）")
        for source, target in blocked:
            self.assertTrue(
                "v0.5.3" in target or "先升" in target,
                f"组合「{source}」标了 ⛔ 却没写明到达路径（需含 v0.5.3 或「先升」）：{target}",
            )

    def test_verified_rows_have_evidence(self) -> None:
        """标 ✅ 的组合必须给出证据（任务 ID 或干净 VM 实测记录）。"""
        verified = [r for r in self._rows() if r[1].lstrip().startswith("✅")]
        self.assertTrue(verified, "应有已实测支持的组合")
        for source, target in verified:
            self.assertRegex(
                target,
                r"upgrade-[0-9a-f]+|干净 VM|实测",
                f"组合「{source}」标 ✅ 但没有实测证据：{target}",
            )

    def test_hard_rules_are_present(self) -> None:
        """三条硬规则必须在位（偏斜期间最容易踩的就是顺序与降级）。"""
        for rule in ("先平台、后 runner", "不得被降级", "只允许一个升级任务"):
            self.assertIn(rule, self.text, f"矩阵缺少硬规则：{rule}")

    def test_explains_why_no_code_fix(self) -> None:
        """必须写清"为什么不做代码级重构"——否则后人会以为是漏做。"""
        self.assertIn("业界常态", self.text)
        self.assertIn("当次升级用不到", self.text)
        self.assertIn("不做代码级重构", self.text)

    def test_placement_guidance_present(self) -> None:
        """必须有"加固该放哪一侧"的指引，否则下次还会把加固加错地方。"""
        self.assertIn("加固该放在哪一侧", self.text)
        self.assertIn("构建期门禁", self.text)

    def test_matrix_is_registered_in_doc_map(self) -> None:
        doc_map = (REPO_ROOT / "docs" / "doc-map.md").read_text(encoding="utf-8")
        self.assertIn("version-skew-matrix.md", doc_map, "新文档必须登记到 docs/doc-map.md")

    def test_matrix_refers_to_issue_and_governance(self) -> None:
        for ref in ("upgrade-strategy-issues.md", "version-governance.md", "upgrade-chain.md"):
            self.assertIn(ref, self.text, f"矩阵应引用 {ref}")


if __name__ == "__main__":
    unittest.main()
