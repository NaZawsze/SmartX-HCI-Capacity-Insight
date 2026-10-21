"""CHANGELOG 门禁（`scripts/verify_changelog.py`）自身的回归锁。

**为什么需要**：CHANGELOG 的过期内容连续被抓出多轮（候选包轮次停在 r37 而实际是
`d235f14c…`、写了不存在的 runner 版本号、「install 直接落 r35 构建」与实测相反、
列表被空行切断）。用户 2026-10-21 明确要求「不靠人眼、靠机器」，因此把门禁做成脚本
（已接入 `scripts/build_release_delivery.sh` 步骤 5.5），这里再用单测锁住**门禁本身的
灵敏度**——否则门禁被弱化（正则写松、检查被删）也不会有任何提示。

分工（用户 2026-10-21 定）：`CHANGELOG.md` 面向**使用者**，只写修复/新增/优化/已知问题；
包 SHA、任务 ID、验证机器等内部细节写在 `docs/releases/release-verification-<version>.md`
（由 `scripts/verify_release_verification.py` 校验）。

每个用例都是「拿真实 CHANGELOG 做一处定向篡改 → 断言门禁必须 FAIL」，
对应一类真实发生过的缺陷。基线用例确保当前文件本身是干净的。
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "scripts" / "verify_changelog.py"
CHANGELOG = ROOT / "docs" / "releases" / "CHANGELOG.md"


def _load_gate():
    spec = importlib.util.spec_from_file_location("verify_changelog", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ChangelogGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = _load_gate()
        cls.original = CHANGELOG.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        # 每个用例后还原真实文件，避免失败用例污染工作树
        CHANGELOG.write_text(self.original, encoding="utf-8")

    def _names_failed(self, text: str) -> set[str]:
        return {c["name"] for c in self.gate.check(text) if not c["ok"]}

    def test_current_changelog_passes(self) -> None:
        """基线：仓库当前 CHANGELOG 必须通过全部门禁检查。"""
        failed = self._names_failed(self.original)
        self.assertEqual(failed, set(), f"当前 CHANGELOG 未通过：{failed}")

    def test_detects_internal_identifiers_in_changelog(self) -> None:
        """CHANGELOG 是给使用者看的：内部轮次号 / SHA / 机器号不得出现在正文。

        用户 2026-10-21：『这个是给其他用的人看的，自己看的你可以自己写一份』。
        """
        for snippet, expect in (
            ("状态：**未发布**。", "状态：**未发布**。当前候选包 r42 已验收。"),
            ("状态：**未发布**。", "状态：**未发布**。平台包 `d235f14ca4737b76dec4ac7ff0b42f09fdd0524a8548e067150b48a1b217af34`"),
            ("状态：**未发布**。", "状态：**未发布**。已在 .14 上验证。"),
            ("状态：**未发布**。", "状态：**未发布**。任务 upgrade-b9233ab5f27c8c1b succeeded。"),
        ):
            mutated = self.original.replace(snippet, expect, 1)
            self.assertNotEqual(mutated, self.original, f"夹具失效：{snippet!r}")
            self.assertIn("no_internal_identifiers", self._names_failed(mutated), expect)

    def test_detects_fix_after_feature(self) -> None:
        """『修复』排在『新增』之后（用户 2026-10-21 明确要求修复在前）。"""
        mutated = (
            self.original.replace("### 修复\n", "### __TMP__\n", 1)
            .replace("### 新增\n", "### 修复\n", 1)
            .replace("### __TMP__\n", "### 新增\n", 1)
        )
        self.assertNotEqual(mutated, self.original, "夹具失效：未找到小节标题")
        self.assertIn("top_sections_order", self._names_failed(mutated))

    def test_detects_stale_round_wording(self) -> None:
        """残留『当前候选对 = … rNN』这类旧轮次表述。"""
        mutated = self.original.replace(
            "状态：**未发布**。",
            "状态：**未发布**。当前候选对 = 平台 r37；",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("no_stale_round_wording", self._names_failed(mutated))

    def test_detects_nonexistent_runner_version(self) -> None:
        """引用不存在的 runner 版本号（历史真实问题：写了已回退的 v0.3.3）。"""
        mutated = self.original.replace(
            "### 修复\n",
            "### 修复\n\n- 升级执行器升级到 v0.3.9 后修复了若干问题。\n",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("runner_versions_exist", self._names_failed(mutated))

    def test_detects_blank_line_inside_list(self) -> None:
        """列表项之间被插入空行 → Markdown 把列表切成两段（渲染断裂）。"""
        mutated = self.original.replace(
            "- **回滚功能不可用**",
            "\n- **回滚功能不可用**",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("no_blank_line_in_list", self._names_failed(mutated))

    def test_detects_missing_top_section(self) -> None:
        """首节缺小节（例如漏写『已知问题』）。"""
        mutated = self.original.replace("### 已知问题", "### 其它", 1)
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("top_sections_present", self._names_failed(mutated))

    def test_gate_is_wired_into_release_script(self) -> None:
        """门禁必须真的接进发布脚本，否则只是一个没人跑的脚本。"""
        script = (ROOT / "scripts" / "build_release_delivery.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/verify_changelog.py", script, "发布脚本未调用 CHANGELOG 门禁")
        self.assertIn(
            "scripts/verify_release_verification.py", script,
            "发布脚本未调用内部验证记录门禁（包 SHA / 任务 ID / 数据比对）",
        )


if __name__ == "__main__":
    unittest.main()
