"""CHANGELOG 门禁（`scripts/verify_changelog.py`）自身的回归锁。

**为什么需要**：CHANGELOG 的过期内容连续被抓出多轮（候选包轮次停在 r37 而实际是
`d235f14c…`、写了不存在的 runner 版本号、「install 直接落 r35 构建」与实测相反、
列表被空行切断）。用户 2026-10-21 明确要求「不靠人眼、靠机器」，因此把门禁做成脚本
（已接入 `scripts/build_release_delivery.sh` 步骤 5.5），这里再用单测锁住**门禁本身的
灵敏度**——否则门禁被弱化（正则写松、检查被删）也不会有任何提示。

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

    def test_detects_stale_package_sha(self) -> None:
        """包换了轮次但 CHANGELOG 的 SHA 没跟（历史真实问题：r37 写成了最终包）。"""
        mutated = self.original.replace(
            "d235f14ca4737b76dec4ac7ff0b42f09fdd0524a8548e067150b48a1b217af34",
            "1601c66afb7321701145907b9f643d5b29b630fbc74a9e0055b8ff74e07bb998",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效：目标 SHA 不在文本中")
        self.assertIn("package_sha_matches_ledger", self._names_failed(mutated))

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
            "状态：**候选，未发布**。**当前候选对",
            "状态：**候选，未发布**。当前候选对 = 平台 r37；**当前候选对",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("no_stale_round_wording", self._names_failed(mutated))

    def test_detects_nonexistent_runner_version(self) -> None:
        """引用不存在的 runner 版本号（历史真实问题：写了已回退的 v0.3.3）。"""
        mutated = self.original.replace(
            "**runner v0.3.2 本火车首次随平台交付**",
            "**runner v0.3.9 本火车首次随平台交付**",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("runner_versions_exist", self._names_failed(mutated))

    def test_detects_blank_line_inside_list(self) -> None:
        """列表项之间被插入空行 → Markdown 把列表切成两段（渲染断裂）。"""
        mutated = self.original.replace(
            "三变体（逐文件独立幂等）；`.12` 复测：三文件全部对齐 v0.3.2。\n- **Test 集群「已分配」恒为 0**",
            "三变体（逐文件独立幂等）；`.12` 复测：三文件全部对齐 v0.3.2。\n\n- **Test 集群「已分配」恒为 0**",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("no_blank_line_in_list", self._names_failed(mutated))

    def test_detects_claim_without_evidence(self) -> None:
        """『✅ 通过』类断言必须带证据（task ID / N PASS / 门禁编号 / 测试名）。"""
        mutated = self.original.replace(
            "| 构建门禁（`.3`，L1） | ✅ 全 PASS：G1 镜像身份 / **G2 runner 交付一致性**"
            "（源码与镜像 `actions.py` 指纹逐字节一致）/ G3 迁移 expand-only / G4 动作词汇冻结 / 对外发布文档脱敏 |",
            "| 构建门禁（`.3`，L1） | ✅ 全部门禁通过 |",
            1,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("verification_claims_have_evidence", self._names_failed(mutated))

    def test_detects_missing_top_section(self) -> None:
        """首节缺小节（例如漏写『已知问题』）。"""
        mutated = self.original.replace("### 已知问题与未解决事项", "### 其它", 1)
        self.assertNotEqual(mutated, self.original, "夹具失效")
        self.assertIn("top_sections_present", self._names_failed(mutated))

    def test_gate_is_wired_into_release_script(self) -> None:
        """门禁必须真的接进发布脚本，否则只是一个没人跑的脚本。"""
        script = (ROOT / "scripts" / "build_release_delivery.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/verify_changelog.py", script, "发布脚本未调用 CHANGELOG 门禁")


if __name__ == "__main__":
    unittest.main()
